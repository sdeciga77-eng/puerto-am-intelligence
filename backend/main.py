"""API y servidor unificado de Puerto A&M.

- Pública: landing, chat con políticas de contenido, formulario de contacto.
- Privada: dashboard ejecutivo, agente financiero y automatizaciones n8n.

Toda ruta que devuelve información financiera exige sesión. Los archivos HTML
privados viven fuera del directorio estático para no poder sortear la auth.
"""

from __future__ import annotations

import csv
import io
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from pydantic import BaseModel, Field

from . import agent, config, n8n, openrouter, public_kb, security
from .repository import (
    DISCLAIMER,
    EXCEL_PATH,
    build_dashboard,
    filter_sales,
    read_workbook,
)

ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIR = config.FRONTEND_DIR
PRIVATE_DIR = ROOT / "private"

_ADMIN_USER, _ADMIN_HASH, _BOOTSTRAP_PASSWORD = security.ensure_admin_credentials()

app = FastAPI(
    title="Puerto A&M | Plataforma",
    description="Landing pública y panel financiero autenticado con agentes n8n.",
    version="2.0.0",
    docs_url="/docs" if config.ENABLE_DOCS else None,
    redoc_url=None,
    openapi_url="/openapi.json" if config.ENABLE_DOCS else None,
)

# CORS cerrado: el frontend se sirve desde el mismo origen.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", security.CSRF_HEADER],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    response.headers["Cache-Control"] = "no-store" if request.url.path.startswith(("/api", "/admin")) else "public, max-age=60"
    forwarded_proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    secure = request.url.scheme == "https" or forwarded_proto == "https" or config.COOKIE_SECURE
    csp = (
        "default-src 'self'; "
        "base-uri 'none'; object-src 'none'; frame-ancestors 'none'; form-action 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com data:; "
        "img-src 'self' data:; connect-src 'self'"
    )
    response.headers["Content-Security-Policy"] = csp
    if secure:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


# --------------------------------------------------------------------------- #
# Modelos de entrada
# --------------------------------------------------------------------------- #
class LoginIn(BaseModel):
    username: str = Field(default="", max_length=80)
    password: str = Field(default="", max_length=200)


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=500)
    sessionId: str | None = Field(default=None, max_length=80)


class ContactIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    email: str = Field(max_length=254)
    phone: str = Field(default="", max_length=40)
    topic: str = Field(default="General", max_length=40)
    message: str = Field(min_length=10, max_length=1500)
    website: str = Field(default="", max_length=100)  # honeypot anti-bots


class AgentIn(BaseModel):
    message: str = Field(min_length=1, max_length=500)


class ActionIn(BaseModel):
    action: str = Field(min_length=2, max_length=60)
    confirm: bool = False
    payload: dict[str, Any] = Field(default_factory=dict)


ALLOWED_ACTIONS = {
    "generate_report": "Generar reporte ejecutivo",
    "email_report": "Enviar reporte por Gmail",
    "drive_backup": "Guardar reporte en Google Drive",
    "sync_national_soft": "Sincronizar movimientos de National Soft",
    "request_cfdi_report": "Solicitar reporte de facturas CFDI",
}


# --------------------------------------------------------------------------- #
# Rutas HTML
# --------------------------------------------------------------------------- #
def _session_from_request(request: Request):
    return security.sessions.get(request.cookies.get(security.SESSION_COOKIE))


@app.get("/", include_in_schema=False)
def landing():
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/admin", include_in_schema=False)
@app.get("/admin/", include_in_schema=False)
def admin_root(request: Request):
    if _session_from_request(request):
        return RedirectResponse("/admin/dashboard", status_code=303)
    return RedirectResponse("/admin/login", status_code=303)


@app.get("/admin/login", include_in_schema=False)
def admin_login(request: Request):
    if _session_from_request(request):
        return RedirectResponse("/admin/dashboard", status_code=303)
    return FileResponse(PRIVATE_DIR / "login.html")


