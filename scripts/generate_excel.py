"""Genera la base de datos Excel de demostración para Puerto A&M | BI.

TODOS LOS DATOS SON FICTICIOS Y SE USAN ÚNICAMENTE CON FINES ACADÉMICOS.
"""

from __future__ import annotations

import calendar
import random
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

from openpyxl import Workbook
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.table import Table, TableStyleInfo

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "Puerto_AM_Base_Datos_DEMO.xlsx"

NAVY = "0B2338"
NAVY_2 = "163A58"
GOLD = "C8A45C"
WARM = "F7F5F0"
WHITE = "FFFFFF"
INK = "1E2933"
MUTED = "667788"
LINE = "DCE3EA"
GREEN = "0F9D76"
RED = "C0392B"
CURRENCY = '"$"#,##0.00'
CURRENCY_NEG = '"$"#,##0.00;[Red]-"$"#,##0.00'
PERCENT = '0.0%'

SEED = 20260331
random.seed(SEED)

PRODUCTS = [
    ("P-001", "Casco de seguridad premium", "Seguridad Industrial", 480.0, 260.0, 6),
    ("P-002", "Guantes de nitrilo (caja 100)", "Seguridad Industrial", 180.0, 95.0, 8),
    ("P-003", "Chaleco reflectivo", "Seguridad Industrial", 320.0, 170.0, 6),
    ("P-004", "Botas de seguridad S3", "Seguridad Industrial", 1450.0, 890.0, 3),
    ("P-005", "Caja corrugada 40x30", "Logística y Empaque", 95.0, 52.0, 10),
    ("P-006", "Fleje de acero 19 mm", "Logística y Empaque", 620.0, 380.0, 5),
    ("P-007", "Pallet de madera estándar", "Logística y Empaque", 780.0, 520.0, 4),
    ("P-008", "Etiquetas térmicas 100x150", "Logística y Empaque", 240.0, 130.0, 8),
    ("P-009", "Laptop corporativa 14\"", "Oficina y Tecnología", 18900.0, 14200.0, 2),
    ("P-010", 'Monitor LED 24"', "Oficina y Tecnología", 4300.0, 3150.0, 3),
    ("P-011", "Teclado ergonómico", "Oficina y Tecnología", 890.0, 540.0, 5),
    ("P-012", "Impresora láser monócroma", "Oficina y Tecnología", 6750.0, 4900.0, 2),
    ("P-013", "Lubricante industrial 1 L", "Mantenimiento", 760.0, 470.0, 5),
    ("P-014", "Cinta adhesiva reforzada", "Mantenimiento", 145.0, 78.0, 10),
]

CHANNELS = ["Mostrador", "Online", "Distribuidor", "Televenta", "Red de socios"]
PAYMENTS = ["Transferencia", "Tarjeta de crédito", "Efectivo", "SPEI", "Crédito a 30 días"]
MONTHLY_ORDERS = [(2026, 1, 108), (2026, 2, 116), (2026, 3, 124)]


def weighted_product():
    weights = [p[5] for p in PRODUCTS]
    return random.choices(PRODUCTS, weights=weights, k=1)[0]


def build_sales():
    sales = []
    order_no = 0
    for year, month, order_count in MONTHLY_ORDERS:
        last_day = calendar.monthrange(year, month)[1]
        for _ in range(order_count):
            order_no += 1
            day = random.randint(1, last_day)
            sale_date = date(year, month, day)
            channel = random.choices(
                CHANNELS, weights=[30, 27, 18, 15, 10], k=1
            )[0]
            payment = random.choices(
                PAYMENTS, weights=[28, 24, 16, 20, 12], k=1
            )[0]
            lines = random.choices([1, 2, 3], weights=[68, 26, 6], k=1)[0]
            used = set()
            for _ in range(lines):
                product = weighted_product()
                while product[0] in used and len(used) < len(PRODUCTS):
                    product = weighted_product()
                used.add(product[0])
                _, name, category, price, cost, _ = product
                discount = 0.0
                if channel == "Distribuidor" and price > 1000:
                    discount = random.choice([0.05, 0.08, 0.10])
                elif channel == "Red de socios":
                    discount = random.choice([0.0, 0.03, 0.05])
                final_price = round(price * (1 - discount), 2)
                qty = random.randint(1, max(1, min(8, 14 - product[5])))
                sales.append(
                    {
                        "fecha": sale_date,
                        "pedido": f"PA-2026-{order_no:04d}",
                        "producto": name,
                        "categoria": category,
                        "cantidad": qty,
                        "precio": final_price,
                        "costo": cost,
                        "canal": channel,
                        "pago": payment,
                    }
                )
    apply_growth_trend(sales)
    random.shuffle(sales)
    sales.sort(key=lambda r: (r["fecha"], r["pedido"]))
    return sales


