"""
Scraper para Alkosto (alkosto.com)

PLATAFORMA: SAP Commerce Cloud (Hybris)
La página de producto y la página de búsqueda son SPA — el precio
se carga via JavaScript, no en el HTML inicial.

ESTRATEGIA:
  1. API interna de Hybris: GET /search?text=TERM&format=json
     SAP Commerce expone un endpoint JSON cuando se pide con
     Accept: application/json o con el parámetro format=json.
  2. Fallback a data/manual_alkosto.json si la API no responde.

URL de búsqueda confirmada: https://www.alkosto.com/search?text=TERM
"""

import json
import os
import re

import requests

from scrapers.base_scraper import BaseScraper, PriceResult


class AlkostoScraper(BaseScraper):

    STORE_NAME = "alkosto"
    BASE_URL   = "https://www.alkosto.com"
    SEARCH_URL = "https://www.alkosto.com/search?text={query}"

    # SAP Hybris acepta JSON nativo con estos headers
    HEADERS_JSON = {
        "User-Agent":    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36",
        "Accept":        "application/json, text/plain, */*",
        "Accept-Language": "es-CO,es;q=0.9",
        "Referer":       "https://www.alkosto.com/",
        "X-Requested-With": "XMLHttpRequest",
    }

    HEADERS_HTML = {
        "User-Agent":    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36",
        "Accept":        "text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language": "es-CO,es;q=0.9",
        "Referer":       "https://www.alkosto.com/",
    }

    def search_product(self, product: dict) -> list[PriceResult]:
        results = []

        for term in product.get("search_terms", [product["name"]]):
            # Intento 1: API JSON de Hybris
            found = self._try_hybris_api(term, product)
            if found:
                results.extend(found)
                break

            self._sleep(1.0, 2.0)

        # Fallback: precios manuales
        if not results:
            results = self._fallback_manual(product)

        return results

    def _try_hybris_api(self, term: str, product: dict) -> list[PriceResult]:
        """
        SAP Hybris expone resultados JSON si se solicita con Accept: application/json
        o con el parámetro &format=json en la URL de búsqueda.
        """
        try:
            # Variante 1: parámetro format=json (más común en Hybris)
            url = f"{self.SEARCH_URL.format(query=requests.utils.quote(term))}&format=json"
            resp = requests.get(url, headers=self.HEADERS_JSON, timeout=15)

            if resp.status_code == 200:
                try:
                    data = resp.json()
                    results = self._parse_hybris_response(data, product)
                    if results:
                        return results
                except ValueError:
                    pass  # no era JSON, intentar con HTML

            # Variante 2: HTML con JSON-LD embebido
            url_html = self.SEARCH_URL.format(query=requests.utils.quote(term))
            resp2 = requests.get(url_html, headers=self.HEADERS_HTML, timeout=15)
            if resp2.status_code == 200:
                return self._parse_json_ld_from_html(resp2.text, product)

        except requests.RequestException as e:
            self.logger.debug(f"Alkosto error red '{term}': {e}")

        return []

    def _parse_hybris_response(self, data: dict, product: dict) -> list[PriceResult]:
        """
        Parsea la respuesta JSON de SAP Hybris.
        Estructura típica: {"products": [{"name": ..., "price": {"value": ...}}]}
        """
        results = []
        items = (
            data.get("products")
            or data.get("results")
            or data.get("searchResults", {}).get("products", [])
            or []
        )
        for item in items[:3]:
            name = item.get("name") or item.get("summary") or ""
            # Hybris anida el precio en un objeto
            price_obj = item.get("price") or item.get("priceRange", {}).get("minPrice", {}) or {}
            price = float(price_obj.get("value", 0) or 0)
            if not name or not price:
                continue
            url = self.BASE_URL + item.get("url", "")
            results.append(PriceResult(
                store        = self.STORE_NAME,
                product_id   = product["id"],
                product_name = name,
                price        = price,
                unit         = product.get("unit", "und"),
                quantity     = product.get("typical_qty", 1),
                url          = url,
            ))
        return results

    def _parse_json_ld_from_html(self, html: str, product: dict) -> list[PriceResult]:
        """Extrae productos del JSON-LD embebido en el HTML de resultados."""
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        results = []
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data  = json.loads(script.string or "")
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if item.get("@type") == "Product":
                        r = self._from_ld(item, product)
                        if r:
                            results.append(r)
                    elif item.get("@type") == "ItemList":
                        for el in item.get("itemListElement", [])[:3]:
                            r = self._from_ld(el.get("item", el), product)
                            if r:
                                results.append(r)
            except Exception:
                continue
        return results[:3]

    def _from_ld(self, item: dict, product: dict) -> "PriceResult | None":
        name   = item.get("name", "")
        offers = item.get("offers", {})
        if isinstance(offers, list):
            offers = offers[0] if offers else {}
        price_str = str(offers.get("price", "0"))
        price = float(re.sub(r"[^\d.]", "", price_str) or 0)
        if not name or not price:
            return None
        # Detectar descuento
        orig_str = str(offers.get("priceValidUntil", "") or "")
        return PriceResult(
            store        = self.STORE_NAME,
            product_id   = product["id"],
            product_name = name,
            price        = price,
            unit         = product.get("unit", "und"),
            quantity     = product.get("typical_qty", 1),
            url          = item.get("url", ""),
        )

    def _fallback_manual(self, product: dict) -> list[PriceResult]:
        """Lee data/manual_alkosto.json si el scraping falla."""
        manual_path = os.path.join(
            os.path.dirname(__file__), "..", "data", "manual_alkosto.json"
        )
        if not os.path.exists(manual_path):
            return []
        try:
            with open(manual_path, encoding="utf-8") as f:
                manual = json.load(f)
            entry = manual.get(product["id"])
            if entry:
                self.logger.info(
                    f"  → [manual Alkosto] '{product['id']}': ${entry['price']:,}"
                )
                return [PriceResult(
                    store        = self.STORE_NAME,
                    product_id   = product["id"],
                    product_name = entry.get("name", product["name"]),
                    price        = float(entry["price"]),
                    unit         = product.get("unit", "und"),
                    quantity     = product.get("typical_qty", 1),
                    url          = self.SEARCH_URL.format(
                                       query=product["search_terms"][0]
                                   ),
                    discount_pct   = entry.get("discount_pct", 0),
                    original_price = entry.get("original_price"),
                )]
        except Exception as e:
            self.logger.warning(f"Error leyendo manual_alkosto.json: {e}")
        return []
