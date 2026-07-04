"""
main.py — punto de entrada del pipeline SOS Price Hunter.

Uso:
  python main.py                        # corre todos los scrapers
  python main.py --stores d1,alkosto    # solo tiendas específicas
  python main.py --skip-scraping        # solo comparar con datos existentes
"""

import argparse
import json
import logging
import os
from datetime import date
from pathlib import Path

from scrapers.scraper_d1 import D1Scraper
from scrapers.scraper_ara import AraScraper
from scrapers.scraper_alkosto import AlkostoScraper
from scrapers.scraper_makro import MakroScraper
from comparador import compare
from report_generator import generate

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [main] %(levelname)s — %(message)s"
)
log = logging.getLogger("main")

SCRAPERS = {
    "d1":      D1Scraper,
    "ara":     AraScraper,
    "alkosto": AlkostoScraper,
    "makro":   MakroScraper,
}

PRODUCTS_PATH = "data/my_products.json"
RAW_DIR = Path("data/raw")
COMPARISON_PATH = f"data/comparison_{date.today()}.json"
REPORTS_DIR = "reports"


def run_scrapers(stores: list[str]):
    """Ejecuta los scrapers para las tiendas indicadas."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    with open(PRODUCTS_PATH, encoding="utf-8") as f:
        products = json.load(f)["products"]

    for store_id in stores:
        scraper_cls = SCRAPERS.get(store_id)
        if not scraper_cls:
            log.warning(f"Tienda '{store_id}' no tiene scraper — omitiendo.")
            continue

        log.info(f"━━━ Scraping {store_id.upper()} ({len(products)} productos) ━━━")
        scraper = scraper_cls()
        scraper.scrape_all(products)

        out_path = str(RAW_DIR / f"{store_id}_{date.today()}.json")
        scraper.save_results(out_path)
        log.info(f"✓ {store_id}: {len(scraper.results)} resultados guardados")


def run_comparison():
    """Compara precios y guarda el JSON de comparación."""
    log.info("━━━ Comparando precios ━━━")
    comparison = compare(str(RAW_DIR), PRODUCTS_PATH)

    with open(COMPARISON_PATH, "w", encoding="utf-8") as f:
        json.dump(comparison, f, ensure_ascii=False, indent=2)

    log.info(
        f"✓ Comparación: {comparison['products_compared']} productos, "
        f"ahorro estimado ${comparison['total_savings_estimate']:,.0f}"
    )
    return comparison


def run_report():
    """Genera el reporte HTML y envía el email."""
    log.info("━━━ Generando reporte ━━━")
    out = generate(COMPARISON_PATH, REPORTS_DIR)
    log.info(f"✓ Reporte generado: {out}")


def main():
    parser = argparse.ArgumentParser(description="SOS Price Hunter pipeline")
    parser.add_argument(
        "--stores",
        default=",".join(SCRAPERS.keys()),
        help="Tiendas a scrapear separadas por coma (default: todas)"
    )
    parser.add_argument(
        "--skip-scraping",
        action="store_true",
        help="Omite scraping y usa datos crudos existentes"
    )
    parser.add_argument(
        "--skip-email",
        action="store_true",
        help="Genera el HTML pero no envía email"
    )
    args = parser.parse_args()

    stores = [s.strip() for s in args.stores.split(",") if s.strip()]

    if args.skip_email:
        # Eliminar la URL de Apps Script para que report_generator omita el envío
        os.environ.pop("APPS_SCRIPT_URL", None)

    if not args.skip_scraping:
        run_scrapers(stores)
    else:
        log.info("Omitiendo scraping — usando datos existentes en data/raw/")

    run_comparison()
    run_report()
    log.info("━━━ Pipeline completado ━━━")


if __name__ == "__main__":
    main()