def apply_growth_trend(sales):
    """Refuerza una tendencia comercial ascendente de enero a marzo.

    Se garantiza un número mínimo de laptops por mes (el artículo de mayor ticket)
    y se ajusta ligeramente la cantidad vendida. Así el KPI de crecimiento muestra
    una evolución positiva y explicable sin perder realismo en los datos.
    """
    laptop = PRODUCTS[8]
    targets = {"2026-01": 3, "2026-02": 5, "2026-03": 11}
    for month, target in targets.items():
        candidates = [
            idx
            for idx, row in enumerate(sales)
            if row["fecha"].strftime("%Y-%m") == month
            and row["precio"] < 1000
            and row["producto"] != laptop[1]
        ]
        current = sum(
            1
            for row in sales
            if row["fecha"].strftime("%Y-%m") == month and row["producto"] == laptop[1]
        )
        random.shuffle(candidates)
        for idx in candidates[: max(0, target - current)]:
            row = sales[idx]
            row["producto"] = laptop[1]
            row["categoria"] = laptop[2]
            row["precio"] = laptop[3]
            row["costo"] = laptop[4]
            row["cantidad"] = random.choice([1, 1, 2])

    quantity_factor = {"2026-01": 1.0, "2026-02": 1.07, "2026-03": 1.16}
    for row in sales:
        factor = quantity_factor[row["fecha"].strftime("%Y-%m")]
        row["cantidad"] = max(1, round(row["cantidad"] * factor))


def style_sheet(ws, headers, widths, table_name, table_style="TableStyleMedium2"):
    for col, (title, width) in enumerate(zip(headers, widths), start=1):
        cell = ws.cell(row=1, column=col, value=title)
        cell.fill = PatternFill("solid", fgColor=NAVY)
        cell.font = Font(name="Aptos", size=10, bold=True, color=WHITE)
        cell.alignment = Alignment(vertical="center", horizontal="left")
        ws.column_dimensions[get_column_letter(col)].width = width
    ws.row_dimensions[1].height = 28

    last_col = get_column_letter(len(headers))
    ref = f"A1:{last_col}{ws.max_row}"
    table = Table(displayName=table_name, ref=ref)
    table.tableStyleInfo = TableStyleInfo(
        name=table_style,
        showFirstColumn=False,
        showLastColumn=False,
        showRowStripes=True,
        showColumnStripes=False,
    )
    ws.add_table(table)
    ws.freeze_panes = "A2"
    ws.sheet_view.showGridLines = False
    ws.sheet_properties.tabColor = GOLD
    ws.auto_filter.ref = ref
    return ref


def style_data_rows(ws, start_row, end_row, cols, money_cols=(), center_cols=()):
    thin = Side(style="hair", color=LINE)
    for row in ws.iter_rows(
        min_row=start_row, max_row=end_row, min_col=1, max_col=cols
    ):
        for cell in row:
            cell.font = Font(name="Aptos", size=10, color=INK)
            cell.alignment = Alignment(vertical="center")
            cell.border = Border(bottom=thin)
            if cell.column in money_cols:
                cell.number_format = CURRENCY
            if cell.column in center_cols:
                cell.alignment = Alignment(vertical="center", horizontal="center")


def write_ventas(wb, sales):
    ws = wb.active
    ws.title = "Ventas"
    headers = [
        "Fecha",
        "Pedido",
        "Producto",
        "Categoría",
        "Cantidad",
        "Precio Unitario (MXN)",
        "Costo Unitario (MXN)",
        "Canal",
        "Método de Pago",
        "Ingreso (MXN)",
        "Costo Total (MXN)",
        "Utilidad (MXN)",
    ]
    for header in headers:
        ws.cell(row=1, column=headers.index(header) + 1, value=header)

    for idx, item in enumerate(sales, start=2):
        ws.cell(row=idx, column=1, value=item["fecha"]).number_format = "dd/mm/yyyy"
        ws.cell(row=idx, column=2, value=item["pedido"])
        ws.cell(row=idx, column=3, value=item["producto"])
        ws.cell(row=idx, column=4, value=item["categoria"])
        ws.cell(row=idx, column=5, value=item["cantidad"])
        ws.cell(row=idx, column=6, value=item["precio"])
        ws.cell(row=idx, column=7, value=item["costo"])
        ws.cell(row=idx, column=8, value=item["canal"])
        ws.cell(row=idx, column=9, value=item["pago"])
        ws.cell(row=idx, column=10, value=f"=E{idx}*F{idx}")
        ws.cell(row=idx, column=11, value=f"=E{idx}*G{idx}")
        ws.cell(row=idx, column=12, value=f"=J{idx}-K{idx}")

    end = len(sales) + 1
    style_sheet(
        ws,
        headers,
        [13, 17, 31, 23, 11, 19, 19, 17, 19, 17, 17, 17],
        "tblVentas",
    )
    style_data_rows(ws, 2, end, 12, money_cols=(6, 7, 10, 11, 12), center_cols=(1, 5))
    for r in range(2, end + 1):
        ws.cell(row=r, column=1).number_format = "dd/mm/yyyy"

    ws.conditional_formatting.add(
        f"L2:L{end}",
        CellIsRule(
            operator="lessThan",
            formula=["0"],
            font=Font(color=RED, bold=True),
            fill=PatternFill("solid", fgColor="FDEDEC"),
        ),
    )

    dv_canal = DataValidation(
        type="list", formula1='"Mostrador,Online,Distribuidor,Televenta,Red de socios"',
        allow_blank=False,
    )
    dv_pago = DataValidation(
        type="list",
        formula1='"Transferencia,Tarjeta de crédito,Efectivo,SPEI,Crédito a 30 días"',
        allow_blank=False,
    )
    ws.add_data_validation(dv_canal)
    ws.add_data_validation(dv_pago)
    dv_canal.add(f"H2:H{end}")
    dv_pago.add(f"I2:I{end}")


