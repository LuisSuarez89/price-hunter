"""
comparador.py — núcleo del sistema.

Lee los resultados de todos los scrapers, normaliza precios por
unidad real (precio/100g, precio/L, precio/und) y determina
qué tienda tiene el mejor precio para cada producto de la canasta.
"""

import json
import os
import re
import logging
from datetime import date
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [comparador] %(levelname)s — %(message)s"
)
log = logging.getLogger("comparador")

# ── Reglas de normalización por producto ─────────────────────────────────────
# Para cada product_id define cómo extraer cantidad real del nombre del producto.
# Si no hay regla, se usa la qty del propio resultado.

QUANTITY_HINTS = {
    "arroz_blanco":      {"factor": 1000, "unit_out": "g",  "divisor": 100},
    "azucar":            {"factor": 1000, "unit_out": "g",  "divisor": 100},
    "aceite_vegetal":    {"factor": 1000, "unit_out": "ml", "divisor": 1000},
    "cafe_granulado":    {"factor": 1,    "unit_out": "g",  "divisor": 100},
    "detergente_liquido":{"factor": 1000, "unit_out": "ml", "divisor": 1000},
    "desinfectante":     {"factor": 1000, "unit_out": "ml", "divisor": 1000},
    "lenteja":           {"factor": 500,  "unit_out": "g",  "divisor": 100},
    "frijol":            {"factor": 500,  "unit_out": "g",  "divisor": 100},
    "pasta_spaghetti":   {"factor": 400,  "unit_out": "g",  "divisor": 100},
    "pan_tajado":        {"factor": 550,  "unit_out": "g",  "divisor": 100},
}

# Patrones para extraer gramaje del nombre del producto
WEIGHT_PATTERNS = [
    (r"(\d+[\.,]?\d*)\s*kg", lambda m: float(m.replace(",", ".")) * 1000),
    (r"(\d+[\.,]?\d*)\s*g\b", lambda m: float(m.replace(",", "."))),
    (r"(\d+[\.,]?\d*)\s*[Ll]\b", lambda m: float(m.replace(",", ".")) * 1000),
    (r"(\d+[\.,]?\d*)\s*ml", lambda m: float(m.replace(",", "."))),
    (r"x(\d+)\s*(?:und|u\b)", lambda m: float(m)),
]


def extract_grams_from_name(name: str) -> float | None:
    """Intenta extraer gramos totales del nombre del producto."""
    name_lower = name.lower()
    for pattern, converter in WEIGHT_PATTERNS:
        m = re.search(pattern, name_lower)
        if m:
            try:
                return converter(m.group(1))
            except Exception:
                continue
    return None


def normalize_price(result: dict, product_def: dict) -> dict:
    """
    Añade precio normalizado al resultado.
    Retorna el mismo dict enriquecido con 'price_per_unit' y 'unit_label'.
    """
    price = result["price"]
    name = result["product_name"]
    pid = result["product_id"]

    grams = extract_grams_from_name(name)
    hint = QUANTITY_HINTS.get(pid, {})

    if hint:
        grams = grams or hint["factor"]
        divisor = hint["divisor"]
        unit_label = f"/{divisor}{hint['unit_out']}"
        price_per_unit = round(price / grams * divisor, 1)
    elif grams:
        # precio/100g genérico
        price_per_unit = round(price / grams * 100, 1)
        unit_label = "/100g"
    else:
        # No se puede normalizar — usar precio absoluto
        price_per_unit = price
        unit_label = f"/{result.get('unit', 'und')}"

    result["price_per_unit"] = price_per_unit
    result["unit_label"] = unit_label
    return result


def load_all_results(results_dir: str) -> list[dict]:
    """Carga todos los archivos JSON de resultados de scrapers."""
    all_results = []
    p = Path(results_dir)
    for f in p.glob("*.json"):
        try:
            with open(f, encoding="utf-8") as fp:
                data = json.load(fp)
            all_results.extend(data.get("results", []))
            log.info(f"Cargado {f.name}: {len(data.get('results', []))} resultados")
        except Exception as e:
            log.warning(f"Error leyendo {f.name}: {e}")
    return all_results


def compare(results_dir: str, products_path: str) -> dict:
    """
    Función principal.
    Retorna un dict con la estructura para el reporte:
    {
      "date": "...",
      "by_product": {
        product_id: {
          "product": {...},
          "winner": {...},       # mejor precio
          "all_prices": [...]    # todos los precios ordenados
        }
      },
      "by_store": {
        "d1":      [product_ids donde D1 gana],
        "alkosto": [...],
        ...
      }
    }
    """
    # Cargar definiciones de productos
    with open(products_path, encoding="utf-8") as f:
        products_data = json.load(f)
    products = {p["id"]: p for p in products_data["products"]}

    # Cargar y normalizar resultados
    raw_results = load_all_results(results_dir)
    for r in raw_results:
        pid = r.get("product_id", "")
        product_def = products.get(pid, {})
        normalize_price(r, product_def)

    # Agrupar por producto
    by_product = {}
    for r in raw_results:
        pid = r["product_id"]
        if pid not in by_product:
            by_product[pid] = {
                "product": products.get(pid, {"id": pid, "name": pid}),
                "prices": []
            }
        by_product[pid]["prices"].append(r)

    # Determinar ganador por producto
    result_by_product = {}
    result_by_store: dict[str, list] = {}

    for pid, data in by_product.items():
        prices = sorted(
            [p for p in data["prices"] if p["price"] > 0],
            key=lambda x: x["price_per_unit"]
        )
        if not prices:
            continue

        winner = prices[0]
        store = winner["store"]

        result_by_product[pid] = {
            "product": data["product"],
            "winner": winner,
            "all_prices": prices,
            "savings_vs_worst": (
                round(prices[-1]["price"] - prices[0]["price"], 0)
                if len(prices) > 1 else 0
            )
        }

        if store not in result_by_store:
            result_by_store[store] = []
        result_by_store[store].append(pid)

    # Calcular ahorro total estimado
    total_savings = sum(
        v["savings_vs_worst"]
        for v in result_by_product.values()
        if v["savings_vs_worst"] > 0
    )

    return {
        "date": str(date.today()),
        "by_product": result_by_product,
        "by_store": result_by_store,
        "total_savings_estimate": total_savings,
        "products_compared": len(result_by_product),
        "stores_found": list(result_by_store.keys()),
    }


if __name__ == "__main__":
    import sys
    results_dir = sys.argv[1] if len(sys.argv) > 1 else "data/raw"
    products_path = sys.argv[2] if len(sys.argv) > 2 else "data/my_products.json"

    report_data = compare(results_dir, products_path)

    out_path = f"data/comparison_{date.today()}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report_data, f, ensure_ascii=False, indent=2)

    log.info(f"Comparación guardada en {out_path}")
    log.info(
        f"Ahorro estimado comprando siempre al mejor precio: "
        f"${report_data['total_savings_estimate']:,.0f}"
    )
