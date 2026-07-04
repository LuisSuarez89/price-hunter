"""
Scraper para Tiendas D1.
D1 no tiene ecommerce público, pero sí tiene catálogo en su app/web.
Este módulo usa requests + BeautifulSoup sobre el sitio público de D1.

NOTA: Si D1 bloquea el scraping directo, hay un fallback a modo
'manual_prices' donde puedes ingresar precios a mano en data/manual_d1.json.
"""

import requests
from bs4 import BeautifulSoup
from scrapers.base_scraper import BaseScraper, PriceResult
import json
import os
import re


class D1Scraper(BaseScraper):

    STORE_NAME = "d1"
    BASE_URL = "https://www.d1.com.co"
    SEARCH_URL = "https://www.d1.com.co/buscar?q={query}"

    def search_product(self, product: dict) -> list[PriceResult]:
        results = []

        # Intentar con cada término de búsqueda hasta encontrar algo
        for term in product.get("search_terms", [product["name"]]):
            try:
                url = self.SEARCH_URL.format(query=requests.utils.quote(term))
                resp = requests.get(url, headers=self.HEADERS, timeout=12)
                if resp.status_code != 200:
                    self.logger.warning(
                        f"D1 respondió {resp.status_code} para '{term}'"
                    )
                    continue

                soup = BeautifulSoup(resp.text, "html.parser")

                # Selector de tarjetas de producto — ajustar si D1 cambia su HTML
                cards = soup.select(".product-card, .product-item, [data-product-id]")

                for card in cards[:3]:  # tomar máximo 3 resultados por término
                    name_el = card.select_one(
                        ".product-name, .product-title, h3, h2"
                    )
                    price_el = card.select_one(
                        ".product-price, .price, [class*='price']"
                    )
                    if not name_el or not price_el:
                        continue

                    price_text = price_el.get_text(strip=True)
                    price = self._parse_price(price_text)
                    if not price:
                        continue

                    link_el = card.select_one("a[href]")
                    url_prod = self.BASE_URL + link_el["href"] if link_el else ""

                    results.append(PriceResult(
                        store=self.STORE_NAME,
                        product_id=product["id"],
                        product_name=name_el.get_text(strip=True),
                        price=price,
                        unit=product.get("unit", "und"),
                        quantity=product.get("typical_qty", 1),
                        url=url_prod,
                    ))

                if results:
                    break  # ya encontramos algo, no seguir buscando

            except requests.RequestException as e:
                self.logger.warning(f"Error de red buscando en D1: {e}")

        # Fallback a precios manuales si no encontramos nada online
        if not results:
            results = self._fallback_manual(product)

        return results

    def _parse_price(self, text: str) -> float:
        """Extrae el número de un texto tipo '$12.900' o '12900'."""
        cleaned = re.sub(r"[^\d]", "", text)
        return float(cleaned) if cleaned else 0.0

    def _fallback_manual(self, product: dict) -> list[PriceResult]:
        """
        Lee precios desde data/manual_d1.json si el scraping falla.
        Formato del archivo:
        { "salmon_filete": {"price": 21950, "name": "Filetes de salmón D1"}, ... }
        """
        manual_path = os.path.join(
            os.path.dirname(__file__), "..", "data", "manual_d1.json"
        )
        if not os.path.exists(manual_path):
            return []

        try:
            with open(manual_path, encoding="utf-8") as f:
                manual = json.load(f)

            entry = manual.get(product["id"])
            if entry:
                self.logger.info(
                    f"  → Usando precio manual para '{product['id']}' en D1"
                )
                return [PriceResult(
                    store=self.STORE_NAME,
                    product_id=product["id"],
                    product_name=entry.get("name", product["name"]),
                    price=entry["price"],
                    unit=product.get("unit", "und"),
                    quantity=product.get("typical_qty", 1),
                    url="manual",
                )]
        except Exception as e:
            self.logger.warning(f"Error leyendo manual_d1.json: {e}")

        return []
