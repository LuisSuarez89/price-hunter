"""
report_generator.py — genera el reporte HTML y lo envía por email.

El envío se hace via Google Apps Script Web App (mismo patrón que SOS Job Hunter):
Python hace POST con el HTML → Apps Script llama GmailApp.sendEmail().
No se necesita SMTP ni App Password.

Secret requerido en GitHub Actions: APPS_SCRIPT_URL
"""

import json
import os
import logging
import requests
from datetime import date
from pathlib import Path

log = logging.getLogger("report_generator")

STORE_LABELS = {
    "d1":      {"name": "D1",      "color": "#E53935", "emoji": "🔴"},
    "ara":     {"name": "Ara",     "color": "#F57C00", "emoji": "🟠"},
    "alkosto": {"name": "Alkosto", "color": "#1565C0", "emoji": "🔵"},
    "makro":   {"name": "Makro",   "color": "#2E7D32", "emoji": "🟢"},
    "manual":  {"name": "Manual",  "color": "#6A1B9A", "emoji": "🟣"},
}

CATEGORY_LABELS = {
    "carnes":       "Carnes y proteínas",
    "lacteos_huevos": "Lácteos y huevos",
    "despensa":     "Despensa y granos",
    "aseo_hogar":   "Aseo del hogar",
    "aseo_personal":"Aseo personal",
}