def write_productos(wb):
    ws = wb.create_sheet("Productos")
    headers = [
        "ID",
        "Producto",
        "Categoría",
        "Precio (MXN)",
        "Costo (MXN)",
        "Margen (%)",
        "Activo",
    ]
    for c, h in enumerate(headers, start=1):
        ws.cell(row=1, column=c, value=h)

    for idx, (pid, name, category, price, cost, _) in enumerate(PRODUCTS, start=2):
        ws.cell(row=idx, column=1, value=pid)
        ws.cell(row=idx, column=2, value=name)
        ws.cell(row=idx, column=3, value=category)
        ws.cell(row=idx, column=4, value=price)
        ws.cell(row=idx, column=5, value=cost)
        ws.cell(row=idx, column=6, value=f"=(D{idx}-E{idx})/D{idx}")
        ws.cell(row=idx, column=7, value="Sí")

    end = len(PRODUCTS) + 1
    style_sheet(
        ws,
        headers,
        [10, 33, 24, 17, 17, 14, 11],
        "tblProductos",
        "TableStyleMedium4",
    )
    style_data_rows(ws, 2, end, 7, money_cols=(4, 5), center_cols=(1, 7))
    for r in range(2, end + 1):
        ws.cell(row=r, column=6).number_format = PERCENT
        ws.cell(row=r, column=6).alignment = Alignment(horizontal="center")


def write_metas(wb, sales):
    monthly = defaultdict(lambda: {"ingreso": 0.0, "pedidos": set(), "utilidad": 0.0})
    for item in sales:
        key = item["fecha"].strftime("%Y-%m")
        monthly[key]["ingreso"] += item["cantidad"] * item["precio"]
        monthly[key]["pedidos"].add(item["pedido"])
        monthly[key]["utilidad"] += item["cantidad"] * (item["precio"] - item["costo"])

    factors = {"2026-01": 0.94, "2026-02": 1.06, "2026-03": 0.97}
    names = {"2026-01": "Enero 2026", "2026-02": "Febrero 2026", "2026-03": "Marzo 2026"}

    ws = wb.create_sheet("Metas")
    headers = [
        "Mes",
        "Nombre del Mes",
        "Meta de Ventas (MXN)",
        "Meta de Pedidos",
        "Meta de Utilidad (MXN)",
    ]
    for c, h in enumerate(headers, start=1):
        ws.cell(row=1, column=c, value=h)

    for idx, key in enumerate(["2026-01", "2026-02", "2026-03"], start=2):
        f = factors[key]
        ws.cell(row=idx, column=1, value=key)
        ws.cell(row=idx, column=2, value=names[key])
        ws.cell(row=idx, column=3, value=round(monthly[key]["ingreso"] * f / 1000) * 1000)
        ws.cell(row=idx, column=4, value=round(len(monthly[key]["pedidos"]) * f))
        ws.cell(row=idx, column=5, value=round(monthly[key]["utilidad"] * f / 1000) * 1000)

    style_sheet(
        ws,
        headers,
        [13, 22, 24, 20, 26],
        "tblMetas",
        "TableStyleMedium5",
    )
    style_data_rows(ws, 2, 4, 5, money_cols=(3, 5), center_cols=(1, 4))

    note = ws.cell(
        row=6,
        column=1,
        value=(
            "Nota: objetivos ficticios de la simulación. El dashboard compara estas "
            "metas con el total de la compañía por mes; los filtros de producto y "
            "categoría no se aplican a esta comparación."
        ),
    )
    note.font = Font(name="Aptos", size=9, italic=True, color=MUTED)
    ws.merge_cells(start_row=6, start_column=1, end_row=6, end_column=5)
    ws.row_dimensions[6].height = 30
    note.alignment = Alignment(wrap_text=True, vertical="center")


