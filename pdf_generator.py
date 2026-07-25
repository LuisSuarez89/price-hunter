"""
pdf_generator.py — genera el reporte como PDF adjunto.

Usa reportlab (Platypus) para crear un PDF con la misma estructura
que el HTML: agrupado por tienda, tabla con colores verde/rojo por
precio normalizado, marca y presentación.

API pública:
    pdf_bytes = generate_pdf(comparison: dict) -> bytes
"""

import io
from datetime import date
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    BaseDocTemplate, Frame, PageTemplate,
    Paragraph, Spacer, Table, TableStyle,
    HRFlowable, KeepTogether,
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT

# ── Paleta de colores ─────────────────────────────────────────────────────────
GREEN_BG   = colors.HexColor("#C8E6C9")
GREEN_TEXT = colors.HexColor("#1B5E20")
RED_BG     = colors.HexColor("#FFCDD2")
RED_TEXT   = colors.HexColor("#B71C1C")
MID_BG     = colors.white
MID_TEXT   = colors.HexColor("#212121")

STORE_COLORS = {
    "d1":      colors.HexColor("#C62828"),
    "ara":     colors.HexColor("#E65100"),
    "alkosto": colors.HexColor("#1565C0"),
    "makro":   colors.HexColor("#2E7D32"),
    "olimpica":colors.HexColor("#6A1B9A"),
}
STORE_NAMES = {
    "d1":"D1", "ara":"Ara", "alkosto":"Alkosto",
    "makro":"Makro", "olimpica":"Olímpica",
}
CAT_LABELS = {
    "carnes":         "Carnes y proteínas",
    "lacteos_huevos": "Lácteos y huevos",
    "despensa":       "Despensa y granos",
    "aseo_hogar":     "Aseo del hogar",
    "aseo_personal":  "Aseo personal",
}

# ── Estilos ───────────────────────────────────────────────────────────────────
def _styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("rpt_title",
            parent=base["Normal"], fontSize=18, fontName="Helvetica-Bold",
            textColor=colors.white, alignment=TA_LEFT, spaceAfter=2),
        "subtitle": ParagraphStyle("rpt_sub",
            parent=base["Normal"], fontSize=10, fontName="Helvetica",
            textColor=colors.HexColor("#BBDEFB"), alignment=TA_LEFT),
        "store_title": ParagraphStyle("store_title",
            parent=base["Normal"], fontSize=13, fontName="Helvetica-Bold",
            textColor=colors.white, alignment=TA_LEFT),
        "store_sub": ParagraphStyle("store_sub",
            parent=base["Normal"], fontSize=9, fontName="Helvetica",
            textColor=colors.HexColor("#EEEEEE"), alignment=TA_LEFT),
        "cat_label": ParagraphStyle("cat_label",
            parent=base["Normal"], fontSize=8, fontName="Helvetica-Bold",
            textColor=colors.HexColor("#555555"), alignment=TA_LEFT),
        "cell": ParagraphStyle("cell",
            parent=base["Normal"], fontSize=8, fontName="Helvetica",
            textColor=MID_TEXT, alignment=TA_LEFT, leading=10),
        "cell_bold": ParagraphStyle("cell_bold",
            parent=base["Normal"], fontSize=8, fontName="Helvetica-Bold",
            textColor=MID_TEXT, alignment=TA_LEFT, leading=10),
        "cell_right": ParagraphStyle("cell_right",
            parent=base["Normal"], fontSize=8, fontName="Helvetica",
            textColor=MID_TEXT, alignment=TA_RIGHT, leading=10),
        "cell_right_bold": ParagraphStyle("cell_right_bold",
            parent=base["Normal"], fontSize=9, fontName="Helvetica-Bold",
            textColor=MID_TEXT, alignment=TA_RIGHT, leading=11),
        "footer": ParagraphStyle("footer",
            parent=base["Normal"], fontSize=7, fontName="Helvetica",
            textColor=colors.HexColor("#999999"), alignment=TA_CENTER),
    }


# ── Helpers ───────────────────────────────────────────────────────────────────
def _rank_colors(ppu: float, ranked: list) -> tuple:
    """Retorna (bg_color, text_color, badge_str) según posición global."""
    if not ranked or ppu <= 0:
        return MID_BG, MID_TEXT, ""
    ppus = [r.get("price_per_unit", 0) for r in ranked]
    best  = min(ppus)
    worst = max(ppus)
    n     = len(ppus)
    if n > 1 and abs(ppu - best)  / (best  + 0.01) < 0.005:
        return GREEN_BG, GREEN_TEXT, "MEJOR"
    if n > 1 and abs(ppu - worst) / (worst + 0.01) < 0.005:
        return RED_BG,   RED_TEXT,   "MAS CARO"
    pos = sorted(set(ppus)).index(min(ppus, key=lambda x: abs(x - ppu))) + 1
    return MID_BG, MID_TEXT, f"#{pos}/{n}"