@app.get("/admin/dashboard", include_in_schema=False)
def admin_dashboard(request: Request):
    if not _session_from_request(request):
        return RedirectResponse("/admin/login", status_code=303)
    return FileResponse(PRIVATE_DIR / "dashboard.html")


# --------------------------------------------------------------------------- #
# Salud y configuración pública
# --------------------------------------------------------------------------- #
@app.get("/api/health")
def health():
    return {
        "estatus": "ok",
        "excelExiste": EXCEL_PATH.exists(),
        "asistentePublico": (
            "conectado"
            if n8n.is_configured(config.N8N_PUBLIC_WEBHOOK_URL) or openrouter.is_configured()
            else "pendiente"
        ),
        "panelFinanciero": "protegido",
    }


@app.get("/api/public/config")
def public_config():
    return config.PUBLIC_CONFIG


# --------------------------------------------------------------------------- #
# Chat público (sin datos financieros)
# --------------------------------------------------------------------------- #
@app.post("/api/public/chat")
def public_chat(body: ChatIn, request: Request):
    ip = security.client_ip(request)
    if not security.limiter.allow(f"chat:{ip}", 25, 60):
        raise HTTPException(status_code=429, detail="Demasiados mensajes. Intenta de nuevo en un minuto.")

    message = security.clean_text(body.message, 500)
    if not message:
        raise HTTPException(status_code=422, detail="Mensaje vacío")

    # GuardrailBefore: nociones financieras jamás se envían al workflow público.
    if public_kb._FINANCIAL_HINT.search(public_kb._normalize(message)):
        return {
            "answer": public_kb.BLOCKED,
            "mode": "guardrail",
            "suggestions": public_kb.SUGGESTIONS,
        }

    status, text, detail = n8n.send_public_chat(message, body.sessionId or "anon")
    if status == n8n.STATUS_OK and text:
        return {"answer": text, "mode": "n8n", "suggestions": public_kb.SUGGESTIONS}

    # Modelo gratuito de OpenRouter: se_validan los datos públicos permitidos.
    if openrouter.is_configured():
        ai_status, ai_text, _ai_detail = openrouter.answer_public(message, config.PUBLIC_CONFIG)
        if ai_status == openrouter.STATUS_OK and ai_text:
            safe = n8n.sanitize_public_text(ai_text)
            if safe:
                return {"answer": safe, "mode": "openrouter", "suggestions": public_kb.SUGGESTIONS}

    notice = (
        "El asistente en línea no está disponible en este momento; te respondo con información "
        "pública verificada de este sitio."
    )
    return {
        "answer": f"{notice}\n\n{public_kb.answer(message)}",
        "mode": "local",
        "suggestions": public_kb.SUGGESTIONS,
        "integration": "pendiente" if status == n8n.STATUS_PENDING else "sin conexión",
        "detail": detail[:80] if status == n8n.STATUS_ERROR else None,
    }


@app.post("/api/public/contact")
def public_contact(body: ContactIn, request: Request):
    ip = security.client_ip(request)
    if not security.limiter.allow(f"contact:{ip}", 5, 600):
        raise HTTPException(status_code=429, detail="Demasiadas solicitudes. Intenta de nuevo en 10 minutos.")
    if body.website.strip():
        return {"ok": True, "reference": "PA-DESCARTADO", "note": "Solicitud ignorada."}
    if not security.valid_email(body.email):
        raise HTTPException(status_code=422, detail="Correo electrónico no válido")

    topics = {"General", "Reserva", "Evento", "Catering", "Carta", "Prensa", "Otro"}
    topic = body.topic if body.topic in topics else "General"
    stamp = datetime.now()
    reference = f"PA-{stamp:%Y%m%d}-{security.secrets.token_hex(3).upper()}"
    record = {
        "reference": reference,
        "createdAt": stamp.isoformat(timespec="seconds"),
        "name": security.clean_text(body.name, 80),
        "email": security.clean_text(body.email, 254),
        "phone": security.clean_text(body.phone, 40),
        "topic": topic,
        "message": security.clean_text(body.message, 1500),
        "sourceIp": ip,
    }
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    with security.CONTACT_FILE.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    delivery = "local"
    if n8n.is_configured(config.N8N_CONTACT_WEBHOOK_URL):
        status, detail = n8n.send_contact(record)
        delivery = "n8n" if status == n8n.STATUS_OK else f"pendiente: {detail[:60]}"
    security.audit("contact_created", "", reference)
    return {
        "ok": True,
        "reference": reference,
        "delivery": delivery,
        "message": "Recibimos tu mensaje. Te responderemos al correo indicado.",
    }


