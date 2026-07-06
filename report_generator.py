"""
report_generator.py
Genera el reporte HTML con tabla de colores por tienda y envía via Apps Script.

Tabla por tienda:
  Producto | Marca | Presentación | Precio | $/100g o /L | Ranking
  - Verde  → mejor precio global
  - Rojo   → precio más alto global
  - Blanco → precio intermedio
"""
import json, os, logging, requests
from datetime import date
from pathlib import Path

log = logging.getLogger("report_generator")

STORE_META = {
    "d1":      {"name":"D1",       "color":"#C62828","bg":"#FFEBEE","emoji":"🔴"},
    "ara":     {"name":"Ara",      "color":"#E65100","bg":"#FFF3E0","emoji":"🟠"},
    "alkosto": {"name":"Alkosto",  "color":"#1565C0","bg":"#E3F2FD","emoji":"🔵"},
    "makro":   {"name":"Makro",    "color":"#2E7D32","bg":"#E8F5E9","emoji":"🟢"},
    "olimpica":{"name":"Olímpica", "color":"#6A1B9A","bg":"#F3E5F5","emoji":"🟣"},
}
CAT_LABELS = {
    "carnes":         "🥩 Carnes y proteínas",
    "lacteos_huevos": "🥚 Lácteos y huevos",
    "despensa":       "🌾 Despensa y granos",
    "aseo_hogar":     "🧹 Aseo del hogar",
    "aseo_personal":  "🧴 Aseo personal",
}
C_BEST  = "#C8E6C9"; T_BEST  = "#1B5E20"
C_WORST = "#FFCDD2"; T_WORST = "#B71C1C"
C_MID   = "#FFFFFF"; T_MID   = "#212121"


def _rank_color(ppu: float, ranked: list) -> tuple:
    """Retorna (bg, text_color, badge) según posición en el ranking global."""
    if not ranked or ppu <= 0:
        return C_MID, T_MID, ""
    n = len(ranked)
    ppus = [r.get("price_per_unit", 0) for r in ranked]
    best  = min(ppus)
    worst = max(ppus)
    # Tolerancia 0.5% para empates
    if abs(ppu - best)  / (best  + 0.01) < 0.005:
        badge = ('<span style="background:#2E7D32;color:#fff;padding:2px 8px;'
                 'border-radius:10px;font-size:11px;font-weight:700;">✓ MEJOR</span>')
        return C_BEST, T_BEST, badge
    if n > 1 and abs(ppu - worst) / (worst + 0.01) < 0.005:
        badge = ('<span style="background:#C62828;color:#fff;padding:2px 8px;'
                 'border-radius:10px;font-size:11px;font-weight:700;">↑ MÁS CARO</span>')
        return C_WORST, T_WORST, badge
    # Posición intermedia
    pos = sorted(set(ppus)).index(min(ppus, key=lambda x: abs(x-ppu))) + 1
    badge = (f'<span style="background:#e0e0e0;color:#555;padding:2px 8px;'
             f'border-radius:10px;font-size:11px;">#{pos}/{n}</span>')
    return C_MID, T_MID, badge