def _fmt(val: float) -> str:
    """Formatea precio en pesos colombianos."""
    return f"${val:,.0f}".replace(",", ".")


# ── Header y footer de página ─────────────────────────────────────────────────
def _header_footer(canvas, doc):
    canvas.saveState()
    w, h = A4
    # Franja superior
    canvas.setFillColor(colors.HexColor("#1A237E"))
    canvas.rect(0, h - 1.8*cm, w, 1.8*cm, fill=1, stroke=0)
    canvas.setFillColor(colors.white)
    canvas.setFont("Helvetica-Bold", 12)
    canvas.drawString(1*cm, h - 1.2*cm, "SOS Price Hunter")
    canvas.setFont("Helvetica", 9)
    canvas.setFillColor(colors.HexColor("#BBDEFB"))
    canvas.drawString(1*cm, h - 1.55*cm, f"Reporte mensual · {doc.report_date}")
    canvas.setFillColor(colors.HexColor("#BBDEFB"))
    canvas.drawRightString(w - 1*cm, h - 1.2*cm, f"Pagina {doc.page}")
    # Franja inferior
    canvas.setFillColor(colors.HexColor("#F5F5F5"))
    canvas.rect(0, 0, w, 0.8*cm, fill=1, stroke=0)
    canvas.setFillColor(colors.HexColor("#999999"))
    canvas.setFont("Helvetica", 7)
    canvas.drawCentredString(w/2, 0.25*cm,
        "Precios sujetos a cambios. Verificar en tienda antes de comprar.")
    canvas.restoreState()


# ── Tabla de resumen KPI ──────────────────────────────────────────────────────
def _kpi_table(comparison: dict, styles: dict) -> Table:
    savings    = comparison.get("total_savings_estimate", 0)
    n_products = comparison.get("products_compared", 0)
    stores     = comparison.get("stores_found", [])

    store_pills = "  ·  ".join(
        STORE_NAMES.get(s, s) for s in stores
    )

    data = [[
        Paragraph(f"{n_products}", ParagraphStyle("kpi_n",
            fontSize=22, fontName="Helvetica-Bold",
            textColor=colors.HexColor("#1A237E"), alignment=TA_CENTER)),
        Paragraph(f"{len(stores)}", ParagraphStyle("kpi_s",
            fontSize=22, fontName="Helvetica-Bold",
            textColor=colors.HexColor("#1A237E"), alignment=TA_CENTER)),
        Paragraph(_fmt(savings), ParagraphStyle("kpi_g",
            fontSize=22, fontName="Helvetica-Bold",
            textColor=colors.HexColor("#2E7D32"), alignment=TA_CENTER)),
    ], [
        Paragraph("productos comparados", ParagraphStyle("kpi_nl",
            fontSize=8, textColor=colors.HexColor("#555"), alignment=TA_CENTER)),
        Paragraph("tiendas revisadas", ParagraphStyle("kpi_sl",
            fontSize=8, textColor=colors.HexColor("#555"), alignment=TA_CENTER)),
        Paragraph("ahorro potencial", ParagraphStyle("kpi_gl",
            fontSize=8, textColor=colors.HexColor("#2E7D32"), alignment=TA_CENTER)),
    ]]

    t = Table(data, colWidths=[5.5*cm, 5.5*cm, 5.5*cm])
    t.setStyle(TableStyle([
        ("BOX",       (0,0), (-1,-1), 0.5, colors.HexColor("#E0E0E0")),
        ("INNERGRID", (0,0), (-1,-1), 0.5, colors.HexColor("#E0E0E0")),
        ("ROWBACKGROUNDS", (0,0), (-1,-1), [colors.HexColor("#FAFAFA"), colors.white]),
        ("TOPPADDING",    (0,0), (-1,-1), 8),
        ("BOTTOMPADDING", (0,0), (-1,-1), 6),
        ("LEFTPADDING",   (0,0), (-1,-1), 8),
        ("RIGHTPADDING",  (0,0), (-1,-1), 8),
        ("ROUNDEDCORNERS", [4]),
    ]))
    return t