# --------------------------------------------------------------------------- #
# Autenticación
# --------------------------------------------------------------------------- #
@app.post("/api/auth/login")
def login(body: LoginIn, request: Request):
    ip = security.client_ip(request)
    key = f"login:{ip}:{body.username[:40]}"
    if not security.limiter.allow(key, 6, 900):
        raise HTTPException(status_code=429, detail="Demasiados intentos. Intenta de nuevo en 15 minutos.")

    user_ok = bool(body.username) and security.hmac.compare_digest(body.username, _ADMIN_USER)
    password_ok = security.verify_password(_ADMIN_HASH, body.password)
    if not (user_ok and password_ok):
        security.audit("login_failed", body.username[:40], ip)
        raise HTTPException(status_code=401, detail="Credenciales inválidas")

    token, session = security.sessions.create(_ADMIN_USER)
    response = JSONResponse(
        {
            "ok": True,
            "username": _ADMIN_USER,
            "csrfToken": session["csrf"],
            "expiresAt": session["expires"].isoformat(),
        }
    )
    security.set_session_cookie(response, token)
    security.audit("login_ok", _ADMIN_USER, ip)
    return response


@app.get("/api/auth/me")
def me(session: dict[str, Any] = Depends(security.require_admin)):
    return {
        "username": session["username"],
        "csrfToken": session["csrf"],
        "expiresAt": session["expires"].isoformat(),
    }


@app.post("/api/auth/logout")
def logout(
    request: Request,
    session: dict[str, Any] = Depends(security.require_csrf),
):
    token = request.cookies.get(security.SESSION_COOKIE)
    security.sessions.destroy(token)
    response = JSONResponse({"ok": True})
    security.clear_session_cookie(response)
    security.audit("logout", session["username"], security.client_ip(request))
    return response


# --------------------------------------------------------------------------- #
# Panel administrativo (protegido)
# --------------------------------------------------------------------------- #
@app.get("/api/admin/integrations")
def integrations(_session=Depends(security.require_admin)):
    result = {}
    for key, item in config.INTEGRACIONES.items():
        result[key] = {
            "nombre": item["nombre"],
            "estado": "conectado" if item["configurada"] else "pendiente",
            "detalle": item["detalle"] if not item["configurada"] else "Canal configurado; verificar workflow en n8n.",
        }
    return result


@app.get("/api/admin/anomalias")
def anomalias(_session=Depends(security.require_admin)):
    return {"alertas": agent.compute_anomalies(), "fuente": EXCEL_PATH.name, "disclaimer": DISCLAIMER}


@app.post("/api/admin/agent")
def financial_agent(body: AgentIn, request: Request, session=Depends(security.require_csrf)):
    message = security.clean_text(body.message, 500)
    if not message:
        raise HTTPException(status_code=422, detail="Pregunta vacía")
    result = agent.answer_question(message)
    security.audit("agent_question", session["username"], result["intent"])
    return result


