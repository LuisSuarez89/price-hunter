"""
Scraper para Tiendas Ara — aratiendas.com

PLATAFORMA: WordPress + WooCommerce
URL búsqueda: https://aratiendas.com/?s=TERM&post_type=product

Selectores WooCommerce confirmados de la URL de producto observada:
  https://aratiendas.com/prod_marcas_propias/carne-pollo-y-pescado/...
  - Tarjetas:    li.product  /  .products .type-product
  - Nombre:      .woocommerce-loop-product__title
  - Precio:      .price .woocommerce-Price-amount bdi
  - Con dto:     .price ins .woocommerce-Price-amount bdi  (rebajado)
                 .price del .woocommerce-Price-amount bdi  (original tachado)
"""

import json
import re

import requests
from bs4 import BeautifulSoup

from scrapers.base_scraper import BaseScraper, PriceResult


class AraScraper(BaseScraper):

    STORE_NAME = "ara"
    BASE_URL   = "https://aratiendas.com"
    SEARCH_URL = "https://aratiendas.com/?s={query}&post_type=product"

    HEADERS = {
        "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "es-CO,es;q=0.9",
        "Referer":         "https://aratiendas.com/",
        "Connection":      "keep-alive",
    }

    def search_product(self, product: dict) -> list[PriceResult]:
        results = []
        for term in product.get("search_terms", [product["name"]]):
            try:
                url  = self.SEARCH_URL.format(query=requests.utils.quote(term))
                resp = requests.get(url, headers=self.HEADERS, timeout=15)
                if resp.status_code != 200:
                    self.logger.warning(f"Ara {resp.status_code} para '{term}'")
                    self._sleep()
                    continue

                found = self._parse(resp.text, product)
                if found:
                    results.extend(found)
                    break

                self._sleep()

            except requests.RequestException as e:
                self.logger.warning(f"Ara error red '{term}': {e}")

        return results

    def _parse(self, html: str, product: dict) -> list[PriceResult]:
        soup = BeautifulSoup(html, "html.parser")

        # Intento 1: JSON-LD (más estable ante cambios de CSS)
        results = self._parse_json_ld(soup, product)
        if results:
            return results

        # Intento 2: selectores WooCommerce
        cards = []
        for sel in ["li.product", ".type-product", "[class*='product-type']", ".products article"]:
            cards = soup.select(sel)
            if cards:
                break

        for card in cards[:3]:
            # Nombre
            name_el = card.select_one(
                ".woocommerce-loop-product__title, "
                "h2.entry-title, h2.product-title, h2, h3"
            )
            if not name_el:
                continue
            name = name_el.get_text(strip=True)

            # Precio (WooCommerce puede tener precio rebajado dentro de <ins>)
            price, original, discount = self._woo_price(card)
            if not price:
                continue

            link = card.select_one("a[href]")
            href = link["href"] if link else ""
            url  = href if href.startswith("http") else self.BASE_URL + href

            results.append(PriceResult(
                store          = self.STORE_NAME,
                product_id     = product["id"],
                product_name   = name,
                price          = price,
                unit           = product.get("unit", "und"),
                quantity       = product.get("typical_qty", 1),
                url            = url,
                discount_pct   = discount,
                original_price = original,
            ))

        return results

    def _woo_price(self, card) -> tuple[float, float | None, float]:
        """Extrae precio final, precio original y % descuento de tarjeta WooCommerce."""
        pc = card.select_one(".price")
        if not pc:
            return 0.0, None, 0.0

        # Precio rebajado (dentro de <ins>)
        ins = pc.select_one("ins .woocommerce-Price-amount bdi, ins .amount")
        # Precio tachado (dentro de <del>)
        old = pc.select_one("del .woocommerce-Price-amount bdi, del .amount")
        # Precio normal (sin ins/del)
        simple = pc.select_one(".woocommerce-Price-amount bdi, .amount")

        if ins:
            price    = self._p(ins.get_text())
            original = self._p(old.get_text()) if old else None
            discount = round((1 - price / original) * 100, 1) if original and original > price else 0.0
            return price, original, discount
        if simple:
            return self._p(simple.get_text()), None, 0.0
        return 0.0, None, 0.0

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

    def _p(self, text: str) -> float:
        cleaned = re.sub(r"[^\d]", "", str(text))
        return float(cleaned) if cleaned else 0.0
