"""
Base scraper — todos los scrapers de tienda heredan de esta clase.
Añadir una tienda nueva = crear scrapers/scraper_nueva_tienda.py
y heredar de BaseScraper.
"""

import json
import logging
import time
import random
from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict
from typing import Optional
from datetime import date

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s — %(message)s"
)


@dataclass
class PriceResult:
    """Un resultado de precio para un producto en una tienda."""
    store: str                   # "d1", "ara", "alkosto", "makro"
    product_id: str              # coincide con my_products.json
    product_name: str            # nombre tal como aparece en la tienda
    price: float                 # precio en COP
    unit: str                    # "und", "kg", "L", "g"
    quantity: float              # cantidad en la unidad declarada (ej. 5 para 5kg)
    price_per_100g: Optional[float] = None   # normalizado — se calcula en comparador.py
    price_per_liter: Optional[float] = None
    url: str = ""
    date: str = str(date.today())
    in_stock: bool = True
    discount_pct: float = 0.0
    original_price: Optional[float] = None

    def to_dict(self):
        return asdict(self)


class BaseScraper(ABC):
    """Clase base para todos los scrapers de tienda."""

    STORE_NAME: str = ""          # subclase debe definir esto
    BASE_URL: str = ""

    # Headers realistas para evitar bloqueos simples
    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "es-CO,es;q=0.9,en;q=0.8",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.results: list[PriceResult] = []

    def _sleep(self, min_s: float = 1.5, max_s: float = 3.5):
        """Pausa aleatoria entre requests para no gatillar rate limiting."""
        time.sleep(random.uniform(min_s, max_s))

    @abstractmethod
    def search_product(self, product: dict) -> list[PriceResult]:
        """
        Busca un producto en la tienda y retorna resultados normalizados.
        Recibe el dict de producto tal como está en my_products.json.
        """
        raise NotImplementedError

    def scrape_all(self, products: list[dict]) -> list[PriceResult]:
        """Itera por todos los productos y agrega resultados."""
        self.results = []
        total = len(products)
        for i, product in enumerate(products, 1):
            self.logger.info(
                f"[{i}/{total}] Buscando '{product['name']}' en {self.STORE_NAME}..."
            )
            try:
                found = self.search_product(product)
                self.results.extend(found)
                self.logger.info(
                    f"  → {len(found)} resultado(s) encontrado(s)"
                )
            except Exception as e:
                self.logger.warning(
                    f"  → Error buscando '{product['name']}': {e}"
                )
            self._sleep()
        return self.results

    def save_results(self, output_path: str):
        data = {
            "store": self.STORE_NAME,
            "scraped_at": str(date.today()),
            "count": len(self.results),
            "results": [r.to_dict() for r in self.results]
        }
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        self.logger.info(
            f"Guardados {len(self.results)} resultados en {output_path}"
        )