@app.post("/api/admin/actions")
def admin_action(body: ActionIn, request: Request, session=Depends(security.require_csrf)):
    if body.action not in ALLOWED_ACTIONS:
        raise HTTPException(status_code=422, detail="Acción no permitida")
    if not body.confirm:
        raise HTTPException(status_code=422, detail="Se requiere confirmación explícita")

    if not n8n.is_configured(config.N8N_ACTIONS_WEBHOOK_URL):
        security.audit("action_pending", session["username"], body.action)
        return {
            "estado": "pendiente",
            "accion": body.action,
            "message": (
                f"Integración pendiente: configura N8N_ACTIONS_WEBHOOK_URL y el workflow de n8n "
                f"para «{ALLOWED_ACTIONS[body.action]}». No se simuló ningún envío."
            ),
        }

    status, text, detail = n8n.send_action(body.action, body.payload, session["username"])
    security.audit(f"action_{status}", session["username"], body.action)
    if status != n8n.STATUS_OK:
        return {"estado": "error", "accion": body.action, "message": f"No se pudo ejecutar: {detail}"}
    return {"estado": "enviado", "accion": body.action, "message": text, "detalle": "Confirmado por n8n."}


@app.get("/api/admin/status")
def admin_status(_session=Depends(security.require_admin)):
    try:
        data = read_workbook()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "archivo": EXCEL_PATH.name,
        "ultimaModificacion": data["lastModified"],
        "registros": len(data["sales"]),
        "hojas": ["Ventas", "Productos", "Metas", "Instrucciones"],
        "disclaimer": DISCLAIMER,
    }


@app.get("/api/admin/dashboard")
def admin_dashboard_api(
    fecha_desde: str | None = Query(default=None, alias="fecha_desde"),
    fecha_hasta: str | None = Query(default=None, alias="fecha_hasta"),
    producto: str | None = Query(default=None),
    categoria: str | None = Query(default=None),
    _session=Depends(security.require_admin),
):
    try:
        return build_dashboard(fecha_desde, fecha_hasta, producto, categoria)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


EXPORT_COLUMNS = [
    ("fecha", "Fecha"),
    ("pedido", "Pedido"),
    ("producto", "Producto"),
    ("categoria", "Categoría"),
    ("cantidad", "Cantidad"),
    ("precio", "Precio Unitario (MXN)"),
    ("costo", "Costo Unitario (MXN)"),
    ("canal", "Canal"),
    ("pago", "Método de Pago"),
    ("ingreso", "Ingreso (MXN)"),
    ("costoTotal", "Costo Total (MXN)"),
    ("utilidad", "Utilidad (MXN)"),
]
CURRENCY_FMT = '"$"#,##0.00'


def _filtered_rows(fecha_desde, fecha_hasta, producto, categoria):
    data = read_workbook()
    rows, _, _ = filter_sales(data["sales"], fecha_desde, fecha_hasta, producto, categoria)
    return sorted(rows, key=lambda r: (r["fecha"], r["pedido"]), reverse=True)


