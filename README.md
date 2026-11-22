# Puerto A&M | Plataforma segura (landing + inteligencia financiera)

Repositorio: https://github.com/sdeciga77-eng/puerto-am-intelligence

Aplicación **funcional** con frontend y backend en una sola origen:

| Experiencia | Ruta | Acceso |
|---|---|---|
| Landing pública premium | `/` | público |
| Asistente de atención (OpenRouter / n8n + fallback local) | widget en `/` | público, sin finanzas |
| Formulario de contacto | `/api/public/contact` | público, con rate limit y honeypot |
| Acceso al panel | `/admin/login` | credenciales |
| Dashboard ejecutivo + agente financiero | `/admin/dashboard` | sesión HttpOnly + CSRF |
| Automatizaciones (reportes, Gmail, Drive, CFDI, National Soft) | `/api/admin/actions` | sesión + CSRF + confirmación |

> **Aviso de datos:** el Excel incluido es una **simulación académica** (Top Learning). Los importes son ficticios y se calculan en tiempo real desde `data/Puerto_AM_Base_Datos_DEMO.xlsx`. No se inventan resultados: si un dato no está en la fuente o su integración no está configurada, la respuesta lo indica.

---

## Qué quedó implementado

### Público
- Landing corporativa minimalista (blanco/azul profundo/acento dorado), animaciones con `IntersectionObserver`, marquee, tarjetas, timeline y formulario funcional.
- Chat widget con **guardrail financiero**: cualquier mención de facturas, ventas, gastos, bancos, tokens o admin se bloquea antes de llamar a n8n o a OpenRouter y se responde con un mensaje seguro.
- Con `OPENROUTER_API_KEY` configurada, el modelo gratuito responde preguntas públicas usando **solo datos públicos**; la respuesta se vuelve a sanear antes de mostrarse. Si el modelo falla o se agota la cuota, se usa la base de conocimiento local y se dice explícitamente.
- Si el webhook público no está configurado o falla, se usa una base de conocimiento **solo pública** y se dice explícitamente que está en modo local.
- Los datos de contacto (correo, horario, dirección) se inyectan desde variables de entorno; si no existen, se pide usar el formulario en vez de inventarlos.

### Panel privado
- Login con hash **PBKDF2-SHA256 (310k iteraciones)**, comparación en tiempo constante, rate limit, cookies `HttpOnly + SameSite=Strict` (y `Secure` cuando aplica), CSRF en cada POST, auditoría en `data/audit.log`, CSP estricto y sin `docs` públicos.
- Las páginas HTML privadas viven en `private/` (fuera del estático) para no poder evadir la autenticación.
- Dashboard con 8 KPI, 5 gráficas Chart.js (vendor local), tabla filtrable/ordenable/pagada, exportación CSV/XLSX/JSON, metas y detección de anomalías con reglas explícitas.
- Agente financiero tipo ChatGPT que responde en lenguaje natural con cifras calculadas del Excel. Adjunta siempre **hechos verificados**, periodo y fuente. OpenRouter solo **redacta** sobre cifras ya calculadas y valida que no aparezcan números nuevos; los temas pendientes (CFDI, bancos, caja) nunca se envían al modelo. Si n8n responde, tiene prioridad.
- Estado de integraciones en tiempo real y botones de automatización que, sin webhook, devuelven `pendiente` (nunca simulan un envío).

---

## Ejecutar

### Windows (más fácil)
Doble clic en **`ejecutar.bat`**. Si no existe credencial configurada, la consola imprime **una sola vez** una contraseña aleatoria de primer ingreso.

### Manual
```powershell
$PY = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
cd puerto_am_bi
& $PY -m pip install -r requirements.txt
& $PY -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Abre `http://127.0.0.1:8000/` y `http://127.0.0.1:8000/admin`.

### Cambiar la contraseña (recomendado)
```powershell
& $PY scripts\set_admin_password.py
# pega ADMIN_PASSWORD_HASH=... en .env y reinicia
```

---

## Configuración

Copia `.env.example` como `.env`. Variables principales:

| Variable | Uso |
|---|---|
| `ADMIN_USER`, `ADMIN_PASSWORD_HASH` | Credencial del panel. `ADMIN_PASSWORD` solo para desarrollo. |
| `SESSION_TTL_MINUTES`, `COOKIE_SECURE`, `TRUST_PROXY` | Sesión y cookies (activar `Secure` detrás de HTTPS). |
| `N8N_PUBLIC_WEBHOOK_URL` | Chat de atención. Debe responder texto plano o JSON con `answer`. |
| `N8N_FINANCE_WEBHOOK_URL` | Agente financiero. Recibe la pregunta + `verifiedFacts`. |
| `N8N_ACTIONS_WEBHOOK_URL` | Reportes, Gmail, Drive, CFDI, National Soft. |
| `N8N_CONTACT_WEBHOOK_URL` | Recepción del formulario de contacto. |
| `N8N_WEBHOOK_TOKEN` | Token enviado como `X-Webhook-Token`. |
| `OPENROUTER_API_KEY` | Llave de OpenRouter. **Solo backend**; nunca se envía al navegador. |
| `OPENROUTER_MODEL` | Modelo gratuito principal (probado: `google/gemma-4-26b-a4b-it:free`). |
| `OPENROUTER_FALLBACK_MODELS` | Cadena de respaldo si el proveedor devuelve 429/503. |
| `OPENROUTER_TIMEOUT_SECONDS`, `OPENROUTER_MAX_TOKENS` | Timeout y límite de salida. |
| `PUBLIC_EMAIL`, `PUBLIC_PHONE`, `PUBLIC_ADDRESS`, `PUBLIC_HOURS` | Datos públicos del restaurante. |