def write_instrucciones(wb, record_count):
    ws = wb.create_sheet("Instrucciones")
    ws.sheet_view.showGridLines = False
    ws.sheet_properties.tabColor = NAVY_2
    ws.column_dimensions["A"].width = 6
    ws.column_dimensions["B"].width = 108

    title = ws.cell(row=1, column=2, value="PUERTO A&M | BUSINESS INTELLIGENCE")
    title.font = Font(name="Aptos Display", size=18, bold=True, color=NAVY)
    ws.row_dimensions[1].height = 34

    sub = ws.cell(
        row=2,
        column=2,
        value="Base de datos de demostración — SIMULACIÓN ACADÉMICA · Todos los valores son ficticios.",
    )
    sub.font = Font(name="Aptos", size=10, bold=True, color=GOLD)
    ws.row_dimensions[2].height = 22

    steps = [
        ("1.", "Abre este archivo con Microsoft Excel o LibreOffice Calc."),
        (
            "2.",
            "Edita únicamente las celdas de las columnas Fecha, Pedido, Producto, Categoría, "
            "Cantidad, Precio Unitario (MXN), Costo Unitario (MXN), Canal y Método de Pago "
            "en la hoja Ventas. Las columnas Ingreso, Costo Total y Utilidad se recalculan "
            "automáticamente en Excel; el dashboard las vuelve a calcular desde las cifras base.",
        ),
        (
            "3.",
            "Para dar de alta artículos, agrega renglones a la tabla de la hoja Productos. "
            "Usa exactamente la misma ortografía del producto en la hoja Ventas.",
        ),
        (
            "4.",
            "Para cambiar objetivos, modifica los importes de la hoja Metas. El mes debe "
            "mantenerse en formato AAAA-MM (por ejemplo, 2026-01).",
        ),
        ("5.", "Guarda el archivo con el mismo nombre y en la misma carpeta data/."),
        (
            "6.",
            "En el dashboard pulsa el botón «Actualizar datos». El backend vuelve a leer "
            "el Excel en ese instante y recalcula todos los indicadores y gráficos; "
            "no necesitas cambiar una sola línea de código.",
        ),
        (
            "7.",
            "Si agregas más registros, procura que la fecha esté entre enero y marzo de 2026 "
            "para que aparezcan en los filtros predeterminados. Puedes ampliar el rango "
            "con los seleccionadores de fecha del dashboard.",
        ),
        (
            "8.",
            "Los filtros del dashboard combinan fecha, producto y categoría. La meta mensual "
            "siempre se compara con el resultado total de la compañía para ese mes.",
        ),
    ]
    row = 4
    for number, text in steps:
        c_num = ws.cell(row=row, column=1, value=number)
        c_num.font = Font(name="Aptos", size=11, bold=True, color=GOLD)
        c_num.alignment = Alignment(horizontal="center", vertical="top")
        c_text = ws.cell(row=row, column=2, value=text)
        c_text.font = Font(name="Aptos", size=10, color=INK)
        c_text.alignment = Alignment(wrap_text=True, vertical="top")
        ws.row_dimensions[row].height = 42 if len(text) > 120 else 26
        row += 1

    row += 1
    footer = ws.cell(
        row=row,
        column=2,
        value=(
            f"Registros iniciales: {record_count} líneas de venta · "
            "Versión de demostración 1.0 · Uso exclusivo para práctica de Top Learning."
        ),
    )
    footer.font = Font(name="Aptos", size=9, italic=True, color=MUTED)


def main():
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    sales = build_sales()

    wb = Workbook()
    wb.properties.title = "Puerto A&M | Base de datos de demostración"
    wb.properties.subject = "Simulación académica de Business Intelligence"
    wb.properties.creator = "Puerto A&M · Top Learning"
    wb.properties.description = (
        "Todos los datos son ficticios. Base de datos de demostración para el dashboard "
        "Puerto A&M | Business Intelligence."
    )
    wb.calculation.fullCalcOnLoad = True
    wb.calculation.calcMode = "auto"

    write_ventas(wb, sales)
    write_productos(wb)
    write_metas(wb, sales)
    write_instrucciones(wb, len(sales))

    wb.save(OUTPUT)
    print(f"Excel generado: {OUTPUT}")
    print(f"Registros de venta: {len(sales)}")
    print(f"Pedidos únicos: {len({s['pedido'] for s in sales})}")


if __name__ == "__main__":
    main()
