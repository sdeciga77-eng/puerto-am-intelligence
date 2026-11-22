"""Agente financiero local, determinista y sin inventar resultados.

Las cifras se calculan siempre desde el Excel real (repository.py). Si n8n está
configurado, su respuesta se presenta junto a los hechos verificados; si no,
se responde con el motor local y se indica la integración pendiente cuando el
dato solicitado no existe en la fuente conectada.
"""

from __future__ import annotations

import re
import statistics
import unicodedata
from collections import defaultdict
from typing import Any

from . import config, n8n, openrouter
from .repository import DISCLAIMER, EXCEL_PATH, month_key, month_label, read_workbook

MONEY = lambda value: f"${float(value or 0):,.2f} MXN"
PCT = lambda value: f"{float(value or 0):.1f}%"

_INTENTES_REESCRIBIBLES = {
    "gastos", "ventas", "utilidad", "pedidos", "metas", "explicacion", "productos_top"
}

PENDING_MESSAGE = (
    "Ese indicador no está disponible en la fuente conectada. La base actual solo contiene "
    "ventas, productos y metas; no incluye CFDI, bancos, pagos pendientes, proveedores ni "
    "movimientos de caja/National Soft. La integración correspondiente está PENDIENTE de "
    "configurarse en n8n. No he inventado ningún resultado."
)


def _normalize(text: str) -> str:
    value = unicodedata.normalize("NFKD", str(text).lower())
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", value).strip()


