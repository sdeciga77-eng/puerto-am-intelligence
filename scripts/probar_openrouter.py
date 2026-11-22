"""Diagnóstico de OpenRouter para la demo de Puerto A&M.

Uso:
    python scripts/probar_openrouter.py list
    python scripts/probar_openrouter.py test [modelo ...]

La llave se lee SOLO de .env / variables de entorno y nunca se imprime.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import agent, config, openrouter  # noqa: E402

BASE = "https://openrouter.ai/api/v1"
HEADERS = {
    "Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
    "Content-Type": "application/json; charset=utf-8",
    "HTTP-Referer": "http://localhost:8000",
    "X-Title": "Puerto A&M Demo",
}


def _request(path: str, payload: dict | None = None) -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(BASE + path, data=data, headers=HEADERS, method="POST" if data else "GET")
    with urllib.request.urlopen(request, timeout=config.OPENROUTER_TIMEOUT_SECONDS) as response:
        return json.loads(response.read(1_000_000).decode("utf-8"))


def listar() -> None:
    result = _request("/models")
    models = result.get("data", [])
    free = [m for m in models if m["id"].endswith(":free") or (
        m.get("pricing", {}).get("prompt") in ("0", "0.0")
        and m.get("pricing", {}).get("completion") in ("0", "0.0")
    )]
    free.sort(key=lambda m: (-(m.get("context_length") or 0), m["id"]))
    print(f"Modelos totales: {len(models)} | gratuitos: {len(free)}\n")
    print(f"{'ID':<52} {'CTX':>8} {'MAX OUT':>8}  NOMBRE")
    for m in free:
        provider = m.get("top_provider") or {}
        print(
            f"{m['id']:<52} {m.get('context_length') or 0:>8} "
            f"{provider.get('max_completion_tokens') or 0:>8}  {m.get('name', '')[:48]}"
        )


def clave() -> None:
    info = _request("/key")
    data = info.get("data", info)
    print(json.dumps(data, indent=2, ensure_ascii=False)[:3000])


def probar(modelos: list[str]) -> None:
    prompt = "Responde en una frase corta en español: ¿ qué es una reserva de mesa?"
    for model in modelos:
        started = time.monotonic()
        print(f"\n--- {model} ---")
        try:
            result = _request("/chat/completions", {
                "model": model,
                "messages": [
                    {"role": "system", "content": "Eres un asistente conciso. Responde siempre en español."},
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": 120,
                "temperature": 0.2,
            })
            choice = (result.get("choices") or [{}])[0]
            message = choice.get("message") or {}
            answer = (message.get("content") or "").strip()
            usage = result.get("usage") or {}
            print(f"OK {time.monotonic() - started:.1f}s | finish={choice.get('finish_reason')} | "
                  f"tokens={usage.get('total_tokens', '?')} | id={result.get('id', '?')}")
            print(f"Respuesta: {answer[:400] or '(sin content) ' + json.dumps(message, ensure_ascii=False)[:300]}")
        except urllib.error.HTTPError as exc:
            detail = exc.read(600).decode("utf-8", errors="replace")
            print(f"HTTP {exc.code}: {detail[:400]}")
        except Exception as exc:  # pragma: no cover
            print(f"ERROR {type(exc).__name__}: {exc}"[:400])


def integracion() -> None:
    """Prueba los dos caminos reales de la aplicación."""
    print(f"Modelo principal: {config.OPENROUTER_MODEL}")
    print(f"Fallbacks: {', '.join(config.OPENROUTER_FALLBACK_MODELS) or '(ninguno)'}\n")

    print("--- Chat público ---")
    estado, texto, detalle = openrouter.answer_public("¿Cómo hago una reserva?", config.PUBLIC_CONFIG)
    print(f"{estado} | {detalle}\n{texto[:500]}\n")

    print("--- Guardrail público (no debe llegar al modelo) ---")
    from backend import public_kb
    print(public_kb.answer("¿Cuánto gastamos este mes?")[:300], "\n")

    print("--- Agente financiero (redacción sobre hechos verificados) ---")
    local = agent.local_answer("¿Cómo van las ventas?")
    estado, texto, detalle, modelo = openrouter.rewrite_finance_answer(
        "¿Cómo van las ventas?", local["answer"], local["verifiedFacts"]
    )
    print(f"{estado} | modelo={modelo} | {detalle}")
    print(texto[:700] or local["answer"][:700])


def verificar_api() -> None:
    """Comprueba los modos que devuelve la API con la llave cargada."""
    import http.cookiejar
    import urllib.parse

    base = "http://127.0.0.1:8000"
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

    def post(path: str, payload: dict, csrf: str | None = None) -> dict:
        headers = {"Content-Type": "application/json"}
        if csrf:
            headers["X-CSRF-Token"] = csrf
        req = urllib.request.Request(
            base + path,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with opener.open(req, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))

    public = post("/api/public/chat", {"message": "¿Cómo hago una reserva?", "sessionId": "demo"})
    print(f"PÚBLICO  mode={public.get('mode')} | {public.get('answer', '')[:220]}")

    post("/api/auth/login", {"username": config.ADMIN_USER, "password": config.ADMIN_PASSWORD or ""})
    with opener.open(base + "/api/auth/me", timeout=10) as response:
        me = json.loads(response.read().decode("utf-8"))
    for question in ("¿Cómo van las ventas?", "¿Qué facturas faltan?"):
        result = post("/api/admin/agent", {"message": question}, me["csrfToken"])
        print(f"ADMIN    mode={result.get('mode')} | intent={result.get('intent')}")
        print(f"         {result.get('answer', '')[:260]}")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "list"
    if mode == "list":
        listar()
    elif mode == "key":
        clave()
    elif mode == "integracion":
        integracion()
    elif mode == "api":
        verificar_api()
    elif mode == "test":
        modelos = sys.argv[2:] or [
            "meta-llama/llama-3.3-70b-instruct:free",
            "google/gemma-3-27b-it:free",
            "qwen/qwen3-235b-a22b:free",
        ]
        probar(modelos)
    else:
        raise SystemExit("Uso: probar_openrouter.py list | test [modelo ...]")