# ── Tabla de productos por tienda ─────────────────────────────────────────────
def _store_table(store_id: str, product_ids: list, by_product: dict,
                 global_ranked: dict, styles: dict) -> list:
    """Retorna lista de Flowables para una tienda."""
    store_color = STORE_COLORS.get(store_id, colors.HexColor("#555555"))
    store_name  = STORE_NAMES.get(store_id, store_id.upper())
    n_best      = len(product_ids)

    # ── Cabecera de tienda ────────────────────────────────────────────────────
    header_data = [[
        Paragraph(store_name, styles["store_title"]),
        Paragraph(f"{n_best} producto(s) al mejor precio", styles["store_sub"]),
    ]]
    header_table = Table(header_data, colWidths=[4*cm, 12.7*cm])
    header_table.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,-1), store_color),
        ("TOPPADDING",    (0,0), (-1,-1), 8),
        ("BOTTOMPADDING", (0,0), (-1,-1), 8),
        ("LEFTPADDING",   (0,0), (-1,-1), 10),
        ("RIGHTPADDING",  (0,0), (-1,-1), 10),
        ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
    ]))

    # ── Cabecera de columnas ──────────────────────────────────────────────────
    col_header = [
        Paragraph("Producto",       styles["cat_label"]),
        Paragraph("Marca",          styles["cat_label"]),
        Paragraph("Presentacion",   styles["cat_label"]),
        Paragraph("Precio",         styles["cat_label"]),
        Paragraph("Normalizado",    styles["cat_label"]),
        Paragraph("Ranking",        styles["cat_label"]),
    ]
    col_widths = [5.8*cm, 2.8*cm, 2.5*cm, 2.2*cm, 2.4*cm, 1.0*cm]

    # ── Agrupar por categoría ─────────────────────────────────────────────────
    by_cat: dict = {}
    for pid in product_ids:
        entry = by_product.get(pid)
        if not entry:
            continue
        cat = entry["product"].get("category", "otros")
        by_cat.setdefault(cat, []).append((pid, entry))

    table_data   = [col_header]
    row_styles   = [
        ("BACKGROUND",    (0,0), (-1,0), colors.HexColor("#F5F5F5")),
        ("FONTNAME",      (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE",      (0,0), (-1,0), 7),
        ("TEXTCOLOR",     (0,0), (-1,0), colors.HexColor("#555555")),
        ("TOPPADDING",    (0,0), (-1,0), 5),
        ("BOTTOMPADDING", (0,0), (-1,0), 5),
        ("LINEBELOW",     (0,0), (-1,0), 1,   colors.HexColor("#DDDDDD")),
        ("GRID",          (0,0), (-1,-1), 0.3, colors.HexColor("#EEEEEE")),
        ("LEFTPADDING",   (0,0), (-1,-1), 5),
        ("RIGHTPADDING",  (0,0), (-1,-1), 5),
        ("TOPPADDING",    (0,1), (-1,-1), 4),
        ("BOTTOMPADDING", (0,1), (-1,-1), 4),
        ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
    ]
    row_idx = 1  # 0 = col_header

    for cat, entries in by_cat.items():
        # Fila de categoría
        cat_label = CAT_LABELS.get(cat, cat.title())
        table_data.append([
            Paragraph(cat_label, styles["cat_label"]),
            "", "", "", "", "",
        ])
        row_styles += [
            ("BACKGROUND",  (0, row_idx), (-1, row_idx), colors.HexColor("#F8F8F8")),
            ("SPAN",        (0, row_idx), (-1, row_idx)),
            ("TOPPADDING",  (0, row_idx), (-1, row_idx), 5),
            ("BOTTOMPADDING",(0,row_idx), (-1, row_idx), 3),
            ("LINEABOVE",   (0, row_idx), (-1, row_idx), 0.5, colors.HexColor("#DDDDDD")),
        ]
        row_idx += 1

        for pid, entry in entries:
            ranked = global_ranked.get(pid, [])
            store_prices = [
                p for p in entry.get("all_prices", [])
                if p.get("store") == store_id
            ]
            if not store_prices:
                store_prices = [entry["winner"]] if entry.get("winner") else []

            for pr in store_prices:
                ppu      = pr.get("price_per_unit", 0)
                unit_lbl = pr.get("unit_label", "")
                qty      = pr.get("quantity_display", "") or ""
                name     = pr.get("product_name", entry["product"]["name"])
                brand    = pr.get("brand", "") or ""
                price    = pr.get("price", 0)
                disc     = pr.get("discount_pct", 0)

                bg, tc, badge_str = _rank_colors(ppu, ranked)

                # Nombre con badge de descuento si aplica
                name_text = name
                if disc and disc > 0:
                    name_text += f" (-{disc:.0f}%)"

                norm_str = f"${ppu:,.1f}{unit_lbl}" if ppu else "-"

                table_data.append([
                    Paragraph(name_text, ParagraphStyle("cn",
                        fontSize=8, fontName="Helvetica",
                        textColor=tc, leading=10)),
                    Paragraph(brand, ParagraphStyle("cb",
                        fontSize=7, fontName="Helvetica",
                        textColor=colors.HexColor("#666666"), leading=9)),
                    Paragraph(qty or "-", ParagraphStyle("cq",
                        fontSize=7, fontName="Helvetica",
                        textColor=colors.HexColor("#666666"), leading=9)),
                    Paragraph(_fmt(price), ParagraphStyle("cp",
                        fontSize=9, fontName="Helvetica-Bold",
                        textColor=tc, alignment=TA_RIGHT, leading=11)),
                    Paragraph(norm_str, ParagraphStyle("cn2",
                        fontSize=7, fontName="Helvetica",
                        textColor=colors.HexColor("#777777"),
                        alignment=TA_RIGHT, leading=9)),
                    Paragraph(badge_str, ParagraphStyle("cbg",
                        fontSize=7, fontName="Helvetica-Bold",
                        textColor=tc, alignment=TA_CENTER, leading=9)),
                ])
                row_styles.append(("BACKGROUND", (0, row_idx), (-1, row_idx), bg))
                row_idx += 1

    t = Table(table_data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle(row_styles))

    return [
        KeepTogether([header_table]),
        Spacer(1, 2),
        t,
        Spacer(1, 14),
    ]


# ── Punto de entrada público ──────────────────────────────────────────────────
def generate_pdf(comparison: dict) -> bytes:
    """
    Genera el PDF del reporte a partir del dict de comparación.
    Retorna los bytes del PDF listo para adjuntar al email.
    """
    buf    = io.BytesIO()
    styles = _styles()
    today  = comparison.get("date", str(date.today()))

    # ── Configurar documento ──────────────────────────────────────────────────
    doc = BaseDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=1*cm,
        rightMargin=1*cm,
        topMargin=2.2*cm,
        bottomMargin=1.2*cm,
    )
    doc.report_date = today  # accesible desde _header_footer

    frame = Frame(
        doc.leftMargin, doc.bottomMargin,
        doc.width, doc.height,
        id="main",
    )
    doc.addPageTemplates([
        PageTemplate(id="main", frames=frame, onPage=_header_footer)
    ])

    # ── Índice global de ranking ──────────────────────────────────────────────
    by_product   = comparison.get("by_product", {})
    by_store     = comparison.get("by_store", {})
    global_ranked = {
        pid: sorted(
            [p for p in data.get("all_prices", []) if p.get("price_per_unit", 0) > 0],
            key=lambda x: x["price_per_unit"]
        )
        for pid, data in by_product.items()
    }

    # ── Armar el story ────────────────────────────────────────────────────────
    story = []

    # KPIs
    story.append(_kpi_table(comparison, styles))
    story.append(Spacer(1, 10))

    # Leyenda
    legend_data = [[
        Paragraph(
            "<b>Guia de colores:</b>  "
            "<font color='#1B5E20'><b>Verde = mejor precio/cantidad</b></font>   "
            "<font color='#B71C1C'><b>Rojo = precio mas alto</b></font>   "
            "Blanco = precio intermedio",
            ParagraphStyle("legend", fontSize=8, fontName="Helvetica",
                           textColor=colors.HexColor("#444444"), leading=11)
        )
    ]]
    legend_t = Table(legend_data, colWidths=[doc.width])
    legend_t.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,-1), colors.HexColor("#F8F9FA")),
        ("BOX",           (0,0), (-1,-1), 0.5, colors.HexColor("#DDDDDD")),
        ("TOPPADDING",    (0,0), (-1,-1), 7),
        ("BOTTOMPADDING", (0,0), (-1,-1), 7),
        ("LEFTPADDING",   (0,0), (-1,-1), 10),
    ]))
    story.append(legend_t)
    story.append(Spacer(1, 12))

    # Secciones por tienda
    for store_id, pids in sorted(by_store.items(), key=lambda x: -len(x[1])):
        story.extend(
            _store_table(store_id, pids, by_product, global_ranked, styles)
        )

    doc.build(story)
    return buf.getvalue()
