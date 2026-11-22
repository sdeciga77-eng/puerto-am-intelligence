"""Configuración centralizada de la plataforma Puerto A&M.

Las credenciales NUNCA se escriben en el frontend: solo se leen de variables de
entorno (o de un archivo .env local que no debe versionarse).
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
FRONTEND_DIR = ROOT / "frontend"


def _load_dotenv() -> None:
    """Carga un .env local sin dependencias externas (las variables reales mandan)."""
    path = ROOT / ".env"
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


_load_dotenv()

# --- Autenticación ---
ADMIN_USER = os.getenv("ADMIN_USER", "admin").strip() or "admin"
ADMIN_PASSWORD = (os.getenv("ADMIN_PASSWORD") or "").strip() or None
ADMIN_PASSWORD_HASH = (os.getenv("ADMIN_PASSWORD_HASH") or "").strip() or None
SESSION_TTL_MINUTES = max(5, int(os.getenv("SESSION_TTL_MINUTES", "480")))
COOKIE_SECURE = _bool("COOKIE_SECURE", False)
TRUST_PROXY = _bool("TRUST_PROXY", False)
ENABLE_DOCS = _bool("ENABLE_DOCS", False)

# --- n8n / automatizaciones ---
N8N_WEBHOOK_TOKEN = (os.getenv("N8N_WEBHOOK_TOKEN") or "").strip() or None
N8N_PUBLIC_WEBHOOK_URL = (os.getenv("N8N_PUBLIC_WEBHOOK_URL") or "").strip() or None
N8N_FINANCE_WEBHOOK_URL = (os.getenv("N8N_FINANCE_WEBHOOK_URL") or "").strip() or None
N8N_ACTIONS_WEBHOOK_URL = (os.getenv("N8N_ACTIONS_WEBHOOK_URL") or "").strip() or None
N8N_CONTACT_WEBHOOK_URL = (os.getenv("N8N_CONTACT_WEBHOOK_URL") or "").strip() or None
WEBHOOK_TIMEOUT_SECONDS = max(2, min(20, int(os.getenv("WEBHOOK_TIMEOUT_SECONDS", "8"))))

# --- OpenRouter (credenciales SOLO en el servidor) ---
OPENROUTER_API_KEY = (os.getenv("OPENROUTER_API_KEY") or "").strip() or None
OPENROUTER_MODEL = (os.getenv("OPENROUTER_MODEL") or "").strip() or "google/gemma-4-26b-a4b-it:free"
OPENROUTER_FALLBACK_MODELS = [
    item.strip()
    for item in (os.getenv("OPENROUTER_FALLBACK_MODELS") or "").split(",")
    if item.strip()
]
OPENROUTER_TIMEOUT_SECONDS = max(5, min(60, int(os.getenv("OPENROUTER_TIMEOUT_SECONDS", "20"))))
OPENROUTER_MAX_TOKENS = max(100, min(1200, int(os.getenv("OPENROUTER_MAX_TOKENS", "450"))))

# --- Datos públicos (nunca financieros) ---
PUBLIC_CONFIG = {
    "restaurant": "Puerto A&M",
    "email": (os.getenv("PUBLIC_EMAIL") or "").strip(),
    "phone": (os.getenv("PUBLIC_PHONE") or "").strip(),
    "address": (os.getenv("PUBLIC_ADDRESS") or "").strip(),
    "hours": (os.getenv("PUBLIC_HOURS") or "").strip(),
    "whatsapp": (os.getenv("PUBLIC_WHATSAPP_URL") or "").strip(),
    "instagram": (os.getenv("PUBLIC_INSTAGRAM_URL") or "").strip(),
}

INTEGRACIONES = {
    "excel": {
        "nombre": "Base de datos Excel (ventas, productos y metas)",
        "configurada": True,
        "detalle": "Fuente local leída en tiempo real con openpyxl.",
    },
    "openrouter": {
        "nombre": "Modelo de lenguaje (OpenRouter)",
        "configurada": bool(OPENROUTER_API_KEY),
        "detalle": "OPENROUTER_API_KEY / OPENROUTER_MODEL" if not OPENROUTER_API_KEY else f"Modelo: {OPENROUTER_MODEL}",
    },
    "n8n_publico": {
        "nombre": "Asistente público (n8n)",
        "configurada": bool(N8N_PUBLIC_WEBHOOK_URL),
        "detalle": "N8N_PUBLIC_WEBHOOK_URL",
    },
    "n8n_financiero": {
        "nombre": "Agente financiero (n8n)",
        "configurada": bool(N8N_FINANCE_WEBHOOK_URL),
        "detalle": "N8N_FINANCE_WEBHOOK_URL",
    },
    "n8n_acciones": {
        "nombre": "Automatizaciones / reportes (n8n)",
        "configurada": bool(N8N_ACTIONS_WEBHOOK_URL),
        "detalle": "N8N_ACTIONS_WEBHOOK_URL",
    },
    "n8n_contacto": {
        "nombre": "Recepción de contactos (n8n)",
        "configurada": bool(N8N_CONTACT_WEBHOOK_URL),
        "detalle": "N8N_CONTACT_WEBHOOK_URL",
    },
    "gmail": {
        "nombre": "Envío de reportes por Gmail",
        "configurada": bool(N8N_ACTIONS_WEBHOOK_URL),
        "detalle": "Requiere workflow de n8n con credencial Gmail OAuth.",
    },
    "google_drive": {
        "nombre": "Respaldo de reportes en Google Drive",
        "configurada": bool(N8N_ACTIONS_WEBHOOK_URL),
        "detalle": "Requiere workflow de n8n con credencial Google Drive OAuth.",
    },
    "national_soft": {
        "nombre": "National Soft (ventas, caja y movimientos)",
        "configurada": bool(N8N_FINANCE_WEBHOOK_URL),
        "detalle": "Requiere workflow de n8n con acceso a National Soft.",
    },
    "cfdi": {
        "nombre": "Facturación CFDI / SAT",
        "configurada": bool(N8N_ACTIONS_WEBHOOK_URL),
        "detalle": "Requiere workflow de n8n con proveedor CFDI autorizado.",
    },
    "bancos": {
        "nombre": "Bancos, pagos y proveedores",
        "configurada": bool(N8N_FINANCE_WEBHOOK_URL),
        "detalle": "Requiere workflow de n8n con conector bancario autorizado.",
    },
}