def _totals(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ingresos = sum(r["ingreso"] for r in rows)
    costos = sum(r["costoTotal"] for r in rows)
    utilidad = ingresos - costos
    pedidos = len({r["pedido"] for r in rows})
    return {
        "ingresos": round(ingresos, 2),
        "costos": round(costos, 2),
        "utilidad": round(utilidad, 2),
        "margen": round(utilidad / ingresos * 100, 2) if ingresos else 0.0,
        "pedidos": pedidos,
        "unidades": int(sum(r["cantidad"] for r in rows)),
        "ticket": round(ingresos / pedidos, 2) if pedidos else 0.0,
    }


def _top_products(rows: list[dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
    totals: dict[str, dict[str, float]] = defaultdict(lambda: {"ingreso": 0.0, "unidades": 0.0})
    for row in rows:
        totals[row["producto"]]["ingreso"] += row["ingreso"]
        totals[row["producto"]]["unidades"] += row["cantidad"]
    result = [
        {
            "producto": name,
            "ingreso": round(values["ingreso"], 2),
            "unidades": int(values["unidades"]),
        }
        for name, values in totals.items()
    ]
    return sorted(result, key=lambda item: -item["ingreso"])[:limit]


def snapshot() -> dict[str, Any]:
    """Estado real del Excel, calculado en cada petición (sin caché)."""
    data = read_workbook()
    sales = data["sales"]
    months = sorted({month_key(row["fecha"]) for row in sales})
    current = months[-1]
    previous = months[-2] if len(months) > 1 else None
    current_rows = [row for row in sales if month_key(row["fecha"]) == current]
    previous_rows = [row for row in sales if month_key(row["fecha"]) == previous] if previous else []
    current_totals = _totals(current_rows)
    previous_totals = _totals(previous_rows)
    growth = None
    if previous_totals["ingresos"]:
        growth = round(
            (current_totals["ingresos"] - previous_totals["ingresos"])
            / previous_totals["ingresos"]
            * 100,
            2,
        )
    goal = next((g for g in data["goals"] if g["mes"] == current), None)
    goal_compliance = None
    if goal and goal["metaVentas"]:
        goal_compliance = round(current_totals["ingresos"] / goal["metaVentas"] * 100, 2)

    return {
        "archivo": EXCEL_PATH.name,
        "periodo": current,
        "periodoEtiqueta": month_label(current),
        "periodoAnterior": previous,
        "periodoAnteriorEtiqueta": month_label(previous) if previous else None,
        "totales": current_totals,
        "anteriores": previous_totals,
        "crecimiento": growth,
        "productos": _top_products(current_rows),
        "meta": goal,
        "cumplimientoMeta": goal_compliance,
        "registros": len(sales),
        "mesesDisponibles": [month_label(month) for month in months],
        "alertas": compute_anomalies(),
    }


def compute_anomalies() -> list[dict[str, Any]]:
    """Reglas explícitas y auditables sobre la fuente conectada."""
    data = read_workbook()
    sales = data["sales"]
    months = sorted({month_key(row["fecha"]) for row in sales})
    anomalies: list[dict[str, Any]] = []

    monthly = [(month, _totals([row for row in sales if month_key(row["fecha"]) == month])) for month in months]
    for index in range(1, len(monthly)):
        month, values = monthly[index]
        prev_values = monthly[index - 1][1]
        if prev_values["ingresos"] and values["ingresos"] < prev_values["ingresos"] * 0.85:
            anomalies.append(
                {
                    "severidad": "media",
                    "titulo": f"Caída de ventas en {month_label(month)}",
                    "detalle": (
                        f"Las ventas bajaron {PCT(abs(round((values['ingresos'] / prev_values['ingresos'] - 1) * 100, 2)))} "
                        f"frente a {month_label(months[index - 1])}."
                    ),
                }
            )
        if values["margen"] < prev_values["margen"] - 5:
            anomalies.append(
                {
                    "severidad": "media",
                    "titulo": f"Margen a la baja en {month_label(month)}",
                    "detalle": (
                        f"Margen bruto {PCT(values['margen'])} vs. {PCT(prev_values['margen'])} "
                        f"en {month_label(months[index - 1])}."
                    ),
                }
            )

    current = months[-1]
    daily: dict[str, float] = defaultdict(float)
    for row in sales:
        if month_key(row["fecha"]) == current:
            daily[row["fecha"].isoformat()] += row["ingreso"]
    if len(daily) >= 5:
        values = list(daily.values())
        mean = statistics.mean(values)
        deviation = statistics.pstdev(values)
        if deviation > 0:
            outliers = sorted(
                ((day, value) for day, value in daily.items() if abs(value - mean) > 2 * deviation),
                key=lambda item: -abs(item[1] - mean),
            )[:3]
            for day, value in outliers:
                direction = "por encima" if value > mean else "por debajo"
                anomalies.append(
                    {
                        "severidad": "baja",
                        "titulo": f"Día atípico: {day}",
                        "detalle": (
                            f"Venta diaria {MONEY(value)} {direction} del promedio mensual "
                            f"({MONEY(mean)}). Regla: desviación > 2σ."
                        ),
                    }
                )

    negative = [row for row in sales if row["utilidad"] < 0]
    if negative:
        anomalies.append(
            {
                "severidad": "alta",
                "titulo": "Líneas con utilidad negativa",
                "detalle": (
                    f"{len(negative)} registros tienen utilidad negativa en la base; "
                    "revisar precios y costos unitarios."
                ),
            }
        )
    return anomalies


def _facts(snap: dict[str, Any]) -> dict[str, Any]:
    return {
        "fuente": snap["archivo"],
        "periodo": snap["periodoEtiqueta"],
        "ventas": snap["totales"]["ingresos"],
        "costos": snap["totales"]["costos"],
        "utilidadBruta": snap["totales"]["utilidad"],
        "margenBruto": snap["totales"]["margen"],
        "pedidos": snap["totales"]["pedidos"],
        "ticketPromedio": snap["totales"]["ticket"],
        "unidades": snap["totales"]["unidades"],
        "crecimientoMensual": snap["crecimiento"],
        "cumplimientoMeta": snap["cumplimientoMeta"],
        "productosTop": snap["productos"],
        "mesesDisponibles": snap["mesesDisponibles"],
    }


def _result(answer: str, intent: str, snap: dict[str, Any], follow_ups: list[str] | None = None) -> dict[str, Any]:
    return {
        "answer": answer,
        "intent": intent,
        "mode": "local",
        "periodo": snap["periodoEtiqueta"],
        "verifiedFacts": _facts(snap),
        "sources": [f"Excel: {snap['archivo']}", DISCLAIMER],
        "followUps": follow_ups
        or [
            "¿Cómo van las ventas?",
            "¿Cuánto gastamos este mes?",
            "¿Hay anomalías?",
        ],
    }


def local_answer(question: str, snap: dict[str, Any] | None = None) -> dict[str, Any]:
    snap = snap or snapshot()
    text = _normalize(question)
    t = snap["totales"]

    if re.search(r"factur|cfdi|sat|comprobante|facturas faltan", text):
        return _result(PENDING_MESSAGE, "facturacion_pendiente", snap)

    if re.search(r"banco|saldo|transferencia|proveedor|pagos pendientes|caja|efectivo|national soft|nomina|nómina", text):
        return _result(PENDING_MESSAGE, "integracion_pendiente", snap)

    if re.search(r"gasto|egreso|costo|gastamos", text):
        answer = (
            f"En {snap['periodoEtiqueta']}, el único egreso registrado en la fuente conectada es el "
            f"costo de ventas: {MONEY(t['costos'])}. Se calcula desde cantidad × costo unitario "
            f"de {snap['registros']:,} líneas en total.\n\n"
            "La base no incluye gastos operativos, nómina ni egresos bancarios. Para un estado "
            "de gastos completo hay que conectar el workflow correspondiente en n8n. No he "
            "inventado importes adicionales."
        )
        return _result(answer, "gastos", snap)

    if re.search(r"venta|ingreso|facturacion|facturación|como va|como van", text):
        growth = snap["crecimiento"]
        growth_text = f"{PCT(growth)} frente a {snap['periodoAnteriorEtiqueta']}." if growth is not None else "Sin mes anterior comparable."
        answer = (
            f"Ventas en {snap['periodoEtiqueta']}: {MONEY(t['ingresos'])} en {t['pedidos']:,} pedidos "
            f"({t['unidades']:,} unidades). Crecimiento mensual: {growth_text}\n"
            f"Ticket promedio: {MONEY(t['ticket'])}. Utilidad bruta: {MONEY(t['utilidad'])} "
            f"con margen de {PCT(t['margen'])}."
        )
        if snap["cumplimientoMeta"] is not None:
            answer += f"\nCumplimiento de la meta de ventas del mes: {PCT(snap['cumplimientoMeta'])}."
        return _result(answer, "ventas", snap)

    if re.search(r"utilidad|ganancia|margen|rentab", text):
        answer = (
            f"En {snap['periodoEtiqueta']}: utilidad bruta {MONEY(t['utilidad'])} y margen bruto "
            f"{PCT(t['margen'])} (utilidad ÷ ventas). Ventas {MONEY(t['ingresos'])} menos costo "
            f"de ventas {MONEY(t['costos'])}.\n\n"
            "Es margen BRUTO: no incluye gastos operativos, impuestos ni egresos bancarios."
        )
        return _result(answer, "utilidad", snap)

    if re.search(r"top|mas vendido|más vendido|producto destacado|mejor vendido|ranking", text):
        lines = [f"• {item['producto']}: {MONEY(item['ingreso'])} · {item['unidades']:,} uds." for item in snap["productos"]]
        return _result(
            f"Productos con mayores ingresos en {snap['periodoEtiqueta']}:\n" + "\n".join(lines),
            "productos_top",
            snap,
        )

    if re.search(r"pedido|ticket|orden|unidad", text):
        return _result(
            f"En {snap['periodoEtiqueta']}: {t['pedidos']:,} pedidos únicos, {t['unidades']:,} "
            f"unidades y ticket promedio de {MONEY(t['ticket'])}. El ticket se calcula como "
            "ventas del periodo entre pedidos únicos.",
            "pedidos",
            snap,
        )

    if re.search(r"meta|objetivo|cumplimiento", text):
        goal = snap["meta"]
        if not goal:
            return _result(f"No hay meta cargada para {snap['periodoEtiqueta']} en la hoja Metas.", "metas", snap)
        return _result(
            f"Meta de ventas de {snap['periodoEtiqueta']}: {MONEY(goal['metaVentas'])}. "
            f"Resultado: {MONEY(t['ingresos'])}. Cumplimiento: {PCT(snap['cumplimientoMeta'])}. "
            f"Meta de pedidos: {goal['metaPedidos']:,} vs. {t['pedidos']:,} reales.",
            "metas",
            snap,
        )

    if re.search(r"anomal|irregular|raro|alerta|desvi|outlier", text):
        alerts = snap["alertas"]
        if not alerts:
            return _result(
                "No se detectaron anomalías con las reglas actuales en el rango analizado "
                "(caída mensual >15%, margen −5pp, días con desviación >2σ y utilidad negativa).",
                "anomalias",
                snap,
            )
        lines = [f"• {item['titulo']}: {item['detalle']}" for item in alerts[:6]]
        return _result("Anomalías detectadas en la base conectada:\n" + "\n".join(lines), "anomalias", snap)

    if re.search(r"que es|qué es|explica|definicion|definición|significa", text):
        if re.search(r"margen", text):
            return _result(
                "Margen bruto = (ventas − costo de ventas) ÷ ventas × 100. Mide qué parte de "
                f"cada peso facturado queda después del costo directo. Valor actual: {PCT(t['margen'])}.",
                "explicacion",
                snap,
            )
        if re.search(r"ticket", text):
            return _result(
                "Ticket promedio = ventas del periodo ÷ pedidos únicos. "
                f"Valor actual: {MONEY(t['ticket'])}.",
                "explicacion",
                snap,
            )
        if re.search(r"utilidad", text):
            return _result(
                "Utilidad bruta = ventas − costo de ventas. "
                f"Valor actual: {MONEY(t['utilidad'])}. No incluye gastos operativos.",
                "explicacion",
                snap,
            )
        return _result(
            "Puedo explicarte ventas totales, costos, utilidad bruta, margen bruto, ticket "
            "promedio, pedidos, metas y crecimiento mensual. ¿Cuál te interesa?",
            "explicacion",
            snap,
        )

    if re.search(r"ayuda|que puedes|qué puedes|como funciona|cómo funciona|hola", text):
        return _result(
            "Puedo responder con cifras calculadas del Excel: ventas, costos, utilidad, margen, "
            "pedidos, ticket, productos top, metas y anomalías. También te indico qué datos "
            "requieren integración (CFDI, bancos, caja, National Soft). Ejemplos: «¿Cómo van "
            "las ventas?», «¿Cuánto gastamos este mes?», «¿Hay anomalías?».",
            "ayuda",
            snap,
        )

    return _result(
        "No encontré ese indicador en la fuente conectada. Trabajo con ventas, costos, utilidad, "
        "margen, pedidos, ticket, productos, metas y anomalías del Excel. Para CFDI, bancos o "
        "National Soft necesito la integración n8n; no invento resultados.",
        "sin_coincidencia",
        snap,
    )


def answer_question(question: str) -> dict[str, Any]:
    """Responde usando n8n si está disponible; siempre adjunta hechos verificados."""
    snap = snapshot()
    local = local_answer(question, snap)
    facts = local["verifiedFacts"]

    if n8n.is_configured(config.N8N_FINANCE_WEBHOOK_URL):
        status, text, detail = n8n.send_finance_question(question, facts)
        if status == n8n.STATUS_OK and text:
            local["answer"] = text
            local["mode"] = "n8n"
            local["sources"].append("Agente n8n (verificar contra hechos Adjuntos)")
            local["notice"] = "Respuesta del agente conectado. Las cifras verificadas se muestran abajo."
            return local
        local["notice"] = (
            "El agente n8n no respondió; se usó el motor local con datos reales del Excel. "
            f"Detalle técnico: {detail[:80]}."
        )

    # OpenRouter es opcional: solo redacta sobre hechos ya calculados. Los temas
    # pendientes (CFDI, bancos, caja) Jamás se envían al modelo.
    if openrouter.is_configured() and local["intent"] in _INTENTES_REESCRIBIBLES:
        ai_status, ai_text, ai_detail, model = openrouter.rewrite_finance_answer(
            question, local["answer"], facts
        )
        if ai_status == openrouter.STATUS_OK and ai_text:
            local["answer"] = ai_text
            local["mode"] = "openrouter"
            local["sources"].append(f"Redacción IA verificada: {model}")
            local["notice"] = "Redacción asistida por IA; las cifras verificadas se muestran abajo."
        elif ai_status != openrouter.STATUS_PENDING:
            local["notice"] = (
                "El modelo no devolvió una respuesta válida; se usó el motor local con cifras "
                f"verificadas. Detalle: {ai_detail[:60]}."
            )

    return local
