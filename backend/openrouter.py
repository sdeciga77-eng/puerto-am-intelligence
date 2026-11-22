"""Adaptador de OpenRouter: modelos gratuitos, con cache y fallback.

La credencial vive SOLO en el servidor (.env / variables de entorno). Nunca se
envía al navegador ni se escribe en respuestas, logs o auditoría.

Diseño pensado para la cuota gratuita de la demo (50 peticiones/día):
- Cache en memoria por pregunta, con TTL.
- Si un proveedor gratuito responde 429, se prueba el siguiente modelo de la
  cadena; si todos fallan, la aplicación usa su motor local determinista.
- El contenido se acota y se valida antes de mostrarse.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import threading
import time
import urllib.error
import urllib.request
from typing import Any

from . import config

STATUS_OK = "ok"
STATUS_PENDING = "pending"
STATUS_ERROR = "error"
STATUS_RATE_LIMITED = "rate_limited"

_TAG_RE = re.compile(r"<[^>]+>")
_SPACES_RE = re.compile(r"\s{2,}")
_CACHE_TTL_SECONDS = 1800
_CACHE_MAX = 300

_cache: dict[str, tuple[float, str, str]] = {}
_lock = threading.Lock()


def is_configured() -> bool:
    return bool(config.OPENROUTER_API_KEY)


def _models() -> list[str]:
    candidates = [config.OPENROUTER_MODEL, *config.OPENROUTER_FALLBACK_MODELS]
    seen: set[str] = set()
    return [m for m in candidates if m and not (m in seen or seen.add(m))]


def _clean(raw: str, limit: int) -> str:
    text = html.unescape(_TAG_RE.sub(" ", raw or ""))
    return _SPACES_RE.sub(" ", text).strip()[:limit]


def _cache_get(key: str) -> tuple[str, str] | None:
    with _lock:
        item = _cache.get(key)
        if not item:
            return None
        expires, text, model = item
        if expires < time.monotonic():
            _cache.pop(key, None)
            return None
        return text, model


def _cache_set(key: str, text: str, model: str, ttl_seconds: int) -> None:
    with _lock:
        if len(_cache) >= _CACHE_MAX:
            oldest = min(_cache, key=lambda k: _cache[k][0])
            _cache.pop(oldest, None)
        _cache[key] = (time.monotonic() + ttl_seconds, text, model)


def chat(
    system: str,
    user: str,
    max_tokens: int | None = None,
    temperature: float = 0.2,
    ttl_seconds: int | None = None,
) -> tuple[str, str, str, str]:
    """Devuelve (status, texto, detalle, modelo_usado)."""
    if not is_configured():
        return STATUS_PENDING, "", "OPENROUTER_API_KEY no configurada", ""

    key = hashlib.sha256(
        f"{system}\n{user}\n{max_tokens}\n{temperature}".encode("utf-8")
    ).hexdigest()
    cached = _cache_get(key)
    if cached:
        return STATUS_OK, cached[0], "cache", cached[1]

    headers = {
        "Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
        "Content-Type": "application/json; charset=utf-8",
        "HTTP-Referer": "http://localhost:8000",
        "X-Title": "Puerto A&M Demo",
    }
    base_payload = {
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": max_tokens or config.OPENROUTER_MAX_TOKENS,
        "temperature": temperature,
    }
    ttl = ttl_seconds or _CACHE_TTL_SECONDS

    last_detail = "Sin respuesta del proveedor"
    saw_rate_limit = False
    for model in _models():
        payload = {**base_payload, "model": model}
        request = urllib.request.Request(
            "https://openrouter.ai/api/v1/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=config.OPENROUTER_TIMEOUT_SECONDS) as response:
                result = json.loads(response.read(400_000).decode("utf-8", errors="replace"))
            choice = (result.get("choices") or [{}])[0]
            message = choice.get("message") or {}
            text = _clean(message.get("content") or "", 4000)
            if text:
                _cache_set(key, text, model, ttl)
                return STATUS_OK, text, "openrouter", model
            last_detail = "El modelo devolvió contenido vacío"
        except urllib.error.HTTPError as exc:
            raw = exc.read(500).decode("utf-8", errors="replace")
            if exc.code in (429, 503):
                saw_rate_limit = saw_rate_limit or exc.code == 429
                last_detail = f"HTTP {exc.code}: proveedor ocupado"
            else:
                try:
                    parsed = json.loads(raw)
                    last_detail = parsed.get("error", {}).get("message", f"HTTP {exc.code}")[:160]
                except json.JSONDecodeError:
                    last_detail = f"HTTP {exc.code}"
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_detail = f"{type(exc).__name__}: {exc}"[:160]
        except Exception as exc:  # pragma: no cover - defensa en profundidad
            last_detail = f"Error inesperado: {type(exc).__name__}"[:160]

    return (STATUS_RATE_LIMITED if saw_rate_limit else STATUS_ERROR), "", last_detail, ""


def answer_public(message: str, public_config: dict[str, str]) -> tuple[str, str, str]:
    """Respuesta pública: se construye solo con datos públicos configurados."""
    facts = []
    labels = {
        "hours": "horario",
        "address": "dirección",
        "email": "correo",
        "phone": "teléfono",
        "whatsapp": "WhatsApp",
        "instagram": "Instagram",
    }
    for key, label in labels.items():
        value = public_config.get(key)
        if value:
            facts.append(f"- {label}: {value}")
    known = "\n".join(facts) if facts else "- (sin datos de contacto publicados en este canal)"

    system = (
        "Eres el asistente público de Puerto A&M, un restaurante. "
        "Responde en español, en máximo 80 palabras, de forma cálida y breve. "
        "Solo puedes usar los datos de la lista DATOS PÚBLICOS. "
        "Nunca menciones cifras, ventas, costos, facturas, finanzas, usuarios, paneles "
        "internos, tecnología, correos o enlaces que no estén en esa lista. "
        "Si el dato no está en la lista, sugiere usar el formulario de contacto "
        "y pide fecha, hora y número de personas cuando sea una reserva. "
        "No inventes horarios, precios ni direcciones.\n\n"
        f"DATOS PÚBLICOS:\n{known}"
    )
    status, text, detail, _model = chat(system, message, max_tokens=180, temperature=0.2, ttl_seconds=3600)
    if status != STATUS_OK:
        return status, "", detail
    return STATUS_OK, text, "openrouter"


def rewrite_finance_answer(
    question: str,
    verified_answer: str,
    facts: dict[str, Any],
) -> tuple[str, str, str, str]:
    """Redacta una respuesta ya verificada, sin permitir cifras nuevas."""
    if not is_configured():
        return STATUS_PENDING, "", "OPENROUTER_API_KEY no configurada", ""

    numbers = sorted({_number_key(n) for n in re.findall(r"\d[\d.,]*", verified_answer)} - {None})
    allowed_numbers = ", ".join(str(n) for n in numbers[:40])
    system = (
        "Eres un analista financiero de Puerto A&M. Reescribe el TEXTO VERIFICADO en español "
        "natural, claro y ejecutivo (máximo 140 palabras), sin cambiar el significado. "
        "USA EXCLUSIVAMENTE las cifras que aparecen en el TEXTO VERIFICADO. "
        "No añadas importes, porcentajes, fechas, conclusiones ni datos nuevos. "
        "Conserva literalmente las expresiones 'costo de ventas', 'no he inventado', "
        "'pendiente' y 'margen bruto' cuando aparezcan en el texto original. "
        "Conserva también los símbolos $, % y MXN y el formato de las cifras. "
        "No uses markdown, listas numeradas ni enlaces. "
        f"Cifras autorizadas: {allowed_numbers or '(ninguna)'}."
    )
    user = f"Pregunta del administrador: {question}\n\nTEXTO VERIFICADO:\n{verified_answer}"
    status, text, detail, model = chat(system, user, max_tokens=380, temperature=0.15, ttl_seconds=900)
    if status != STATUS_OK:
        return status, "", detail, ""

    # Validación posterior: ninguna cifra nueva y frases críticas conservadas.
    generated = {_number_key(n) for n in re.findall(r"\d[\d.,]*", text)}
    generated.discard(None)
    if generated - set(numbers):
        return STATUS_ERROR, "", "El modelo introdujo cifras no verificadas", model
    lower = text.lower()
    for phrase in ("costo de ventas", "no he inventado", "pendiente", "margen bruto"):
        if phrase in verified_answer.lower() and phrase not in lower:
            return STATUS_ERROR, "", f"El modelo omitió la frase obligatoria '{phrase}'", model
    return STATUS_OK, text, "openrouter", model


def _number_key(raw: str) -> float | None:
    try:
        return round(float(raw.replace(",", "")), 2)
    except ValueError:
        return None
