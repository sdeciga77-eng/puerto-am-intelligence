"""Autenticación, sesiones, CSRF, rate limiting y auditoría.

Diseñado para producción: cookies HttpOnly + SameSite=Strict, hash PBKDF2,
comparación en tiempo constante y auditoría de eventos sensibles.
El store de sesiones es en memoria (apropiado para una instancia); para
múltiples réplicas, sustituir por Redis/DB conservando la misma interfaz.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import Depends, HTTPException, Request, status

from . import config

PBKDF2_ALGO = "pbkdf2_sha256"
PBKDF2_ITERATIONS = 310_000
SECRET_FILE = config.DATA_DIR / "admin_secret.json"
AUDIT_FILE = config.DATA_DIR / "audit.log"
CONTACT_FILE = config.DATA_DIR / "contact_requests.json"

SESSION_COOKIE = "pa_session"
CSRF_HEADER = "X-CSRF-Token"


# --------------------------------------------------------------------------- #
# Contraseñas
# --------------------------------------------------------------------------- #
def hash_password(password: str, iterations: int = PBKDF2_ITERATIONS) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"{PBKDF2_ALGO}${iterations}${salt.hex()}${digest.hex()}"


def verify_password(stored: str, provided: str) -> bool:
    try:
        algo, iterations, salt_hex, digest_hex = stored.split("$", 3)
        if algo != PBKDF2_ALGO:
            return False
        candidate = hashlib.pbkdf2_hmac(
            "sha256", provided.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations)
        )
        return hmac.compare_digest(candidate.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def ensure_admin_credentials() -> tuple[str, str, str | None]:
    """Devuelve (usuario, hash, password_generada_o_None).

    Prioridad: ADMIN_PASSWORD_HASH > ADMIN_PASSWORD > archivo local bootstrap.
    Si no hay nada configurado, genera una credencial aleatoria de un solo uso
    que debe mostrarse una única vez en la consola del servidor.
    """
    username = config.ADMIN_USER
    if config.ADMIN_PASSWORD_HASH:
        return username, config.ADMIN_PASSWORD_HASH, None
    if config.ADMIN_PASSWORD:
        return username, hash_password(config.ADMIN_PASSWORD), None

    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    if SECRET_FILE.exists():
        payload = json.loads(SECRET_FILE.read_text(encoding="utf-8"))
        stored_user = str(payload.get("username", username))
        stored_hash = str(payload.get("hash", ""))
        if stored_hash:
            return stored_user, stored_hash, None

    generated = secrets.token_urlsafe(15)
    record = {
        "username": username,
        "hash": hash_password(generated),
        "createdAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "note": "Solo hash. La contraseña se mostró una vez al iniciar el servidor.",
    }
    SECRET_FILE.write_text(json.dumps(record, indent=2), encoding="utf-8")
    try:
        SECRET_FILE.chmod(0o600)
    except OSError:
        pass
    return username, record["hash"], generated


# --------------------------------------------------------------------------- #
# Sesiones y CSRF
# --------------------------------------------------------------------------- #
class SessionStore:
    def __init__(self, ttl_minutes: int) -> None:
        self.ttl = timedelta(minutes=ttl_minutes)
        self._sessions: dict[str, dict[str, Any]] = {}

    def _cleanup(self) -> None:
        now = datetime.now(timezone.utc)
        expired = [key for key, value in self._sessions.items() if value["expires"] <= now]
        for key in expired:
            self._sessions.pop(key, None)

    def create(self, username: str) -> tuple[str, dict[str, Any]]:
        self._cleanup()
        token = secrets.token_urlsafe(32)
        session = {
            "username": username,
            "csrf": secrets.token_urlsafe(24),
            "created": datetime.now(timezone.utc),
            "expires": datetime.now(timezone.utc) + self.ttl,
        }
        self._sessions[token] = session
        return token, session

    def get(self, token: str | None) -> dict[str, Any] | None:
        if not token:
            return None
        self._cleanup()
        session = self._sessions.get(token)
        if session and session["expires"] > datetime.now(timezone.utc):
            return session
        return None

    def destroy(self, token: str | None) -> None:
        if token:
            self._sessions.pop(token, None)


sessions = SessionStore(config.SESSION_TTL_MINUTES)


class RateLimiter:
    """Ventana deslizante en memoria; suficiente para un despliegue por instancia."""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str, limit: int, window_seconds: int) -> bool:
        now = time.monotonic()
        bucket = self._hits[key]
        while bucket and bucket[0] <= now - window_seconds:
            bucket.popleft()
        if len(bucket) >= limit:
            return False
        bucket.append(now)
        return True

    def retry_after(self, key: str, window_seconds: int) -> int:
        bucket = self._hits.get(key)
        if not bucket:
            return window_seconds
        return max(1, int(window_seconds - (time.monotonic() - bucket[0])))


limiter = RateLimiter()


def client_ip(request: Request) -> str:
    if config.TRUST_PROXY:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def require_admin(request: Request) -> dict[str, Any]:
    session = sessions.get(request.cookies.get(SESSION_COOKIE))
    if not session:
        raise HTTPException(status_code=401, detail="Sesión requerida")
    return session


def require_csrf(
    request: Request, session: dict[str, Any] = Depends(require_admin)
) -> dict[str, Any]:
    token = request.headers.get(CSRF_HEADER, "")
    if not token or not hmac.compare_digest(token, session["csrf"]):
        raise HTTPException(status_code=403, detail="Token CSRF inválido")

    origin = request.headers.get("origin")
    if origin:
        expected = f"{request.url.scheme}://{request.url.netloc}"
        # Detrás de proxy, request.url puede ser http; aceptar el host reenviado.
        forwarded_proto = request.headers.get("x-forwarded-proto", request.url.scheme)
        allowed = {expected, f"{forwarded_proto}://{request.headers.get('host', request.url.netloc)}"}
        if origin not in allowed:
            raise HTTPException(status_code=403, detail="Origen no permitido")
    return session


def set_session_cookie(response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        secure=config.COOKIE_SECURE,
        samesite="strict",
        max_age=int(config.SESSION_TTL_MINUTES * 60),
        path="/",
    )


def clear_session_cookie(response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/", samesite="strict", secure=config.COOKIE_SECURE)


# --------------------------------------------------------------------------- #
# Auditoría
# --------------------------------------------------------------------------- #
def audit(event: str, username: str = "", detail: str = "") -> None:
    record = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "event": event,
        "user": username,
        "detail": detail[:300],
    }
    try:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        with AUDIT_FILE.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass  # La auditoría no debe romper la petición; monitorizar en producción.


# --------------------------------------------------------------------------- #
# Validación de entradas públicas
# --------------------------------------------------------------------------- #
CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def clean_text(value: Any, max_length: int = 500) -> str:
    if not isinstance(value, str):
        return ""
    text = CONTROL_CHARS.sub("", value).strip()
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text[:max_length]


EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]{2,}$")


def valid_email(value: str) -> bool:
    return bool(value and len(value) <= 254 and EMAIL_RE.match(value))
