"""Lectura del archivo Excel y cálculo de indicadores de Puerto A&M.

La fuente de verdad es SIEMPRE el archivo .xlsx. No existen datos incrustados.
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[1]
EXCEL_PATH = ROOT / "data" / "Puerto_AM_Base_Datos_DEMO.xlsx"

DISCLAIMER = (
    "SIMULACIÓN ACADÉMICA · Todos los datos son ficticios y se emplean únicamente "
    "para práctica de Top Learning."
)

MONTH_LABELS = {
    1: "Ene",
    2: "Feb",
    3: "Mar",
    4: "Abr",
    5: "May",
    6: "Jun",
    7: "Jul",
    8: "Ago",
    9: "Sep",
    10: "Oct",
    11: "Nov",
    12: "Dic",
}


def normalize_header(value: Any) -> str:
    text = "" if value is None else str(value)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return text


def to_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)):
        return date(1899, 12, 30) + timedelta(days=int(value))
    if isinstance(value, str):
        raw = value.strip()
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
            try:
                return datetime.strptime(raw, fmt).date()
            except ValueError:
                continue
    return None


def to_number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    raw = str(value).strip().replace("$", "").replace(",", "")
    try:
        return float(raw)
    except ValueError:
        return None


def money(value: float) -> float:
    return round(float(value) + 0.0, 2)


def month_key(value: date) -> str:
    return f"{value.year:04d}-{value.month:02d}"


def month_label(key: str) -> str:
    try:
        year, month = key.split("-")
        return f"{MONTH_LABELS[int(month)]} {year[-2:]}"
    except (ValueError, KeyError):
        return key


def parse_yyyy_mm(value: Any) -> str | None:
    raw = "" if value is None else str(value).strip()
    match = re.match(r"^(\d{4})-(\d{2})$", raw)
    if match and 1 <= int(match.group(2)) <= 12:
        return raw
    return None


def read_workbook() -> dict[str, Any]:
    if not EXCEL_PATH.exists():
        raise FileNotFoundError(
            f"No se encontró el archivo Excel: {EXCEL_PATH}"
        )

    wb = load_workbook(EXCEL_PATH, read_only=True, data_only=False)
    try:
        required = {"Ventas", "Productos", "Metas", "Instrucciones"}
        missing = required - set(wb.sheetnames)
        if missing:
            raise ValueError(
                "El Excel no contiene las hojas requeridas: " + ", ".join(sorted(missing))
            )

        sales, invalid_sales = parse_sales(wb["Ventas"])
        products = parse_products(wb["Productos"])
        goals = parse_goals(wb["Metas"])

        if not sales:
            raise ValueError("La hoja Ventas no contiene registros válidos.")

        modified = datetime.fromtimestamp(EXCEL_PATH.stat().st_mtime)
        return {
            "sales": sales,
            "products": products,
            "goals": goals,
            "invalidSales": invalid_sales,
            "lastModified": modified.isoformat(timespec="seconds"),
            "fileSize": EXCEL_PATH.stat().st_size,
        }
    finally:
        wb.close()


def header_map(first_row: Iterable[Any]) -> dict[str, int]:
    return {normalize_header(cell): idx for idx, cell in enumerate(first_row)}


def parse_sales(ws) -> tuple[list[dict[str, Any]], int]:
    rows = ws.iter_rows(values_only=True)
    headers = header_map(next(rows, ()))

    aliases = {
        "fecha": ("fecha",),
        "pedido": ("pedido",),
        "producto": ("producto",),
        "categoria": ("categoria",),
        "cantidad": ("cantidad",),
        "precio": (
            "precio_unitario_mxn",
            "precio_mxn",
            "precio_unitario",
            "precio",
        ),
        "costo": (
            "costo_unitario_mxn",
            "costo_unitario",
            "costo_mxn",
            "costo",
        ),
        "canal": ("canal",),
        "pago": ("metodo_de_pago", "forma_de_pago", "pago"),
    }

    def col(field: str) -> int | None:
        for alias in aliases[field]:
            if alias in headers:
                return headers[alias]
        return None

    indexes = {field: col(field) for field in aliases}
    required = ("fecha", "pedido", "producto", "cantidad", "precio", "costo")
    if any(indexes[f] is None for f in required):
        raise ValueError("La hoja Ventas no tiene todas las columnas esperadas.")

    result: list[dict[str, Any]] = []
    invalid = 0
    for row in rows:
        if all(cell is None for cell in row):
            continue

        def get(field: str) -> Any:
            idx = indexes[field]
            return row[idx] if idx is not None and idx < len(row) else None

        fecha = to_date(get("fecha"))
        cantidad = to_number(get("cantidad"))
        precio = to_number(get("precio"))
        costo = to_number(get("costo"))
        pedido = get("pedido")
        producto = get("producto")

        if (
            fecha is None
            or pedido is None
            or producto is None
            or cantidad is None
            or precio is None
            or costo is None
            or cantidad <= 0
            or precio < 0
            or costo < 0
        ):
            invalid += 1
            continue

        ingreso = cantidad * precio
        costo_total = cantidad * costo
        result.append(
            {
                "fecha": fecha,
                "pedido": str(pedido).strip(),
                "producto": str(producto).strip(),
                "categoria": str(get("categoria") or "Sin categoría").strip(),
                "cantidad": int(cantidad) if cantidad.is_integer() else cantidad,
                "precio": money(precio),
                "costo": money(costo),
                "canal": str(get("canal") or "Sin especificar").strip(),
                "pago": str(get("pago") or "Sin especificar").strip(),
                "ingreso": money(ingreso),
                "costoTotal": money(costo_total),
                "utilidad": money(ingreso - costo_total),
            }
        )

    return result, invalid


def parse_products(ws) -> list[dict[str, Any]]:
    rows = ws.iter_rows(values_only=True)
    headers = header_map(next(rows, ()))
    result = []
    for row in rows:
        if all(cell is None for cell in row):
            continue

        def pick(*aliases: str) -> Any:
            for alias in aliases:
                if alias in headers and headers[alias] < len(row):
                    return row[headers[alias]]
            return None

        name = pick("producto", "nombre")
        if name is None:
            continue
        price = to_number(pick("precio_mxn", "precio", "precio_de_venta_mxn"))
        cost = to_number(pick("costo_mxn", "costo"))
        result.append(
            {
                "id": str(pick("id") or ""),
                "producto": str(name).strip(),
                "categoria": str(pick("categoria") or "Sin categoría").strip(),
                "precio": money(price or 0),
                "costo": money(cost or 0),
                "activo": str(pick("activo") or "Sí").strip(),
            }
        )
    return result


def parse_goals(ws) -> list[dict[str, Any]]:
    rows = ws.iter_rows(values_only=True)
    headers = header_map(next(rows, ()))

    def pick(row: tuple[Any, ...], *aliases: str) -> Any:
        for alias in aliases:
            if alias in headers and headers[alias] < len(row):
                return row[headers[alias]]
        return None

    result = []
    for row in rows:
        if all(cell is None for cell in row):
            continue
        key = parse_yyyy_mm(pick(row, "mes", "mes_objetivo", "periodo"))
        if not key:
            continue
        sales_goal = to_number(
            pick(row, "meta_de_ventas_mxn", "meta_de_ventas", "meta_ventas")
        )
        orders_goal = to_number(pick(row, "meta_de_pedidos", "meta_pedidos"))
        profit_goal = to_number(
            pick(row, "meta_de_utilidad_mxn", "meta_de_utilidad", "meta_utilidad")
        )
        result.append(
            {
                "mes": key,
                "nombre": str(pick(row, "nombre_del_mes", "nombre") or month_label(key)),
                "metaVentas": money(sales_goal or 0),
                "metaPedidos": int(orders_goal or 0),
                "metaUtilidad": money(profit_goal or 0),
            }
        )
    return sorted(result, key=lambda g: g["mes"])


def parse_date_filter(value: str | None, fallback: date) -> date:
    if not value:
        return fallback
    parsed = to_date(value)
    return parsed or fallback


def filter_sales(
    sales: list[dict[str, Any]],
    fecha_desde: str | None,
    fecha_hasta: str | None,
    producto: str | None,
    categoria: str | None,
) -> tuple[list[dict[str, Any]], date, date]:
    dates = [row["fecha"] for row in sales]
    min_date, max_date = min(dates), max(dates)
    start = parse_date_filter(fecha_desde, min_date)
    end = parse_date_filter(fecha_hasta, max_date)
    if start > end:
        start, end = end, start

    selected_product = (producto or "").strip()
    selected_category = (categoria or "").strip()

    filtered = [
        row
        for row in sales
        if start <= row["fecha"] <= end
        and (not selected_product or row["producto"] == selected_product)
        and (not selected_category or row["categoria"] == selected_category)
    ]
    return filtered, start, end


def continuous_months(start: date, end: date) -> list[str]:
    keys = []
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        keys.append(f"{year:04d}-{month:02d}")
        month += 1
        if month == 13:
            year, month = year + 1, 1
    return keys


def aggregate_monthly(rows: list[dict[str, Any]], months: list[str]) -> list[dict[str, Any]]:
    buckets = {key: {"ingreso": 0.0, "costo": 0.0, "utilidad": 0.0, "pedidos": set(), "unidades": 0.0}
               for key in months}
    for row in rows:
        key = month_key(row["fecha"])
        if key not in buckets:
            continue
        bucket = buckets[key]
        bucket["ingreso"] += row["ingreso"]
        bucket["costo"] += row["costoTotal"]
        bucket["utilidad"] += row["utilidad"]
        bucket["pedidos"].add(row["pedido"])
        bucket["unidades"] += row["cantidad"]

    return [
        {
            "mes": key,
            "etiqueta": month_label(key),
            "ingreso": money(buckets[key]["ingreso"]),
            "costo": money(buckets[key]["costo"]),
            "utilidad": money(buckets[key]["utilidad"]),
            "pedidos": len(buckets[key]["pedidos"]),
            "unidades": int(buckets[key]["unidades"]) if buckets[key]["unidades"].is_integer() else buckets[key]["unidades"],
        }
        for key in months
    ]


def top_by(rows: list[dict[str, Any]], field: str, limit: int = 8) -> list[dict[str, Any]]:
    totals: dict[str, dict[str, float]] = defaultdict(
        lambda: {"value": 0.0, "ingreso": 0.0, "unidades": 0.0}
    )
    for row in rows:
        item = totals[row["producto"]]
        item["value"] += row[field]
        item["ingreso"] += row["ingreso"]
        item["unidades"] += row["cantidad"]
    result = [
        {
            "producto": name,
            "valor": money(values["value"]),
            "ingreso": money(values["ingreso"]),
            "unidades": int(values["unidades"]) if values["unidades"].is_integer() else values["unidades"],
        }
        for name, values in totals.items()
    ]
    result.sort(key=lambda item: (-item["valor"], item["producto"]))
    return result[:limit]


def build_dashboard(
    fecha_desde: str | None = None,
    fecha_hasta: str | None = None,
    producto: str | None = None,
    categoria: str | None = None,
) -> dict[str, Any]:
    data = read_workbook()
    all_sales = data["sales"]
    filtered, start, end = filter_sales(
        all_sales, fecha_desde, fecha_hasta, producto, categoria
    )

    months = continuous_months(start, end)
    monthly = aggregate_monthly(filtered, months)

    ingreso_total = money(sum(row["ingreso"] for row in filtered))
    costo_total = money(sum(row["costoTotal"] for row in filtered))
    utilidad_total = money(ingreso_total - costo_total)
    pedidos = len({row["pedido"] for row in filtered})
    unidades = sum(row["cantidad"] for row in filtered)
    unidades = int(unidades) if float(unidades).is_integer() else money(unidades)
    margen = round((utilidad_total / ingreso_total * 100), 2) if ingreso_total else 0.0
    ticket = money(ingreso_total / pedidos) if pedidos else 0.0

    growth = None
    growth_label = None
    if len(monthly) >= 2:
        current, previous = monthly[-1], monthly[-2]
        if previous["ingreso"] > 0:
            growth = round(
                (current["ingreso"] - previous["ingreso"]) / previous["ingreso"] * 100,
                2,
            )
            growth_label = f"{current['etiqueta']} vs {previous['etiqueta']}"

    top_units = top_by(filtered, "cantidad", limit=1)
    top_revenue = top_by(filtered, "ingreso", limit=8)
    best_seller = top_units[0] if top_units else None

    category_totals: dict[str, dict[str, float]] = defaultdict(
        lambda: {"ingreso": 0.0, "unidades": 0.0}
    )
    for row in filtered:
        category_totals[row["categoria"]]["ingreso"] += row["ingreso"]
        category_totals[row["categoria"]]["unidades"] += row["cantidad"]
    categories = [
        {
            "categoria": name,
            "ingreso": money(values["ingreso"]),
            "porcentaje": round(values["ingreso"] / ingreso_total * 100, 2) if ingreso_total else 0.0,
            "unidades": int(values["unidades"]) if values["unidades"].is_integer() else values["unidades"],
        }
        for name, values in category_totals.items()
    ]
    categories.sort(key=lambda item: -item["ingreso"])

    # Las metas se comparan con la compañía completa dentro del rango de fechas.
    goals = [goal for goal in data["goals"] if months[0] <= goal["mes"] <= months[-1]]
    goal_map = {goal["mes"]: goal for goal in goals}
    company_rows = [
        row for row in all_sales if start <= row["fecha"] <= end
    ]
    company_monthly = aggregate_monthly(company_rows, months)
    goals_detail = []
    for item in company_monthly:
        goal = goal_map.get(item["mes"])
        if not goal:
            continue
        goals_detail.append(
            {
                "mes": item["mes"],
                "etiqueta": item["etiqueta"],
                "metaVentas": goal["metaVentas"],
                "resultadoVentas": item["ingreso"],
                "cumplimiento": (
                    round(item["ingreso"] / goal["metaVentas"] * 100, 2)
                    if goal["metaVentas"]
                    else 0.0
                ),
                "metaPedidos": goal["metaPedidos"],
                "resultadoPedidos": item["pedidos"],
                "metaUtilidad": goal["metaUtilidad"],
                "resultadoUtilidad": item["utilidad"],
            }
        )

    meta_ventas_total = sum(g["metaVentas"] for g in goals)
    resultado_ventas_total = sum(g["resultadoVentas"] for g in goals_detail)
    cumplimiento = (
        round(resultado_ventas_total / meta_ventas_total * 100, 2)
        if meta_ventas_total
        else None
    )

    table_rows = [
        {
            "fecha": row["fecha"].isoformat(),
            "pedido": row["pedido"],
            "producto": row["producto"],
            "categoria": row["categoria"],
            "cantidad": row["cantidad"],
            "precio": row["precio"],
            "costo": row["costo"],
            "canal": row["canal"],
            "pago": row["pago"],
            "ingreso": row["ingreso"],
            "costoTotal": row["costoTotal"],
            "utilidad": row["utilidad"],
        }
        for row in sorted(filtered, key=lambda r: (r["fecha"], r["pedido"]), reverse=True)
    ]

    all_dates = [row["fecha"] for row in all_sales]
    options_products = sorted({row["producto"] for row in all_sales})
    options_categories = sorted({row["categoria"] for row in all_sales})

    kpis = {
        "ventasTotales": ingreso_total,
        "pedidos": pedidos,
        "ticketPromedio": ticket,
        "unidadesVendidas": unidades,
        "costos": costo_total,
        "utilidadBruta": utilidad_total,
        "margenBruto": margen,
        "crecimientoMensual": growth,
        "crecimientoEtiqueta": growth_label,
        "productoMasVendido": best_seller,
        "cumplimientoMetas": cumplimiento,
        "registros": len(filtered),
    }

    charts = {
        "evolucion": {
            "labels": [item["etiqueta"] for item in monthly],
            "ingresos": [item["ingreso"] for item in monthly],
            "utilidades": [item["utilidad"] for item in monthly],
        },
        "ingresosCostos": {
            "labels": [item["etiqueta"] for item in monthly],
            "ingresos": [item["ingreso"] for item in monthly],
            "costos": [item["costo"] for item in monthly],
        },
        "categorias": {
            "labels": [item["categoria"] for item in categories],
            "ingresos": [item["ingreso"] for item in categories],
            "porcentajes": [item["porcentaje"] for item in categories],
        },
        "productos": {
            "labels": [item["producto"] for item in top_revenue],
            "ingresos": [item["ingreso"] for item in top_revenue],
            "unidades": [item["unidades"] for item in top_revenue],
        },
        "metas": {
            "labels": [item["etiqueta"] for item in goals_detail],
            "metas": [item["metaVentas"] for item in goals_detail],
            "resultados": [item["resultadoVentas"] for item in goals_detail],
            "cumplimiento": [item["cumplimiento"] for item in goals_detail],
        },
    }

    return {
        "meta": {
            "archivo": EXCEL_PATH.name,
            "ultimaModificacion": data["lastModified"],
            "tamanioBytes": data["fileSize"],
            "registrosTotales": len(all_sales),
            "registrosInvalidos": data["invalidSales"],
            "catalogoProductos": len(data["products"]),
            "disclaimer": DISCLAIMER,
            "fuente": "Excel · openpyxl",
        },
        "filtros": {
            "fechaDesde": start.isoformat(),
            "fechaHasta": end.isoformat(),
            "producto": selected_or(producto),
            "categoria": selected_or(categoria),
            "opciones": {
                "fechaMin": min(all_dates).isoformat(),
                "fechaMax": max(all_dates).isoformat(),
                "productos": options_products,
                "categorias": options_categories,
            },
        },
        "kpis": kpis,
        "graficos": charts,
        "metasDetalle": goals_detail,
        "tabla": {"filas": table_rows, "total": len(table_rows)},
    }


def selected_or(value: str | None) -> str:
    return value.strip() if value and value.strip() else "Todos"