def build_html(comparison: dict) -> str:
    today = comparison["date"]
    by_store = comparison["by_store"]
    by_product = comparison["by_product"]
    savings = comparison.get("total_savings_estimate", 0)
    n_products = comparison.get("products_compared", 0)

    # ── Sección resumen de KPIs ───────────────────────────────────────────────
    store_counts = {
        STORE_LABELS.get(s, {}).get("name", s): len(pids)
        for s, pids in by_store.items()
    }
    store_summary_html = "".join(
        f'<span style="display:inline-block;margin:4px 6px;padding:6px 14px;'
        f'border-radius:20px;background:{STORE_LABELS.get(s,{}).get("color","#555")};'
        f'color:#fff;font-size:13px;font-weight:500;">'
        f'{STORE_LABELS.get(s,{}).get("emoji","")} '
        f'{STORE_LABELS.get(s,{}).get("name",s)}: {len(pids)} productos</span>'
        for s, pids in by_store.items()
    )

    # ── Sección por tienda (el corazón del reporte) ───────────────────────────
    by_store_html = ""
    for store_id, product_ids in sorted(by_store.items(), key=lambda x: -len(x[1])):
        meta = STORE_LABELS.get(store_id, {"name": store_id, "color": "#555", "emoji": ""})
        rows_html = ""

        # Agrupar por categoría dentro de cada tienda
        by_cat: dict[str, list] = {}
        for pid in product_ids:
            entry = by_product.get(pid)
            if not entry:
                continue
            cat = entry["product"].get("category", "otros")
            by_cat.setdefault(cat, []).append(entry)

        for cat, entries in by_cat.items():
            cat_label = CATEGORY_LABELS.get(cat, cat.capitalize())
            rows_html += (
                f'<tr><td colspan="4" style="padding:10px 12px 4px;'
                f'font-size:11px;font-weight:600;color:#888;'
                f'text-transform:uppercase;letter-spacing:.5px;">'
                f'{cat_label}</td></tr>'
            )
            for entry in entries:
                winner = entry["winner"]
                prod = entry["product"]
                savings_item = entry.get("savings_vs_worst", 0)
                savings_badge = ""
                if savings_item > 0:
                    savings_badge = (
                        f'<span style="margin-left:8px;padding:2px 8px;'
                        f'border-radius:10px;background:#E8F5E9;color:#2E7D32;'
                        f'font-size:11px;">ahorras ${savings_item:,.0f}</span>'
                    )

                all_prices_html = ""
                for pr in entry.get("all_prices", [])[1:]:
                    other_store = STORE_LABELS.get(pr["store"], {}).get("name", pr["store"])
                    all_prices_html += (
                        f'<span style="font-size:11px;color:#999;margin-left:8px;">'
                        f'{other_store}: ${pr["price"]:,.0f}</span>'
                    )

                url = winner.get("url", "")
                name_html = (
                    f'<a href="{url}" style="color:inherit;text-decoration:none;">'
                    f'{winner["product_name"]}</a>'
                    if url and url != "manual"
                    else winner["product_name"]
                )

                note = prod.get("note", "")
                note_html = (
                    f'<div style="font-size:11px;color:#aaa;margin-top:2px;">'
                    f'{note}</div>'
                    if note else ""
                )

                rows_html += f"""
                <tr style="border-bottom:1px solid #f0f0f0;">
                  <td style="padding:10px 12px;font-size:14px;">
                    {name_html}
                    {note_html}
                    {savings_badge}
                    {all_prices_html}
                  </td>
                  <td style="padding:10px 12px;font-size:13px;color:#555;white-space:nowrap;">
                    {winner.get('unit_label','')}</td>
                  <td style="padding:10px 12px;font-size:14px;font-weight:600;
                    color:{meta['color']};white-space:nowrap;">
                    ${winner['price']:,.0f}</td>
                  <td style="padding:10px 12px;font-size:12px;color:#aaa;white-space:nowrap;">
                    ${winner['price_per_unit']:,.1f}{winner.get('unit_label','')}</td>
                </tr>"""

        by_store_html += f"""
        <div style="margin-bottom:28px;border-radius:12px;overflow:hidden;
          border:1.5px solid {meta['color']}22;box-shadow:0 2px 8px #0001;">
          <div style="background:{meta['color']};color:#fff;padding:14px 18px;
            display:flex;align-items:center;gap:10px;">
            <span style="font-size:20px;">{meta['emoji']}</span>
            <div>
              <div style="font-size:17px;font-weight:600;">{meta['name']}</div>
              <div style="font-size:12px;opacity:.85;">
                {len(product_ids)} productos al mejor precio este mes</div>
            </div>
          </div>
          <table style="width:100%;border-collapse:collapse;background:#fff;">
            <thead>
              <tr style="background:#fafafa;">
                <th style="padding:8px 12px;text-align:left;font-size:12px;color:#888;
                  font-weight:500;border-bottom:1px solid #eee;">Producto</th>
                <th style="padding:8px 12px;text-align:left;font-size:12px;color:#888;
                  font-weight:500;border-bottom:1px solid #eee;">Unidad</th>
                <th style="padding:8px 12px;text-align:left;font-size:12px;color:#888;
                  font-weight:500;border-bottom:1px solid #eee;">Precio</th>
                <th style="padding:8px 12px;text-align:left;font-size:12px;color:#888;
                  font-weight:500;border-bottom:1px solid #eee;">Normalizado</th>
              </tr>
            </thead>
            <tbody>{rows_html}</tbody>
          </table>
        </div>"""

    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SOS Price Hunter — {today}</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    max-width: 680px; margin: 0 auto; padding: 20px; background: #f5f5f5; color: #1a1a1a; }}
  @media (prefers-color-scheme: dark) {{
    body {{ background: #121212; color: #e0e0e0; }}
    table {{ background: #1e1e1e !important; }}
    thead tr {{ background: #252525 !important; }}
  }}
</style>
</head>
<body>

<div style="background:linear-gradient(135deg,#1a237e,#283593);
  color:#fff;border-radius:16px;padding:24px;margin-bottom:24px;">
  <div style="font-size:22px;font-weight:700;margin-bottom:4px;">
    🛒 SOS Price Hunter
  </div>
  <div style="font-size:14px;opacity:.8;">Reporte mensual — {today}</div>
  <div style="margin-top:16px;display:flex;gap:16px;flex-wrap:wrap;">
    <div style="background:rgba(255,255,255,.15);border-radius:10px;
      padding:12px 20px;text-align:center;">
      <div style="font-size:22px;font-weight:700;">{n_products}</div>
      <div style="font-size:11px;opacity:.8;">productos comparados</div>
    </div>
    <div style="background:rgba(255,255,255,.15);border-radius:10px;
      padding:12px 20px;text-align:center;">
      <div style="font-size:22px;font-weight:700;">{len(by_store)}</div>
      <div style="font-size:11px;opacity:.8;">tiendas revisadas</div>
    </div>
    <div style="background:rgba(76,175,80,.4);border-radius:10px;
      padding:12px 20px;text-align:center;">
      <div style="font-size:22px;font-weight:700;">${savings:,.0f}</div>
      <div style="font-size:11px;opacity:.8;">ahorro potencial estimado</div>
    </div>
  </div>
</div>

<div style="background:#fff;border-radius:12px;padding:18px;margin-bottom:24px;
  border:1px solid #e0e0e0;">
  <div style="font-size:13px;font-weight:600;color:#555;margin-bottom:10px;">
    DÓNDE COMPRAR ESTE MES
  </div>
  {store_summary_html}
</div>

{by_store_html}

<div style="text-align:center;font-size:12px;color:#aaa;margin-top:24px;padding-bottom:16px;">
  Generado automáticamente por SOS Price Hunter · {today}<br>
  Precios sujetos a cambios — verificar en tienda antes de ir
</div>

</body>
</html>"""

    return html


def send_email(html: str, subject: str):
    """
    Envía el reporte vía Google Apps Script Web App.

    El script de Apps Script recibe un POST con JSON:
      { "subject": "...", "html": "..." }
    y usa GmailApp.sendEmail() para despachar el correo.

    Secret requerido en GitHub Actions: APPS_SCRIPT_URL
    (la URL de deployment del Web App de Apps Script)
    """
    apps_script_url = os.environ.get("APPS_SCRIPT_URL")

    if not apps_script_url:
        log.warning(
            "Variable de entorno APPS_SCRIPT_URL no configurada — "
            "omitiendo envío de email. "
            "Agrega el secret en GitHub → Settings → Secrets → APPS_SCRIPT_URL"
        )
        return

    payload = {
        "subject": subject,
        "html":    html,
    }

    try:
        log.info("Enviando reporte via Apps Script...")
        resp = requests.post(
            apps_script_url,
            json=payload,
            timeout=30,
            # Apps Script redirige el POST — hay que seguir el redirect
            allow_redirects=True,
        )
        resp.raise_for_status()

        # Apps Script devuelve JSON con status
        try:
            result = resp.json()
            if result.get("status") == "ok":
                log.info(f"✓ Email enviado correctamente via Apps Script")
            else:
                log.warning(f"Apps Script respondió: {result}")
        except Exception:
            # Si no devuelve JSON válido pero el status HTTP fue 200, igual funcionó
            log.info(f"✓ Apps Script respondió HTTP {resp.status_code}")

    except requests.exceptions.Timeout:
        log.error("Timeout esperando respuesta de Apps Script (>30s)")
        raise
    except requests.exceptions.RequestException as e:
        log.error(f"Error llamando Apps Script: {e}")
        raise


def generate(comparison_path: str, output_dir: str = "reports"):
    with open(comparison_path, encoding="utf-8") as f:
        comparison = json.load(f)

    html = build_html(comparison)

    Path(output_dir).mkdir(exist_ok=True)
    out_file = Path(output_dir) / f"report_{comparison['date']}.html"
    out_file.write_text(html, encoding="utf-8")
    log.info(f"Reporte HTML guardado: {out_file}")

    subject = (
        f"🛒 SOS Price Hunter — {comparison['date']} | "
        f"Ahorro estimado: ${comparison.get('total_savings_estimate', 0):,.0f}"
    )
    send_email(html, subject)

    return str(out_file)


if __name__ == "__main__":
    import sys
    comparison_path = sys.argv[1] if len(sys.argv) > 1 else "data/comparison_latest.json"
    generate(comparison_path)
