"""
Scraper para Alkosto.
Alkosto tiene ecommerce activo en alkosto.com con API de búsqueda
accesible vía parámetros de URL — más confiable que parsear HTML.
"""

import requests
import re
from scrapers.base_scraper import BaseScraper, PriceResult


class AlkostoScraper(BaseScraper):

    STORE_NAME = "alkosto"
    BASE_URL = "https://www.alkosto.com"

    # Alkosto usa Algolia o similar como motor de búsqueda interno
    # La URL de búsqueda devuelve HTML con datos de producto en <script type="application/ld+json">
    SEARCH_URL = "https://www.alkosto.com/search?text={query}"

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
                    continue

                found = self._parse_ld_json(resp.text, product)
                results.extend(found)

                if results:
                    break

                self._sleep(1.0, 2.5)

            except requests.RequestException as e:
                self.logger.warning(
                    f"Error de red en Alkosto para '{term}': {e}"
                )

        return results[:3]

    def _parse_ld_json(self, html: str, product: dict) -> list[PriceResult]:
        """
        Alkosto incluye datos estructurados JSON-LD en los resultados.
        Es más estable que parsear CSS selectors.
        """
        import json
        from bs4 import BeautifulSoup

        results = []
        soup = BeautifulSoup(html, "html.parser")

        # Buscar bloques JSON-LD de tipo Product
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "")
            except Exception:
                continue

            items = data if isinstance(data, list) else [data]
            for item in items:
                if item.get("@type") not in ("Product", "ItemList"):
                    continue

                # Si es ItemList, expandir
                if item.get("@type") == "ItemList":
                    sub_items = item.get("itemListElement", [])
                    for si in sub_items[:3]:
                        r = self._extract_product(si.get("item", si), product)
                        if r:
                            results.append(r)
                else:
                    r = self._extract_product(item, product)
                    if r:
                        results.append(r)

        # Fallback: parsear precios desde HTML con regex si no hay JSON-LD
        if not results:
            prices = re.findall(r'\$\s*([\d\.]+)', html)
            names = re.findall(
                r'<h\d[^>]*class="[^"]*product[^"]*"[^>]*>([^<]+)</h\d>',
                html, re.IGNORECASE
            )
            if prices and names:
                price = float(prices[0].replace(".", ""))
                results.append(PriceResult(
                    store=self.STORE_NAME,
                    product_id=product["id"],
                    product_name=names[0].strip(),
                    price=price,
                    unit=product.get("unit", "und"),
                    quantity=product.get("typical_qty", 1),
                    url=self.SEARCH_URL.format(
                        query=product["search_terms"][0]
                    ),
                ))

        return results

    def _extract_product(self, item: dict, product: dict) -> "PriceResult | None":
        name = item.get("name", "")
        if not name:
            return None

        offers = item.get("offers", {})
        if isinstance(offers, list):
            offers = offers[0] if offers else {}

        price_str = str(offers.get("price", "0"))
        try:
            price = float(re.sub(r"[^\d.]", "", price_str))
        except Exception:
            return None
        if price <= 0:
            return None

        availability = offers.get("availability", "")
        in_stock = "InStock" in availability or availability == ""

        return PriceResult(
            store=self.STORE_NAME,
            product_id=product["id"],
            product_name=name,
            price=price,
            unit=product.get("unit", "und"),
            quantity=product.get("typical_qty", 1),
            url=item.get("url", ""),
            in_stock=in_stock,
        )