def _store_section(store_id: str, product_ids: list, by_product: dict,
                   global_ranked: dict) -> str:
    m = STORE_META.get(store_id, {"name":store_id,"color":"#555","bg":"#fafafa","emoji":""})

    # Agrupar por categoría
    by_cat: dict = {}
    for pid in product_ids:
        entry = by_product.get(pid)
        if not entry: continue
        cat = entry["product"].get("category","otros")
        by_cat.setdefault(cat, []).append((pid, entry))

    rows = ""
    for cat, entries in by_cat.items():
        rows += (f'<tr><td colspan="6" style="padding:10px 12px 4px;font-size:11px;'
                 f'font-weight:700;color:#777;text-transform:uppercase;letter-spacing:.6px;'
                 f'background:#f8f8f8;border-bottom:1px solid #eee;">'
                 f'{CAT_LABELS.get(cat, cat.title())}</td></tr>')

        for pid, entry in entries:
            # TODOS los resultados de esta tienda para este producto
            store_results = [p for p in entry.get("all_prices", [])
                             if p.get("store") == store_id]
            if not store_results:
                store_results = [entry["winner"]] if entry.get("winner") else []

            ranked = global_ranked.get(pid, [])

            for pr in store_results:
                ppu       = pr.get("price_per_unit", 0)
                unit_lbl  = pr.get("unit_label", "")
                qty       = pr.get("quantity_display", "") or ""
                name      = pr.get("product_name", entry["product"]["name"])
                brand     = pr.get("brand", "") or ""
                price     = pr.get("price", 0)
                url       = pr.get("url", "")
                disc      = pr.get("discount_pct", 0)

                bg, tc, badge = _rank_color(ppu, ranked)

                disc_badge = ""
                if disc and disc > 0:
                    disc_badge = (f'<span style="margin-left:6px;padding:1px 7px;'
                                  f'border-radius:10px;background:#E8F5E9;color:#2E7D32;'
                                  f'font-size:11px;font-weight:600;">-{disc:.0f}%</span>')

                name_cell = (f'<a href="{url}" style="color:inherit;text-decoration:none;'
                             f'font-weight:500;">{name}</a>'
                             if url and url not in ("manual","") else
                             f'<span style="font-weight:500;">{name}</span>')

                rows += f"""
<tr style="background:{bg};border-bottom:1px solid #f0f0f0;">
  <td style="padding:9px 12px;font-size:13px;color:{tc};">{name_cell}{disc_badge}</td>
  <td style="padding:9px 12px;font-size:12px;color:#555;">{brand}</td>
  <td style="padding:9px 12px;font-size:12px;color:#555;white-space:nowrap;">{qty or "—"}</td>
  <td style="padding:9px 12px;font-size:14px;font-weight:700;color:{tc};white-space:nowrap;">
    ${price:,.0f}</td>
  <td style="padding:9px 12px;font-size:12px;color:#777;white-space:nowrap;">
    {f"${ppu:,.1f}{unit_lbl}" if ppu else "—"}</td>
  <td style="padding:9px 12px;text-align:center;">{badge}</td>
</tr>"""

    return f"""
<div style="margin-bottom:28px;border-radius:12px;overflow:hidden;
  border:1.5px solid {m['color']}44;box-shadow:0 2px 8px #0001;">
  <div style="background:{m['color']};color:#fff;padding:14px 18px;
    display:flex;align-items:center;gap:10px;">
    <span style="font-size:20px;">{m['emoji']}</span>
    <div>
      <div style="font-size:17px;font-weight:600;">{m['name']}</div>
      <div style="font-size:12px;opacity:.85;">{len(product_ids)} producto(s) al mejor precio</div>
    </div>
  </div>
  <div style="overflow-x:auto;">
  <table style="width:100%;border-collapse:collapse;background:#fff;min-width:560px;">
    <thead>
      <tr style="background:#fafafa;border-bottom:2px solid #eee;">
        <th style="padding:8px 12px;text-align:left;font-size:11px;color:#888;
          font-weight:600;text-transform:uppercase;letter-spacing:.4px;">Producto</th>
        <th style="padding:8px 12px;text-align:left;font-size:11px;color:#888;
          font-weight:600;text-transform:uppercase;letter-spacing:.4px;">Marca</th>
        <th style="padding:8px 12px;text-align:left;font-size:11px;color:#888;
          font-weight:600;text-transform:uppercase;letter-spacing:.4px;">Presentación</th>
        <th style="padding:8px 12px;text-align:left;font-size:11px;color:#888;
          font-weight:600;text-transform:uppercase;letter-spacing:.4px;">Precio</th>
        <th style="padding:8px 12px;text-align:left;font-size:11px;color:#888;
          font-weight:600;text-transform:uppercase;letter-spacing:.4px;">Normalizado</th>
        <th style="padding:8px 12px;text-align:center;font-size:11px;color:#888;
          font-weight:600;text-transform:uppercase;letter-spacing:.4px;">Ranking</th>
      </tr>
    </thead>
    <tbody>{rows}</tbody>
  </table>
  </div>
</div>"""


