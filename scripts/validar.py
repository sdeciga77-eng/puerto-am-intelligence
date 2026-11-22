"""Validación integral: Excel real, autenticación, API, agente y exportación.

Uso (servidor corriendo en 127.0.0.1:8000):
    $env:ADMIN_PASSWORD="tu_password"
    python scripts/validar.py

Si la credencial se generó automáticamente, usa esa contraseña de primer ingreso.
"""

from __future__ import annotations

import http.cookiejar
import io
import json
import os
import shutil
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import date, datetime
from pathlib import Path

from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[1]
EXCEL = ROOT / "data" / "Puerto_AM_Base_Datos_DEMO.xlsx"
BACKUP = ROOT / "data" / "_validacion_backup.xlsx"
BASE = "http://127.0.0.1:8000"

passed = 0
failed = 0
COOKIE_JAR = http.cookiejar.CookieJar()
OPENER = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(COOKIE_JAR))


def check(name: str, condition: bool, detail: str = "") -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"[OK]   {name}" + (f" — {detail}" if detail else ""))
    else:
        failed += 1
        print(f"[FAIL] {name}" + (f" — {detail}" if detail else ""))


def api(path: str, params: dict | None = None):
    url = BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    with OPENER.open(url, timeout=20) as response:
        return response.read(), response.headers.get("Content-Type", "")


def api_json(path: str, params: dict | None = None) -> dict:
    raw, _ = api(path, params)
    return json.loads(raw.decode("utf-8"))


def post_json(path: str, payload: dict, extra_headers: dict | None = None) -> tuple[int, dict]:
    headers = {"Content-Type": "application/json"}
    headers.update(extra_headers or {})
    request = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with OPENER.open(request, timeout=20) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8", errors="replace"))


def login() -> str:
    password = os.getenv("ADMIN_PASSWORD") or os.getenv("PA_TEST_PASSWORD") or ""
    if not password:
        raise SystemExit("Define ADMIN_PASSWORD con la contraseña del administrador antes de validar.")
    username = os.getenv("ADMIN_USER", "admin")
    status, payload = post_json("/api/auth/login", {"username": username, "password": password})
    check("Login con credenciales válidas", status == 200 and payload.get("ok"), f"HTTP {status}")
    if status != 200:
        raise SystemExit("No se pudo autenticar; el resto de pruebas requiere sesión.")
    return payload["csrfToken"]


def excel_rows():
    wb = load_workbook(EXCEL, read_only=True, data_only=False)
    try:
        ws = wb["Ventas"]
        rows = list(ws.iter_rows(values_only=True))
        return rows[0], [r for r in rows[1:] if any(cell is not None for cell in r)]
    finally:
        wb.close()


def recompute(rows):
    ingreso = sum(float(r[4]) * float(r[5]) for r in rows)
    costo = sum(float(r[4]) * float(r[6]) for r in rows)
    pedidos = len({str(r[1]) for r in rows})
    return {
        "ingreso": round(ingreso, 2), "costo": round(costo, 2),
        "utilidad": round(ingreso - costo, 2), "unidades": int(sum(float(r[4]) for r in rows)),
        "pedidos": pedidos, "ticket": round(ingreso / pedidos, 2) if pedidos else 0,
        "margen": round((ingreso - costo) / ingreso * 100, 2) if ingreso else 0,
    }


