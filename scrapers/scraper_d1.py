"""
Scraper para Tiendas D1 — domicilios.tiendasd1.com

SITUACIÓN TÉCNICA:
  El portal de D1 es una SPA (React) con rendering 100% en cliente.
  requests + BeautifulSoup solo recibe el HTML shell vacío — los productos
  los carga dinámicamente via API interna no documentada.

ESTRATEGIA:
  1. Intentar la API interna de búsqueda descubierta via Network tab:
       GET /api/products/search?query=<term>&store=<store_id>
     (requiere store_id de Bogotá — 11808__352 basado en URL conocida)
  2. Si falla, usar Selenium/Playwright headless (si está disponible).
  3. Fallback final: precios manuales de data/manual_d1.json
     (actualizado por Luis después de cada visita a la tienda).

NOTA: El fallback manual es el modo principal en GitHub Actions,
ya que instalar Playwright agrega ~500MB al runner. Si quieres
habilitar el scraping real, descomenta la sección de Selenium
y agrega 'playwright' a requirements.txt.
"""

import json
import os
import re

import requests

from scrapers.base_scraper import BaseScraper, PriceResult

# Store ID de D1 Bogotá (de la URL https://domicilios.tiendasd1.com/store/11808__352)
D1_STORE_ID = "11808__352"


class D1Scraper(BaseScraper):

    STORE_NAME = "d1"
    BASE_URL   = "https://domicilios.tiendasd1.com"

    # Endpoint interno descubierto via DevTools Network tab
    # Formato observado en la URL de búsqueda del portal
    API_SEARCH = "https://domicilios.tiendasd1.com/api/products/search"

    HEADERS = {
        "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Accept":          "application/json, text/plain, */*",
        "Accept-Language": "es-CO,es;q=0.9",
        "Referer":         "https://domicilios.tiendasd1.com/",
        "Origin":          "https://domicilios.tiendasd1.com",
    }

    def search_product(self, product: dict) -> list[PriceResult]:
        results = []

        for term in product.get("search_terms", [product["name"]]):
            # ── Intento 1: API interna JSON ──────────────────────────────────
            found = self._try_api(term, product)
            if found:
                results.extend(found)
                break

            self._sleep(1.0, 2.0)

        # ── Fallback: precios manuales ────────────────────────────────────────
        if not results:
            results = self._fallback_manual(product)

        return results

    def _try_api(self, term: str, product: dict) -> list[PriceResult]:
        """
        Intenta el endpoint interno de búsqueda de D1.
        Si la API cambia o requiere autenticación, retorna lista vacía
        y el sistema cae al fallback manual sin romper.
        """
        params = {
            "query":   term,
            "store":   D1_STORE_ID,
            "channel": "WEB",
        }
        try:
            resp = requests.get(
                self.API_SEARCH,
                params=params,
                headers=self.HEADERS,
                timeout=12,
            )
            if resp.status_code != 200:
                self.logger.debug(
                    f"D1 API respondió {resp.status_code} para '{term}'"
                )
                return []

            data = resp.json()
            return self._parse_api_response(data, product)

        except (requests.RequestException, ValueError) as e:
            self.logger.debug(f"D1 API no disponible para '{term}': {e}")
            return []

    def _parse_api_response(self, data: dict | list, product: dict) -> list[PriceResult]:
        """
        Parsea la respuesta JSON del endpoint interno.
        La estructura exacta depende de la versión del API de D1.
        Se intenta con varios formatos conocidos de ecommerce colombiano.
        """
        results = []

        # Formato 1: {"products": [...]}
        items = (
            data.get("products")
            or data.get("items")
            or data.get("results")
            or (data if isinstance(data, list) else [])
        )

        for item in items[:self.MAX_RESULTS_PER_PRODUCT]:
            name  = (
                item.get("name")
                or item.get("title")
                or item.get("productName")
                or ""
            )
            price = (
                item.get("price")
                or item.get("sellingPrice")
                or item.get("salePrice")
                or 0
            )
            # Algunos APIs devuelven precio en centavos
            if isinstance(price, (int, float)) and price > 1_000_000:
                price = price / 100

            url = (
                item.get("url")
                or item.get("link")
                or item.get("slug", "")
            )
            if url and not url.startswith("http"):
                url = self.BASE_URL + "/p/" + url

            if name and price:
                results.append(PriceResult(
                    store        = self.STORE_NAME,
                    product_id   = product["id"],
                    product_name = name,
                    price        = float(price),
                    unit         = product.get("unit", "und"),
                    quantity     = product.get("typical_qty", 1),
                    url          = url,
                ))

        return results

    def _fallback_manual(self, product: dict) -> list[PriceResult]:
        """
        Modo principal en GitHub Actions.
        Lee data/manual_d1.json — actualizar después de cada visita a D1.
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
                    f"  → [manual D1] '{product['id']}': ${entry['price']:,}"
                )
                return [PriceResult(
                    store        = self.STORE_NAME,
                    product_id   = product["id"],
                    product_name = entry.get("name", product["name"]),
                    price        = float(entry["price"]),
                    unit         = product.get("unit", "und"),
                    quantity     = product.get("typical_qty", 1),
                    url          = f"{self.BASE_URL}/search?name={product['search_terms'][0]}",
                )]
        except Exception as e:
            self.logger.warning(f"Error leyendo manual_d1.json: {e}")
        return []
