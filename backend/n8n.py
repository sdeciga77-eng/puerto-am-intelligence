"""Adaptadores hacia n8n.

Todas las llamadas son POST con timeout, token opcional y respuesta acotada.
Si el webhook no está configurado, se devuelve un estado "pending" y la
aplicación usa su motor local o informa de la integración pendiente. Nunca se
simula una automatización exitosa.
"""

from __future__ import annotations

import html
import json
import re
import urllib.error
import urllib.request
from typing import Any

from . import config

STATUS_PENDING = "pending"
STATUS_OK = "ok"
STATUS_ERROR = "error"

_TEXT_KEYS = ("answer", "text", "message", "response", "output", "reply", "content", "result")

# Patrones que jamás deben aparecer en una respuesta del canal público.
_PUBLIC_BLOCK = re.compile(
    r"(?i)(?:\$\s?\d|\d+\s?(?:mxn|pesos|usd)|factura|cfdi|sat\b|egreso|gasto|"
    r"utilidad|margen|venta|ventas|banco|saldo|proveedor|nómina|nomina|"
    r"contraseña|password|token|webhook|admin|financier|reporte|excel|"
    r"http[s]?://|www\.|[\w.+-]+@[\w-]+\.[\w.-]+)"
)

_TAG_RE = re.compile(r"<[^>]+>")
_SPACES_RE = re.compile(r"\s{2,}")


def is_configured(url: str | None) -> bool:
    return bool(url and url.startswith(("http://", "https://")))


def post_webhook(
    url: str | None,
    payload: dict[str, Any],
    token: str | None = None,
    timeout: int | None = None,
) -> tuple[str, Any, str]:
    """Devuelve (status, payload_respuesta, detalle)."""
    if not is_configured(url):
        return STATUS_PENDING, None, "Webhook no configurado"
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json; charset=utf-8", "Accept": "application/json, text/plain"}
    effective_token = token if token is not None else config.N8N_WEBHOOK_TOKEN
    if effective_token:
        headers["X-Webhook-Token"] = effective_token
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout or config.WEBHOOK_TIMEOUT_SECONDS) as response:
            raw = response.read(200_000).decode("utf-8", errors="replace")
            content_type = response.headers.get("Content-Type", "")
            if "json" in content_type:
                try:
                    return STATUS_OK, json.loads(raw), "Respuesta JSON recibida"
                except json.JSONDecodeError:
                    pass
            return STATUS_OK, raw, "Respuesta de texto recibida"
    except urllib.error.HTTPError as exc:
        return STATUS_ERROR, None, f"HTTP {exc.code}"
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return STATUS_ERROR, None, f"{type(exc).__name__}: {exc}"[:180]
    except Exception as exc:  # pragma: no cover - defensa en profundidad
        return STATUS_ERROR, None, f"Error inesperado: {type(exc).__name__}"[:180]


def extract_text(response: Any) -> str:
    """Extrae texto de las formas habituales de respuesta de n8n."""
    if isinstance(response, str):
        return _clean(response)
    if isinstance(response, list):
        for item in response:
            text = extract_text(item)
            if text:
                return text
        return ""
    if isinstance(response, dict):
        for key in _TEXT_KEYS:
            if key in response:
                text = extract_text(response[key])
                if text:
                    return text
        for key in ("data", "body", "json"):
            if key in response and isinstance(response[key], (dict, list)):
                text = extract_text(response[key])
                if text:
                    return text
    return ""


def _clean(raw: str) -> str:
    text = html.unescape(_TAG_RE.sub(" ", raw))
    return _SPACES_RE.sub(" ", text).strip()[:4000]


def sanitize_public_text(text: str) -> str | None:
    """Bloquea cualquier respuesta que pueda filtrar datos financieros o enlaces."""
    clean = _clean(text)
    if not clean:
        return None
    if _PUBLIC_BLOCK.search(clean):
        return None
    return clean[:1200]


def sanitize_internal_text(text: str) -> str:
    """Para el panel administrativo: se permite contenido financiero, no HTML."""
    clean = _clean(text)
    return clean[:4000] if clean else ""


def send_public_chat(message: str, session_id: str) -> tuple[str, str, str]:
    payload = {
        "source": "public_website",
        "channel": "landing_chat",
        "message": message,
        "sessionId": session_id,
        "timestamp": _timestamp(),
        "policy": (
            "Responde SOLO sobre reservas, horarios, servicios, ubicación y contacto del "
            "restaurante. No menciones ventas, costos, facturas, finanzas, usuarios ni "
            "detalles técnicos. Si no sabes algo, dilo y sugiere el formulario de contacto."
        ),
    }
    status, response, detail = post_webhook(config.N8N_PUBLIC_WEBHOOK_URL, payload)
    if status != STATUS_OK:
        return status, "", detail
    text = extract_text(response)
    safe = sanitize_public_text(text)
    if not safe:
        return STATUS_ERROR, "", "La respuesta del asistente no cumplió la política de contenido público"
    return STATUS_OK, safe, "n8n"


def send_contact(payload: dict[str, Any]) -> tuple[str, str]:
    status, _response, detail = post_webhook(config.N8N_CONTACT_WEBHOOK_URL, payload)
    return status, detail


def send_finance_question(question: str, context: dict[str, Any]) -> tuple[str, str, str]:
    payload = {
        "source": "admin_finance_agent",
        "question": question,
        "context": context,
        "rules": [
            "Usa EXCLUSIVAMENTE las cifras del contexto 'verifiedFacts'.",
            "Si el contexto no contiene el dato, responde que la integración está pendiente.",
            "No inventes importes, fechas ni conclusiones.",
            "Responde en español, con un máximo de 180 palabras.",
        ],
        "responseFormat": "JSON: {\"answer\": \"...\"} o texto plano",
    }
    status, response, detail = post_webhook(config.N8N_FINANCE_WEBHOOK_URL, payload)
    if status != STATUS_OK:
        return status, "", detail
    return STATUS_OK, sanitize_internal_text(extract_text(response)), "n8n"


def send_action(action: str, payload: dict[str, Any], username: str) -> tuple[str, str, str]:
    body = {
        "source": "admin_panel",
        "action": action,
        "requestedBy": username,
        "timestamp": _timestamp(),
        "payload": payload,
    }
    status, response, detail = post_webhook(config.N8N_ACTIONS_WEBHOOK_URL, body)
    if status != STATUS_OK:
        return status, "", detail
    text = extract_text(response)
    return STATUS_OK, sanitize_internal_text(text) or "Acción enviada al workflow de n8n.", "n8n"


def _timestamp() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")
