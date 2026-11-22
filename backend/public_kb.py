"""Base de conocimiento pública: solo información no financiera y verificable.

Si un dato de contacto no fue configurado, se dice explícitamente en lugar de
inventarlo. Ninguna respuesta de aquí menciona indicadores financieros.
"""

from __future__ import annotations

import re
import unicodedata

from . import config

FALLBACK = (
    "Puedo ayudarte con reservas, horarios, servicios, ubicación y formas de contacto "
    "de Puerto A&M. Cuéntame qué necesitas y, si prefieres, usa el formulario de "
    "contacto de esta página."
)
BLOCKED = (
    "Para consultas administrativas, financieras o de facturación, comunícate con el "
    "equipo autorizado mediante los canales internos. Yo solo puedo ayudarte con "
    "reservas, horarios, servicios y contacto."
)

_PATTERNS = [
    (
        (r"horario|abier|abren|cierran|cerrado|hora|atencion|atención",),
        lambda: (
            f"Horario: {config.PUBLIC_CONFIG['hours']}."
            if config.PUBLIC_CONFIG["hours"]
            else "Todavía no tenemos un horario publicado en este canal. Envíanos un mensaje "
            "por el formulario de contacto y te lo confirmamos sin compromiso."
        ),
    ),
    (
        (r"reserv|mesa|agendar|cita|disponibilidad",),
        lambda: (
            "Para reservar, envíanos los datos del formulario de contacto (fecha, hora y "
            "número de personas). "
            + (
                f"También puedes escribirnos a {config.PUBLIC_CONFIG['email']}."
                if config.PUBLIC_CONFIG["email"]
                else "Nos pondremos en contacto contigo para confirmar."
            )
        ),
    ),
    (
        (r"evento|privad|banquete|reunion|reunión|corporativ|conferencia|catering",),
        lambda: (
            "Ofrecemos experiencias para eventos privados y reuniones corporativas. "
            "Cuéntanos el tipo de evento, número de invitados y fecha aproximada en el "
            "formulario de contacto para preparar una propuesta a tu medida."
        ),
    ),
    (
        (r"ubic|direccion|dirección|donde|dónde|como llegar|cómo llegar|estacionam|mapa",),
        lambda: (
            f"Ubicación: {config.PUBLIC_CONFIG['address']}."
            if config.PUBLIC_CONFIG["address"]
            else "Aún no publicamos la dirección en este canal. Solicítala con el formulario "
            "de contacto y te la compartiremos."
        ),
    ),
    (
        (r"contacto|correo|email|telefono|teléfono|llamar|whatsapp|instagram|redes",),
        lambda: _contact_answer(),
    ),
    (
        (r"carta|menu|menú|plato|comida|gastronom|especialidad|postre|bebida",),
        lambda: (
            "Nuestra propuesta gastronómica se concentra en cocina de temporada, productos "
            "frescos y presentación cuidada. Para conocer la carta vigente y opciones "
            "dietéticas, solicítala por el formulario de contacto; así te enviamos la "
            "versión más reciente."
        ),
    ),
    (
        (r"alerg|vegan|vegetariano|gluten|dietet|dietético|sin lactosa",),
        lambda: (
            "Podemos ayudarte con opciones vegetarianas, veganas y sin gluten. Indica tus "
            "restricciones al hacer tu reserva o en el formulario de contacto para que el "
            "equipo revise la carta vigente contigo."
        ),
    ),
    (
        (r"precio|coste|costo|tarifa|presupuesto|cuenta",),
        lambda: (
            "Para conocer precios y presupuestos, envíanos tu consulta por el formulario de "
            "contacto. Preferimos darte información vigente y personalizada en lugar de un "
            "importe que pueda estar desactualizado."
        ),
    ),
    (
        (r"gracias|perfecto|genial|ey|hola|buenas|saludos|ayuda|help",),
        lambda: FALLBACK,
    ),
]

_FINANCIAL_HINT = re.compile(
    r"(?i)(factura|cfdi|sat\b|venta|ventas|gasto|gastos|gastam|gastar|gasté|gaste|egreso|egresos|banco|saldo|"
    r"utilidad|margen|proveedor|caja|nomina|nómina|pago|pagos|financier|reporte|"
    r"admin|contraseña|password|token|webhook|n8n|excel|dato|sistema)"
)


def _contact_answer() -> str:
    parts = ["Puedes contactarnos mediante el formulario de esta página."]
    cfg = config.PUBLIC_CONFIG
    if cfg["email"]:
        parts.append(f"Correo: {cfg['email']}.")
    if cfg["phone"]:
        parts.append(f"Teléfono: {cfg['phone']}.")
    if cfg["whatsapp"]:
        parts.append("También tenemos canal de WhatsApp (enlace en el pie de página).")
    if len(parts) == 1:
        parts.append("Aún no publicamos otros canales en este sitio; te responderemos por ahí.")
    return " ".join(parts)


def _normalize(text: str) -> str:
    value = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in value if not unicodedata.combining(ch))


def answer(message: str) -> str:
    normalized = _normalize(message)
    if _FINANCIAL_HINT.search(normalized):
        return BLOCKED
    for patterns, response in _PATTERNS:
        if any(re.search(pattern, normalized) for pattern in patterns):
            return response()
    return FALLBACK


SUGGESTIONS = [
    "¿Cuál es el horario de atención?",
    "¿Cómo hago una reserva?",
    "¿Ofrecen eventos privados?",
    "¿Cómo puedo contactarlos?",
]