def main() -> int:
    print("=" * 72)
    print("PUERTO A&M | VALIDACIÓN DE SEGURIDAD, DATOS REALES Y AGENTE")
    print("=" * 72)

    # 1. Estructura del Excel
    wb = load_workbook(EXCEL, read_only=False, data_only=False)
    check("Hojas del Excel", wb.sheetnames == ["Ventas", "Productos", "Metas", "Instrucciones"], str(wb.sheetnames))
    ws = wb["Ventas"]
    check("Fórmulas en columnas de cálculo", all(str(ws.cell(2, c).value).startswith("=") for c in (10, 11, 12)))
    check("Filtros/tablas aplicados", len(ws.tables) == 1 and ws.auto_filter.ref is not None)
    check("Formato de moneda MXN", "$" in ws.cell(2, 6).number_format)
    check("Congelación de encabezado", ws.freeze_panes == "A2")
    wb.close()

    header, data = excel_rows()
    check("Mínimo 300 registros en Ventas", len(data) >= 300, f"{len(data)} registros")
    expected = recompute(data)
    months = Counter()
    for row in data:
        value = row[0]
        if isinstance(value, (datetime, date)):
            months[value.strftime("%Y-%m")] += 1
    check("Datos en enero-marzo 2026", set(months) == {"2026-01", "2026-02", "2026-03"}, str(dict(months)))

    # 2. La zona pública no expone finanzas
    health = api_json("/api/health")
    check("Health público sin cifras", "ventasTotales" not in health and health.get("panelFinanciero") == "protegido")
    status_public, guard = post_json("/api/public/chat", {"message": "¿Cuánto gastamos este mes?"})
    check("Chat público bloquea temas financieros", status_public == 200 and guard.get("mode") == "guardrail")
    status_public, local_chat = post_json("/api/public/chat", {"message": "¿Cómo reservo?"})
    check("Chat público responde temas permitidos", status_public == 200 and bool(local_chat.get("answer")))

    # 3. Autenticación obligatoria
    try:
        api("/api/admin/dashboard")
        check("API financiera exige sesión", False, "respondió sin autenticar")
    except urllib.error.HTTPError as exc:
        check("API financiera exige sesión", exc.code == 401, f"HTTP {exc.code}")
    csrf = login()
    me = api_json("/api/auth/me")
    check("Endpoint /me accesible con sesión", bool(me.get("csrfToken")), f"usuario {me.get('username')}")
    status_bad, _ = post_json("/api/admin/agent", {"message": "hola"}, {})
    check("CSRF requerido en POST admin", status_bad == 403, f"HTTP {status_bad}")

    # 4. Dashboard y cálculos
    dashboard = api_json("/api/admin/dashboard")
    kpis = dashboard["kpis"]
    check("API registros = Excel", kpis["registros"] == len(data), f"API={kpis['registros']} Excel={len(data)}")
    check("Ventas totales correctas", abs(kpis["ventasTotales"] - expected["ingreso"]) < 0.05, f"{kpis['ventasTotales']} vs {expected['ingreso']}")
    check("Costos correctos", abs(kpis["costos"] - expected["costo"]) < 0.05)
    check("Utilidad bruta correcta", abs(kpis["utilidadBruta"] - expected["utilidad"]) < 0.05)
    check("Pedidos únicos correctos", kpis["pedidos"] == expected["pedidos"], str(kpis["pedidos"]))
    check("Unidades correctas", kpis["unidadesVendidas"] == expected["unidades"])
    check("Ticket promedio correcto", abs(kpis["ticketPromedio"] - expected["ticket"]) < 0.05)
    check("Margen bruto correcto", abs(kpis["margenBruto"] - expected["margen"]) < 0.05)
    check("Crecimiento mensual presente", kpis["crecimientoMensual"] is not None, f"{kpis['crecimientoMensual']}%")
    check("Cumplimiento de metas presente", kpis["cumplimientoMetas"] is not None, f"{kpis['cumplimientoMetas']}%")
    check("Tabla completa", dashboard["tabla"]["total"] == len(data))

    # 5. Filtros
    first_product = sorted({str(r[2]) for r in data})[0]
    filtered = api_json("/api/admin/dashboard", {"producto": first_product})
    subset = [r for r in data if str(r[2]) == first_product]
    check("Filtro por producto", filtered["kpis"]["ventasTotales"] == recompute(subset)["ingreso"], first_product)
    check("Filtro por producto reduce registros", filtered["kpis"]["registros"] == len(subset))
    first_category = sorted({str(r[3]) for r in data})[0]
    filtered = api_json("/api/admin/dashboard", {"categoria": first_category})
    subset = [r for r in data if str(r[3]) == first_category]
    check("Filtro por categoría", filtered["kpis"]["ventasTotales"] == recompute(subset)["ingreso"])
    filtered = api_json("/api/admin/dashboard", {"fecha_desde": "2026-02-01", "fecha_hasta": "2026-02-28"})
    subset = [r for r in data if r[0].strftime("%Y-%m-%d") >= "2026-02-01" and r[0].strftime("%Y-%m-%d") <= "2026-02-28"]
    check("Filtro por fecha", filtered["kpis"]["ventasTotales"] == recompute(subset)["ingreso"], f"{len(subset)} registros")
    combo = api_json("/api/admin/dashboard", {"fecha_desde": "2026-03-01", "fecha_hasta": "2026-03-31", "categoria": first_category})
    subset = [r for r in data if r[0].strftime("%Y-%m-%d") >= "2026-03-01" and str(r[3]) == first_category]
    check("Filtros combinados", combo["kpis"]["ventasTotales"] == recompute(subset)["ingreso"])

    # 6. Agente financiero con cifras reales e integraciones pendientes
    # El agente informa el ÚLTIMO mes con datos (marzo 2026), no el acumulado.
    expected_month = recompute([r for r in data if r[0].strftime("%Y-%m") == "2026-03"])
    status_agent, agent_sales = post_json("/api/admin/agent", {"message": "¿Cómo van las ventas?"}, {"X-CSRF-Token": csrf})
    facts = agent_sales.get("verifiedFacts", {})
    check("Agente responde ventas reales", status_agent == 200 and abs(facts.get("ventas", 0) - expected_month["ingreso"]) < 0.05, f"agente={facts.get('ventas')} excel={expected_month['ingreso']}")
    status_agent, agent_spend = post_json("/api/admin/agent", {"message": "¿Cuánto gastamos este mes?"}, {"X-CSRF-Token": csrf})
    check("Agente gasto = costo real", status_agent == 200 and abs(agent_spend.get("verifiedFacts", {}).get("costos", 0) - expected_month["costo"]) < 0.05 and "costo de ventas" in agent_spend.get("answer", "").lower())
    status_agent, agent_invoice = post_json("/api/admin/agent", {"message": "¿Qué facturas faltan?"}, {"X-CSRF-Token": csrf})
    check("Agente no inventa facturas", status_agent == 200 and "pendiente" in agent_invoice.get("answer", "").lower() and "no he inventado" in agent_invoice.get("answer", "").lower())
    integrations = api_json("/api/admin/integrations")
    check("Integraciones informan estado real", all("estado" in v for v in integrations.values()), f"{len(integrations)} integraciones")
    status_action, action = post_json("/api/admin/actions", {"action": "email_report", "confirm": True}, {"X-CSRF-Token": csrf})
    check("Acción sin webhook no simula envío", status_action == 200 and action.get("estado") == "pendiente")

    # 7. Exportación
    for formato in ("csv", "xlsx", "json"):
        raw, ctype = api("/api/admin/exportar", {"formato": formato})
        check(f"Exportación {formato.upper()}", len(raw) > 100, f"{len(raw)} bytes · {ctype.split(';')[0]}")

    # 8. Ciclo real de edición → actualización
    shutil.copy2(EXCEL, BACKUP)
    try:
        wb = load_workbook(EXCEL)
        ws = wb["Ventas"]
        old_qty = float(ws.cell(2, 5).value)
        price = float(ws.cell(2, 6).value)
        ws.cell(2, 5, value=old_qty + 1)
        wb.save(EXCEL)
        edited = api_json("/api/admin/dashboard", {"_": "editado"})
        delta = round(edited["kpis"]["ventasTotales"] - kpis["ventasTotales"], 2)
        check("Editar Excel cambia el dashboard", abs(delta - price) < 0.05, f"Delta={delta}, precio={price}")
        check("Editar Excel cambia la utilidad", edited["kpis"]["utilidadBruta"] != kpis["utilidadBruta"])
        shutil.copy2(BACKUP, EXCEL)
        restored = api_json("/api/admin/dashboard", {"_": "restaurado"})
        check("Dashboard se restaura al recuperar el Excel", abs(restored["kpis"]["ventasTotales"] - kpis["ventasTotales"]) < 0.05)
    finally:
        if BACKUP.exists():
            BACKUP.unlink()

    print("=" * 72)
    print(f"RESULTADO: {passed} correctos · {failed} fallidos")
    print("=" * 72)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
