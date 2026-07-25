"""
report_generator.py
Genera el reporte HTML + PDF adjunto y envía ambos via Apps Script.

Flujo:
  1. build_html(comparison)       → str   (email body)
  2. generate_pdf(comparison)     → bytes (adjunto)
  3. send_email(html, pdf_bytes)  → POST al Apps Script con:
       { "subject": "...", "html": "...", "pdf_b64": "...", "pdf_filename": "..." }
  4. Apps Script usa GmailApp.sendEmail con el adjunto decodificado.
"""

import base64
import json
import logging
import os
import requests
from datetime import date
from pathlib import Path

from pdf_generator import generate_pdf

log = logging.getLogger("report_generator")

STORE_META = {
    "d1":      {"name":"D1",       "color":"#C62828","emoji":"🔴"},
    "ara":     {"name":"Ara",      "color":"#E65100","emoji":"🟠"},
    "alkosto": {"name":"Alkosto",  "color":"#1565C0","emoji":"🔵"},
    "makro":   {"name":"Makro",    "color":"#2E7D32","emoji":"🟢"},
    "olimpica":{"name":"Olímpica", "color":"#6A1B9A","emoji":"🟣"},
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


# ── Colores por ranking ───────────────────────────────────────────────────────
def _rank_color(ppu: float, ranked: list) -> tuple:
    if not ranked or ppu <= 0:
        return C_MID, T_MID, ""
    ppus  = [r.get("price_per_unit", 0) for r in ranked]
    best  = min(ppus); worst = max(ppus); n = len(ppus)
    if n > 1 and abs(ppu - best)  / (best  + 0.01) < 0.005:
        return C_BEST,  T_BEST, ('<span style="background:#2E7D32;color:#fff;padding:2px 8px;'
                                  'border-radius:10px;font-size:11px;font-weight:700;">✓ MEJOR</span>')
    if n > 1 and abs(ppu - worst) / (worst + 0.01) < 0.005:
        return C_WORST, T_WORST,('<span style="background:#C62828;color:#fff;padding:2px 8px;'
                                  'border-radius:10px;font-size:11px;font-weight:700;">↑ MÁS CARO</span>')
    pos = sorted(set(ppus)).index(min(ppus, key=lambda x: abs(x - ppu))) + 1
    return C_MID, T_MID, (f'<span style="background:#e0e0e0;color:#555;padding:2px 8px;'
                           f'border-radius:10px;font-size:11px;">#{pos}/{n}</span>')


# ── Sección HTML de una tienda ────────────────────────────────────────────────
def _store_section(store_id, pids, by_product, global_ranked):
    m = STORE_META.get(store_id, {"name": store_id, "color": "#555", "emoji": ""})
    by_cat: dict = {}
    for pid in pids:
        e = by_product.get(pid)
        if not e: continue
        cat = e["product"].get("category", "otros")
        by_cat.setdefault(cat, []).append((pid, e))

    rows = ""
    for cat, entries in by_cat.items():
        rows += (f'<tr><td colspan="6" style="padding:8px 10px 4px;font-size:10px;'
                 f'font-weight:700;color:#777;text-transform:uppercase;letter-spacing:.5px;'
                 f'background:#f8f8f8;">{CAT_LABELS.get(cat, cat.title())}</td></tr>')
        for pid, entry in entries:
            ranked = global_ranked.get(pid, [])
            store_prices = [p for p in entry.get("all_prices", []) if p.get("store") == store_id]
            if not store_prices:
                store_prices = [entry["winner"]] if entry.get("winner") else []
            for pr in store_prices:
                ppu  = pr.get("price_per_unit", 0)
                bg, tc, badge = _rank_color(ppu, ranked)
                disc = pr.get("discount_pct", 0)
                disc_badge = (f'<span style="margin-left:5px;padding:1px 6px;border-radius:8px;'
                              f'background:#E8F5E9;color:#2E7D32;font-size:10px;">-{disc:.0f}%</span>'
                              if disc else "")
                url  = pr.get("url", "")
                name = pr.get("product_name", entry["product"]["name"])
                name_html = (f'<a href="{url}" style="color:inherit;text-decoration:none;">{name}</a>'
                             if url and url not in ("manual","") else name)
                rows += f"""
<tr style="background:{bg};border-bottom:1px solid #f0f0f0;">
  <td style="padding:7px 10px;font-size:12px;color:{tc};">{name_html}{disc_badge}</td>
  <td style="padding:7px 10px;font-size:11px;color:#666;">{pr.get("brand","") or "—"}</td>
  <td style="padding:7px 10px;font-size:11px;color:#666;white-space:nowrap;">{pr.get("quantity_display","") or "—"}</td>
  <td style="padding:7px 10px;font-size:13px;font-weight:700;color:{tc};white-space:nowrap;">${pr.get("price",0):,.0f}</td>
  <td style="padding:7px 10px;font-size:11px;color:#888;white-space:nowrap;">{"${:,.1f}{}".format(ppu, pr.get("unit_label","")) if ppu else "—"}</td>
  <td style="padding:7px 10px;text-align:center;">{badge}</td>
</tr>"""

    return f"""
<div style="margin-bottom:24px;border-radius:10px;overflow:hidden;border:1px solid {m['color']}33;">
  <div style="background:{m['color']};color:#fff;padding:12px 16px;">
    <span style="font-size:16px;font-weight:600;">{m['emoji']} {m['name']}</span>
    <span style="font-size:11px;opacity:.8;margin-left:8px;">{len(pids)} productos al mejor precio</span>
  </div>
  <div style="overflow-x:auto;">
  <table style="width:100%;border-collapse:collapse;background:#fff;min-width:520px;">
    <thead><tr style="background:#fafafa;border-bottom:2px solid #eee;">
      <th style="padding:7px 10px;text-align:left;font-size:10px;color:#888;font-weight:600;text-transform:uppercase;">Producto</th>
      <th style="padding:7px 10px;text-align:left;font-size:10px;color:#888;font-weight:600;text-transform:uppercase;">Marca</th>
      <th style="padding:7px 10px;text-align:left;font-size:10px;color:#888;font-weight:600;text-transform:uppercase;">Presentación</th>
      <th style="padding:7px 10px;text-align:left;font-size:10px;color:#888;font-weight:600;text-transform:uppercase;">Precio</th>
      <th style="padding:7px 10px;text-align:left;font-size:10px;color:#888;font-weight:600;text-transform:uppercase;">Normalizado</th>
      <th style="padding:7px 10px;text-align:center;font-size:10px;color:#888;font-weight:600;text-transform:uppercase;">Ranking</th>
    </tr></thead>
    <tbody>{rows}</tbody>
  </table></div>
</div>"""


# ── HTML completo ─────────────────────────────────────────────────────────────
def build_html(comparison: dict) -> str:
    today      = comparison["date"]
    by_store   = comparison["by_store"]
    by_product = comparison["by_product"]
    savings    = comparison.get("total_savings_estimate", 0)
    n          = comparison.get("products_compared", 0)

    global_ranked = {
        pid: sorted([p for p in data.get("all_prices",[]) if p.get("price_per_unit",0)>0],
                    key=lambda x: x["price_per_unit"])
        for pid, data in by_product.items()
    }

    pills = "".join(
        f'<span style="display:inline-block;margin:4px 4px 4px 0;padding:4px 12px;'
        f'border-radius:20px;background:{STORE_META.get(s,{}).get("color","#555")};'
        f'color:#fff;font-size:12px;">'
        f'{STORE_META.get(s,{}).get("emoji","")} {STORE_META.get(s,{}).get("name",s)}: {len(pids)}</span>'
        for s, pids in sorted(by_store.items(), key=lambda x: -len(x[1]))
    )
    sections = "".join(
        _store_section(sid, pids, by_product, global_ranked)
        for sid, pids in sorted(by_store.items(), key=lambda x: -len(x[1]))
    )
    return f"""<!DOCTYPE html><html lang="es"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SOS Price Hunter — {today}</title></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
  max-width:700px;margin:0 auto;padding:20px;background:#f5f5f5;color:#1a1a1a;">
<div style="background:linear-gradient(135deg,#1a237e,#283593);color:#fff;
  border-radius:12px;padding:20px 24px;margin-bottom:20px;">
  <div style="font-size:20px;font-weight:700;margin-bottom:4px;">🛒 SOS Price Hunter</div>
  <div style="font-size:12px;opacity:.75;margin-bottom:14px;">{today}</div>
  <div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:14px;">
    <div style="background:rgba(255,255,255,.15);border-radius:8px;padding:8px 16px;text-align:center;">
      <div style="font-size:18px;font-weight:700;">{n}</div><div style="font-size:10px;opacity:.8;">productos</div></div>
    <div style="background:rgba(255,255,255,.15);border-radius:8px;padding:8px 16px;text-align:center;">
      <div style="font-size:18px;font-weight:700;">{len(by_store)}</div><div style="font-size:10px;opacity:.8;">tiendas</div></div>
    <div style="background:rgba(76,175,80,.45);border-radius:8px;padding:8px 16px;text-align:center;">
      <div style="font-size:18px;font-weight:700;">${savings:,.0f}</div><div style="font-size:10px;opacity:.8;">ahorro potencial</div></div>
  </div>
  <div>{pills}</div>
</div>
<div style="background:#f8f9fa;border:1px solid #e0e0e0;border-radius:8px;
  padding:10px 16px;margin-bottom:20px;font-size:12px;color:#555;">
  <b>Colores:</b>
  <span style="background:{C_BEST};color:{T_BEST};padding:1px 8px;border-radius:4px;font-weight:600;">■ Mejor precio</span>&nbsp;
  <span style="background:{C_WORST};color:{T_WORST};padding:1px 8px;border-radius:4px;font-weight:600;">■ Precio más alto</span>&nbsp;
  <span style="background:#fff;border:1px solid #ddd;padding:1px 8px;border-radius:4px;">■ Intermedio</span>
  &nbsp;— comparado por precio/100g o /L entre todas las tiendas.<br>
  <span style="color:#888;font-size:11px;margin-top:4px;display:block;">
    📎 Este email incluye el reporte completo como PDF adjunto.</span>
</div>
{sections}
<div style="text-align:center;font-size:11px;color:#aaa;margin-top:20px;
  padding-top:16px;border-top:1px solid #eee;">
  SOS Price Hunter · {today} · precios sujetos a cambios</div>
</body></html>"""


# ── Envío via Apps Script ─────────────────────────────────────────────────────
def send_email(html: str, subject: str, pdf_bytes: bytes, pdf_filename: str):
    """
    Envía el reporte por email vía Apps Script.
    El PDF se envía como base64 en el campo pdf_b64.
    Apps Script lo decodifica y adjunta con GmailApp.sendEmail.
    """
    url = os.environ.get("APPS_SCRIPT_URL")
    if not url:
        log.warning("APPS_SCRIPT_URL no configurada — omitiendo email.")
        return

    payload = {
        "subject":      subject,
        "html":         html,
        "pdf_b64":      base64.b64encode(pdf_bytes).decode("utf-8"),
        "pdf_filename": pdf_filename,
    }

    try:
        log.info(f"Enviando reporte ({len(pdf_bytes)//1024} KB PDF adjunto)...")
        resp = requests.post(url, json=payload, timeout=60, allow_redirects=True)
        resp.raise_for_status()
        try:
            r = resp.json()
            log.info(f"✓ Apps Script: {r.get('status','?')} — {r.get('message','')}")
        except Exception:
            log.info(f"✓ Apps Script HTTP {resp.status_code}")
    except requests.exceptions.Timeout:
        log.error("Timeout (>60s) — el PDF puede ser demasiado grande para Apps Script")
        raise
    except requests.exceptions.RequestException as e:
        log.error(f"Error enviando: {e}"); raise


# ── Punto de entrada ──────────────────────────────────────────────────────────
def generate(comparison_path: str, output_dir: str = "reports") -> str:
    with open(comparison_path, encoding="utf-8") as f:
        comparison = json.load(f)

    today = comparison["date"]
    Path(output_dir).mkdir(exist_ok=True)

    # HTML
    html     = build_html(comparison)
    out_html = Path(output_dir) / f"report_{today}.html"
    out_html.write_text(html, encoding="utf-8")
    log.info(f"HTML: {out_html}")

    # PDF
    log.info("Generando PDF...")
    pdf_bytes    = generate_pdf(comparison)
    pdf_filename = f"SOS_Price_Hunter_{today}.pdf"
    out_pdf      = Path(output_dir) / pdf_filename
    out_pdf.write_bytes(pdf_bytes)
    log.info(f"PDF: {out_pdf} ({len(pdf_bytes)//1024} KB)")

    # Email
    subject = (f"🛒 SOS Price Hunter — {today} | "
               f"Ahorro est: ${comparison.get('total_savings_estimate',0):,.0f} COP")
    send_email(html, subject, pdf_bytes, pdf_filename)

    return str(out_html)


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s — %(message)s")
    generate(sys.argv[1] if len(sys.argv) > 1 else "data/comparison_latest.json")