def build_html(comparison: dict) -> str:
    today      = comparison["date"]
    by_store   = comparison["by_store"]
    by_product = comparison["by_product"]
    savings    = comparison.get("total_savings_estimate", 0)
    n          = comparison.get("products_compared", 0)

    # Índice de ranking global: pid → lista ordenada de todos los precios
    global_ranked = {
        pid: sorted(
            [p for p in data.get("all_prices", []) if p.get("price_per_unit", 0) > 0],
            key=lambda x: x["price_per_unit"]
        )
        for pid, data in by_product.items()
    }

    # KPIs
    pills = "".join(
        f'<span style="display:inline-block;margin:4px 5px 4px 0;padding:5px 13px;'
        f'border-radius:20px;background:{STORE_META.get(s,{}).get("color","#555")};'
        f'color:#fff;font-size:13px;font-weight:500;">'
        f'{STORE_META.get(s,{}).get("emoji","")} '
        f'{STORE_META.get(s,{}).get("name",s)}: {len(pids)}</span>'
        for s, pids in sorted(by_store.items(), key=lambda x: -len(x[1]))
    )

    header = f"""
<div style="background:linear-gradient(135deg,#1a237e,#283593);color:#fff;
  border-radius:14px;padding:22px 24px;margin-bottom:22px;">
  <div style="font-size:21px;font-weight:700;margin-bottom:4px;">
    🛒 SOS Price Hunter — Reporte mensual</div>
  <div style="font-size:13px;opacity:.75;margin-bottom:16px;">{today}</div>
  <div style="display:flex;gap:14px;flex-wrap:wrap;margin-bottom:16px;">
    <div style="background:rgba(255,255,255,.15);border-radius:10px;
      padding:10px 18px;text-align:center;">
      <div style="font-size:20px;font-weight:700;">{n}</div>
      <div style="font-size:11px;opacity:.8;">productos</div></div>
    <div style="background:rgba(255,255,255,.15);border-radius:10px;
      padding:10px 18px;text-align:center;">
      <div style="font-size:20px;font-weight:700;">{len(by_store)}</div>
      <div style="font-size:11px;opacity:.8;">tiendas</div></div>
    <div style="background:rgba(76,175,80,.45);border-radius:10px;
      padding:10px 18px;text-align:center;">
      <div style="font-size:20px;font-weight:700;">${savings:,.0f}</div>
      <div style="font-size:11px;opacity:.8;">ahorro potencial</div></div>
  </div>
  <div>{pills}</div>
</div>"""

    legend = f"""
<div style="background:#f8f9fa;border:1px solid #e0e0e0;border-radius:10px;
  padding:12px 18px;margin-bottom:22px;font-size:13px;line-height:1.8;">
  <strong>Guía de colores</strong> — comparación por precio normalizado ($/100g o $/L)
  entre todas las variantes de todas las tiendas:<br>
  <span style="background:{C_BEST};color:{T_BEST};padding:2px 10px;
    border-radius:4px;font-weight:600;">■ Mejor precio</span>&nbsp;
  <span style="background:{C_WORST};color:{T_WORST};padding:2px 10px;
    border-radius:4px;font-weight:600;">■ Precio más alto</span>&nbsp;
  <span style="background:#fff;border:1px solid #ddd;
    padding:2px 10px;border-radius:4px;">■ Precio intermedio</span>
</div>"""

    sections = "".join(
        _store_section(sid, pids, by_product, global_ranked)
        for sid, pids in sorted(by_store.items(), key=lambda x: -len(x[1]))
    )

    footer = (f'<div style="text-align:center;font-size:12px;color:#aaa;'
              f'margin-top:24px;padding:16px 0;border-top:1px solid #eee;">'
              f'SOS Price Hunter · {today} · precios sujetos a cambios</div>')

    return f"""<!DOCTYPE html>
<html lang="es">
<head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SOS Price Hunter — {today}</title>
</head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
  max-width:720px;margin:0 auto;padding:20px;background:#f5f5f5;color:#1a1a1a;">
{header}{legend}{sections}{footer}
</body></html>"""


def send_email(html: str, subject: str):
    url = os.environ.get("APPS_SCRIPT_URL")
    if not url:
        log.warning("APPS_SCRIPT_URL no configurada — omitiendo email.")
        return
    try:
        resp = requests.post(url, json={"subject": subject, "html": html},
                             timeout=30, allow_redirects=True)
        resp.raise_for_status()
        try:
            r = resp.json()
            log.info(f"✓ Email: {r.get('status','?')}")
        except Exception:
            log.info(f"✓ Apps Script HTTP {resp.status_code}")
    except Exception as e:
        log.error(f"Error enviando email: {e}"); raise


def generate(comparison_path: str, output_dir: str = "reports") -> str:
    with open(comparison_path, encoding="utf-8") as f:
        comparison = json.load(f)
    html     = build_html(comparison)
    Path(output_dir).mkdir(exist_ok=True)
    out_file = Path(output_dir) / f"report_{comparison['date']}.html"
    out_file.write_text(html, encoding="utf-8")
    log.info(f"HTML: {out_file}")
    send_email(html, (
        f"🛒 SOS Price Hunter — {comparison['date']} | "
        f"Ahorro est: ${comparison.get('total_savings_estimate',0):,.0f} COP"))
    return str(out_file)


if __name__ == "__main__":
    import sys
    generate(sys.argv[1] if len(sys.argv) > 1 else "data/comparison_latest.json")