@app.get("/api/admin/exportar")
def admin_exportar(
    formato: str = Query(default="csv", pattern="^(csv|xlsx|json)$"),
    fecha_desde: str | None = Query(default=None, alias="fecha_desde"),
    fecha_hasta: str | None = Query(default=None, alias="fecha_hasta"),
    producto: str | None = Query(default=None),
    categoria: str | None = Query(default=None),
    _session=Depends(security.require_admin),
):
    rows = _filtered_rows(fecha_desde, fecha_hasta, producto, categoria)
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    filename = f"PuertoAM_Reporte_{stamp}.{formato}"
    content_disposition = f"attachment; filename*=UTF-8''{quote(filename)}"

    if formato == "json":
        payload = {
            "disclaimer": DISCLAIMER,
            "fuente": EXCEL_PATH.name,
            "registros": len(rows),
            "ventasTotales": round(sum(r["ingreso"] for r in rows), 2),
            "utilidadBruta": round(sum(r["utilidad"] for r in rows), 2),
            "datos": [
                {label: row[key].isoformat() if key == "fecha" else row[key] for key, label in EXPORT_COLUMNS}
                for row in rows
            ],
        }
        return JSONResponse(content=payload, headers={"Content-Disposition": content_disposition})

    if formato == "csv":
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow([label for _, label in EXPORT_COLUMNS])
        for row in rows:
            writer.writerow(
                [row["fecha"].strftime("%d/%m/%Y") if key == "fecha" else row[key] for key, _ in EXPORT_COLUMNS]
            )
        writer.writerow([])
        writer.writerow(["SIMULACIÓN ACADÉMICA — datos ficticios", DISCLAIMER])
        writer.writerow(
            [
                "TOTALES", "", "", "", sum(r["cantidad"] for r in rows), "", "", "", "",
                round(sum(r["ingreso"] for r in rows), 2),
                round(sum(r["costoTotal"] for r in rows), 2),
                round(sum(r["utilidad"] for r in rows), 2),
            ]
        )
        return Response(
            content=buffer.getvalue().encode("utf-8-sig"),
            media_type="text/csv; charset=utf-8-sig",
            headers={"Content-Disposition": content_disposition},
        )

    wb = Workbook()
    ws = wb.active
    ws.title = "Reporte"
    ws.append([label for _, label in EXPORT_COLUMNS])
    for row in rows:
        ws.append([row["fecha"].strftime("%d/%m/%Y") if key == "fecha" else row[key] for key, _ in EXPORT_COLUMNS])
        if ws.max_row % 2 == 0:
            for cell in ws[ws.max_row]:
                cell.fill = PatternFill("solid", fgColor="F2F5F8")
    for cell in ws[1]:
        cell.fill = PatternFill("solid", fgColor="0B2338")
        cell.font = Font(color="FFFFFF", bold=True)
        cell.alignment = Alignment(vertical="center")
    ws.row_dimensions[1].height = 26
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:L{ws.max_row}"
    for idx, width in enumerate([13, 17, 31, 23, 11, 19, 19, 17, 19, 17, 17, 17], start=1):
        ws.column_dimensions[chr(64 + idx)].width = width
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row):
        for cell in row:
            if cell.column in (6, 7, 10, 11, 12):
                cell.number_format = CURRENCY_FMT
    total_row = ws.max_row + 2
    ws.cell(row=total_row, column=1, value="TOTALES").font = Font(bold=True, color="0B2338")
    ws.cell(row=total_row, column=5, value=sum(r["cantidad"] for r in rows))
    for col, key in ((10, "ingreso"), (11, "costoTotal"), (12, "utilidad")):
        cell = ws.cell(row=total_row, column=col, value=round(sum(r[key] for r in rows), 2))
        cell.number_format = CURRENCY_FMT
        cell.font = Font(bold=True)
    note_row = total_row + 2
    ws.cell(row=note_row, column=1, value=f"Fuente: {EXCEL_PATH.name} · {DISCLAIMER}")
    ws.cell(row=note_row, column=1).font = Font(italic=True, size=9, color="667788")
    output = io.BytesIO()
    wb.save(output)
    return Response(
        content=output.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": content_disposition},
    )


# Alias legacy: siguen protegidos para no exponer información financiera.
app.add_api_route("/api/dashboard", admin_dashboard_api, methods=["GET"], include_in_schema=False)
app.add_api_route("/api/exportar", admin_exportar, methods=["GET"], include_in_schema=False)
app.add_api_route("/api/status", admin_status, methods=["GET"], include_in_schema=False)


@app.on_event("startup")
def startup_notice() -> None:
    print("\n" + "=" * 68)
    print("  PUERTO A&M | PLATAFORMA SEGURA")
    print("  Landing:  http://127.0.0.1:8000/")
    print("  Panel:    http://127.0.0.1:8000/admin")
    if _BOOTSTRAP_PASSWORD:
        print("  Credencial de primer ingreso (se muestra UNA sola vez):")
        print(f"    usuario: {_ADMIN_USER}")
        print(f"    password: {_BOOTSTRAP_PASSWORD}")
        print("  Cambia esta contraseña definiendo ADMIN_PASSWORD_HASH en .env")
    print("=" * 68 + "\n")


app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
