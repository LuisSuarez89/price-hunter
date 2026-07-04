"""
Scraper para Makro Colombia (makro.com.co).
Makro tiene ecommerce activo. Al ser mayorista, sus precios
son por bulto/paquete mayor — el comparador normaliza a precio/unidad.
"""

import requests
import re
from bs4 import BeautifulSoup
from scrapers.base_scraper import BaseScraper, PriceResult


class MakroScraper(BaseScraper):

    STORE_NAME = "makro"
    BASE_URL = "https://www.makro.com.co"
    SEARCH_URL = "https://www.makro.com.co/catalogsearch/result/?q={query}"

    def search_product(self, product: dict) -> list[PriceResult]:
        results = []

        for term in product.get("search_terms", [product["name"]]):
            try:
                url = self.SEARCH_URL.format(
                    query=requests.utils.quote(term)
                )
                resp = requests.get(
                    url, headers=self.HEADERS, timeout=15
                )
                if resp.status_code != 200:
                    self._sleep()
                    continue

                soup = BeautifulSoup(resp.text, "html.parser")

                # Makro usa Magento 2 — selectores típicos de ese framework
                cards = soup.select(
                    ".product-item, "
                    "[class*='product-item'], "
                    ".item.product"
                )

                for card in cards[:3]:
                    name_el = card.select_one(
                        ".product-item-name, "
                        ".product-name, "
                        "strong.product-item-name, "
                        "h2, h3"
                    )
                    price_el = card.select_one(
                        ".price, "
                        "[data-price-type='finalPrice'] .price, "
                        ".special-price .price"
                    )

                    if not name_el or not price_el:
                        continue

                    price = self._parse_price(price_el.get_text(strip=True))
                    if not price:
                        continue

                    link_el = card.select_one("a.product-item-link, a[href]")
                    url_prod = ""
                    if link_el:
                        href = link_el.get("href", "")
                        url_prod = (
                            href if href.startswith("http")
                            else self.BASE_URL + href
                        )

                    # En Makro la cantidad suele estar en el nombre del producto
                    # Ej. "Arroz blanco x5kg" — el comparador lo normalizará
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
                    break

                self._sleep()

            except requests.RequestException as e:
                self.logger.warning(
                    f"Error de red en Makro para '{term}': {e}"
                )

        return results

    def _parse_price(self, text: str) -> float:
        cleaned = re.sub(r"[^\d]", "", text)
        return float(cleaned) if cleaned else 0.0
