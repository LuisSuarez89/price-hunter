"""
Scraper para tiendas Ara (ara.com.co).
Ara tiene ecommerce activo con búsqueda por URL.
"""

import requests
import re
import json
from bs4 import BeautifulSoup
from scrapers.base_scraper import BaseScraper, PriceResult


class AraScraper(BaseScraper):

    STORE_NAME = "ara"
    BASE_URL = "https://www.ara.com.co"
    SEARCH_URL = "https://www.ara.com.co/search?q={query}"

    def search_product(self, product: dict) -> list[PriceResult]:
        results = []

        for term in product.get("search_terms", [product["name"]]):
            try:
                url = self.SEARCH_URL.format(
                    query=requests.utils.quote(term)
                )
                resp = requests.get(
                    url, headers=self.HEADERS, timeout=12
                )
                if resp.status_code != 200:
                    self._sleep()
                    continue

                soup = BeautifulSoup(resp.text, "html.parser")

                # Ara usa Vtex — estructura típica de ese ecommerce
                cards = soup.select(
                    ".product-summary, [class*='productSummary'], "
                    ".shelf-item, [data-product-summary]"
                )

                for card in cards[:3]:
                    name_el = card.select_one(
                        ".product-summary-name, "
                        "[class*='productName'], "
                        "h3, h2"
                    )
                    # Precio con descuento primero, luego precio normal
                    price_el = card.select_one(
                        ".product-selling-price, "
                        "[class*='sellingPrice'], "
                        "[class*='spotPrice'], "
                        ".price"
                    )
                    original_el = card.select_one(
                        ".product-list-price, "
                        "[class*='listPrice']"
                    )

                    if not name_el or not price_el:
                        continue

                    price = self._parse_price(price_el.get_text(strip=True))
                    if not price:
                        continue

                    original = None
                    discount_pct = 0.0
                    if original_el:
                        original = self._parse_price(
                            original_el.get_text(strip=True)
                        )
                        if original and original > price:
                            discount_pct = round(
                                (1 - price / original) * 100, 1
                            )

                    link_el = card.select_one("a[href]")
                    url_prod = ""
                    if link_el:
                        href = link_el.get("href", "")
                        url_prod = (
                            href if href.startswith("http")
                            else self.BASE_URL + href
                        )

                    results.append(PriceResult(
                        store=self.STORE_NAME,
                        product_id=product["id"],
                        product_name=name_el.get_text(strip=True),
                        price=price,
                        unit=product.get("unit", "und"),
                        quantity=product.get("typical_qty", 1),
                        url=url_prod,
                        discount_pct=discount_pct,
                        original_price=original,
                    ))

                if results:
                    break

                self._sleep()

            except requests.RequestException as e:
                self.logger.warning(f"Error de red en Ara para '{term}': {e}")

        return results

    def _parse_price(self, text: str) -> float:
        cleaned = re.sub(r"[^\d]", "", text)
        return float(cleaned) if cleaned else 0.0
