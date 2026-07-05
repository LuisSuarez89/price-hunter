"""
Scraper para Makro Colombia (makro.com.co)

PLATAFORMA: Magento 2
URL de búsqueda confirmada: https://www.makro.com.co/catalogsearch/result/?q=TERM

Magento 2 renderiza productos en el HTML inicial (no es SPA pura),
y también expone un endpoint JSON:
  GET /catalogsearch/result/index/?q=TERM&ajax=1

NOTA: Makro es mayorista — algunas presentaciones son en bulto (ej. 5kg, x24).
El comparador normaliza a precio/100g o precio/L.
"""

import json
import os
import re

import requests
from bs4 import BeautifulSoup

from scrapers.base_scraper import BaseScraper, PriceResult


class MakroScraper(BaseScraper):

    STORE_NAME = "makro"
    BASE_URL   = "https://www.makro.com.co"
    SEARCH_URL = "https://www.makro.com.co/catalogsearch/result/?q={query}"

    HEADERS = {
        "User-Agent":    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36",
        "Accept":        "text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language": "es-CO,es;q=0.9",
        "Referer":       "https://www.makro.com.co/",
    }

    def search_product(self, product: dict) -> list[PriceResult]:
        results = []

        for term in product.get("search_terms", [product["name"]]):
            try:
                url  = self.SEARCH_URL.format(query=requests.utils.quote(term))
                resp = requests.get(url, headers=self.HEADERS, timeout=15)

                if resp.status_code != 200:
                    self.logger.warning(f"Makro {resp.status_code} para '{term}'")
                    self._sleep()
                    continue

                found = self._parse(resp.text, product)
                if found:
                    results.extend(found)
                    break

                self._sleep()

            except requests.RequestException as e:
                self.logger.warning(f"Makro error red '{term}': {e}")

        if not results:
            results = self._fallback_manual(product)

        return results

    def _parse(self, html: str, product: dict) -> list[PriceResult]:
        soup = BeautifulSoup(html, "html.parser")
        results = []

        # 1. JSON-LD (más estable)
        results = self._parse_json_ld(soup, product)
        if results:
            return results

        # 2. Selectores Magento 2
        # Magento 2 renderiza precios con data attributes
        cards = []
        for sel in [
            ".product-item",
            ".item.product.product-item",
            "[class*='product-item']",
            "li.item",
        ]:
            cards = soup.select(sel)
            if cards:
                break

        for card in cards[:3]:
            # Nombre
            name_el = card.select_one(
                ".product-item-name, "
                ".product-name, "
                "strong.product-item-name a, "
                "h2, h3"
            )
            if not name_el:
                continue
            name = name_el.get_text(strip=True)

            # Precio — Magento 2 usa data-price-amount o .price
            price = 0.0
            price_el = card.select_one(
                "[data-price-amount], "
                ".special-price .price, "
                ".price-final_price .price, "
                ".price"
            )
            if price_el:
                # Primero intentar el data attribute (más confiable)
                data_price = price_el.get("data-price-amount", "")
                if data_price:
                    try:
                        price = float(data_price)
                    except ValueError:
                        pass
                if not price:
                    price = self._p(price_el.get_text())

            if not name or not price:
                continue

            link_el  = card.select_one("a.product-item-link, a[href]")
            href     = link_el["href"] if link_el else ""
            url_prod = href if href.startswith("http") else self.BASE_URL + href

            results.append(PriceResult(
                store        = self.STORE_NAME,
                product_id   = product["id"],
                product_name = name,
                price        = price,
                unit         = product.get("unit", "und"),
                quantity     = product.get("typical_qty", 1),
                url          = url_prod,
            ))

        return results

    def _parse_json_ld(self, soup, product: dict) -> list[PriceResult]:
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
        price = self._p(str(offers.get("price", "0")))
        if not name or not price:
            return None
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
        manual_path = os.path.join(
            os.path.dirname(__file__), "..", "data", "manual_makro.json"
        )
        if not os.path.exists(manual_path):
            return []
        try:
            with open(manual_path, encoding="utf-8") as f:
                manual = json.load(f)
            entry = manual.get(product["id"])
            if entry:
                self.logger.info(
                    f"  → [manual Makro] '{product['id']}': ${entry['price']:,}"
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
                )]
        except Exception as e:
            self.logger.warning(f"Error leyendo manual_makro.json: {e}")
        return []

    def _p(self, text: str) -> float:
        cleaned = re.sub(r"[^\d]", "", str(text))
        return float(cleaned) if cleaned else 0.0