### Modelo gratuito de OpenRouter (demo)

La llave de prueba está en `.env` (archivo ignorado por Git). El plan gratuito de esa llave permite **50 peticiones/día** y vence el **29 nov 2026**; para producción usa tu propia llave y rota esta, ya que apareció en la conversación.

- **Modelo principal:** `google/gemma-4-26b-a4b-it:free` (respuestas correctas en español, ~1–2 s).
- **Fallbacks:** `openrouter/free`, `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free`, `baidu/ernie-5.5-flash-preview:free`.
- **Ahorro de cuota:** cache en memoria por pregunta (1 h en chat público, 15 min en el agente) y cadena de respaldo automática ante 429. Las preguntas repetidas **no consumen** peticiones.
- **Seguridad:** el guardrail financiero corre antes del modelo; la respuesta pública se sanea después; la respuesta financiera se rechaza si introduce cifras no verificadas.
- Si la cuota se agota, la app sigue funcionando con el motor local determinista y lo indica; nunca inventa respuestas.

Para diagnosticar la llave y los modelos:
```powershell
& $PY scripts\probar_openrouter.py list
& $PY scripts\probar_openrouter.py key
& $PY scripts\probar_openrouter.py integracion
& $PY scripts\probar_openrouter.py api
```

Para ver el estado real sin iniciar el servidor:
```powershell
& $PY scripts\check_integrations.py
```

---

## Contratos de los workflows n8n

Todos los webhooks son `POST JSON` con timeout de 8 s (configurable) y cabecera `X-Webhook-Token` si se define el token.

**Chat público** (`source: "public_website"`):
```json
{ "source": "public_website", "message": "¿Cómo reservo?", "sessionId": "...", "timestamp": "...", "policy": "..." }
```
Respuesta aceptada: texto plano o `{"answer": "..."}`. El servidor **descarta** respuestas con cifras, enlaces, correos o vocabulario financiero.

**Agente financiero** (`source: "admin_finance_agent"`):
```json
{ "source": "admin_finance_agent", "question": "¿Cómo van las ventas?", "context": { "ventas": 1234.5, "costos": 500, "periodo": "Mar 2026", "...": "..." }, "rules": ["Usa solo verifiedFacts", "..."] }
```
El prompt del workflow debe prohibir importes fuera del contexto. El panel muestra las cifras verificadas calculadas localmente al lado de la respuesta.

**Acciones** (`source: "admin_panel"`):
```json
{ "source": "admin_panel", "action": "email_report", "requestedBy": "admin", "confirm": true, "payload": {} }
```
Acciones permitidas: `generate_report`, `email_report`, `drive_backup`, `sync_national_soft`, `request_cfdi_report`. La respuesta se muestra tal cual; **no se afirma éxito** si n8n no responde.

---

## Integraciones pendientes (no simuladas)

Con la llave de OpenRouter cargada hay **2/11 canales conectados** (Excel + OpenRouter). Sin variables `N8N_*`, estas conexiones quedan marcadas como **PENDIENTE** en el panel y en `scripts/check_integrations.py`:

1. Workflow n8n de atención pública (chat).
2. Workflow n8n del agente financiero (con prompts y permisos).
3. Workflow n8n de acciones (Gmail OAuth, Google Drive OAuth, proveedor CFDI, National Soft, conector bancario).
4. Datos reales de contacto del restaurante (`PUBLIC_*`).
5. Para producción multi-instancia: reemplazar el store de sesiones y rate limiter en memoria por Redis/DB, y configurar HTTPS con `COOKIE_SECURE=true` + `TRUST_PROXY=true`.

La base Excel solo contiene **Ventas, Productos y Metas**. Por eso las consultas sobre CFDI, bancos, pagos pendientes, proveedores, caja y National Soft se responden como integración pendiente, sin fabricar datos.

---

## Estructura

```
puerto_am_bi/
├─ backend/
│  ├─ main.py          # rutas públicas, auth, admin, exportación
│  ├─ config.py        # entorno y estado de integraciones
│  ├─ security.py      # hash, sesiones, CSRF, rate limit, auditoría
│  ├─ n8n.py           # adaptadores de webhooks y saneamiento
│  ├─ openrouter.py    # modelo gratuito: cache, fallback y validación
│  ├─ public_kb.py     # conocimiento público (sin finanzas)
│  ├─ agent.py         # motor financiero determinista + anomalías
│  └─ repository.py    # lectura del Excel (reutilizado del BI original)
├─ frontend/
│  ├─ index.html, styles.css, app.js       # landing pública
│  ├─ admin/admin.css, admin/admin.js      # assets del panel
│  └─ vendor/chart.umd.min.js              # Chart.js local
├─ private/            # HTML del panel (fuera del estático)
├─ data/               # Excel + secret hash + auditoría + contactos (gitignored)
├─ scripts/            # generador Excel, validación, password, integraciones y diagnóstico OpenRouter
└─ .env.example
```

## Validación

Con el servidor corriendo y `ADMIN_PASSWORD` definido:
```powershell
$env:ADMIN_PASSWORD="la_misma_contraseña"
& $PY scripts\validar.py
```
Verifica Excel, auth, CSRF, guardrail público, cálculos, filtros, agente, acciones pendientes, exportación y el ciclo editar → actualizar → restaurar.
