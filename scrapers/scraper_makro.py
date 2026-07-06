"""
Scraper para Makro Colombia.
URL real confirmada: https://tienda.makro.com.co/search?name=TERM
"""
import json, os, re
import requests
from bs4 import BeautifulSoup
from scrapers.base_scraper import BaseScraper, PriceResult

class MakroScraper(BaseScraper):
    STORE_NAME = "makro"
    BASE_URL   = "https://tienda.makro.com.co"
    SEARCH_URL = "https://tienda.makro.com.co/search?name={query}"

    HEADERS = {
        "User-Agent":    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36",
        "Accept":        "text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language": "es-CO,es;q=0.9",
        "Referer":       "https://tienda.makro.com.co/",
    }

    def search_product(self, product: dict) -> list[PriceResult]:
        results = []
        for term in product.get("search_terms", [product["name"]]):
            try:
                url  = self.SEARCH_URL.format(query=requests.utils.quote(term))
                resp = requests.get(url, headers=self.HEADERS, timeout=15)
                if resp.status_code != 200:
                    self._sleep(1, 2); continue

                found = self._parse(resp.text, product)
                if found:
                    results.extend(found); break
                self._sleep(1, 2)
            except requests.RequestException as e:
                self.logger.warning(f"Makro red error '{term}': {e}")

        if not results:
            results = self._fallback(product)
        return results

    def _parse(self, html: str, product: dict) -> list[PriceResult]:
        soup    = BeautifulSoup(html, "html.parser")
        results = []

        # JSON-LD primero
        results = self._parse_json_ld(soup, product)
        if results:
            return results

        # tienda.makro.com.co es una SPA tipo Koba/React similar a D1
        # Intentar extraer de script con datos de productos
        for script in soup.find_all("script"):
            text = script.string or ""
            if '"products"' in text or '"items"' in text:
                try:
                    # Buscar array JSON dentro del script
                    m = re.search(r'"(?:products|items)"\s*:\s*(\[.*?\])', text, re.DOTALL)
                    if m:
                        items = json.loads(m.group(1))
                        for item in items[:self.MAX_RESULTS_PER_PRODUCT]:
                            r = self._from_dict(item, product)
                            if r: results.append(r)
                        if results: return results
                except Exception:
                    continue

        # Selectores HTML genéricos
        for sel in [".product-item", "[class*='product-card']", "[class*='ProductCard']",
                    "li.product", ".item"]:
            cards = soup.select(sel)
            if not cards: continue
            for card in cards[:self.MAX_RESULTS_PER_PRODUCT]:
                name_el  = card.select_one("[class*='name'],[class*='title'],h2,h3")
                price_el = card.select_one("[class*='price'],[data-price-amount]")
                if not name_el or not price_el: continue
                price = float(price_el.get("data-price-amount", 0) or 0) or self._p(price_el.get_text())
                if not price: continue
                link = card.select_one("a[href]")
                href = link["href"] if link else ""
                results.append(PriceResult(
                    store=self.STORE_NAME, product_id=product["id"],
                    product_name=name_el.get_text(strip=True), price=price,
                    unit=product.get("unit","und"), quantity=product.get("typical_qty",1),
                    url=href if href.startswith("http") else self.BASE_URL+href))
            if results: break
        return results

    def _parse_json_ld(self, soup, product):
        results = []
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "")
                for item in (data if isinstance(data, list) else [data]):
                    if item.get("@type") == "ItemList":
                        for el in item.get("itemListElement",[])[:self.MAX_RESULTS_PER_PRODUCT]:
                            r = self._from_ld(el.get("item",el), product)
                            if r: results.append(r)
                    elif item.get("@type") == "Product":
                        r = self._from_ld(item, product)
                        if r: results.append(r)
            except Exception: continue
        return results

    def _from_ld(self, item, product):
        name   = item.get("name","")
        offers = item.get("offers",{})
        if isinstance(offers, list): offers = offers[0] if offers else {}
        price  = self._p(str(offers.get("price","0")))
        if not name or not price: return None
        return PriceResult(store=self.STORE_NAME, product_id=product["id"],
            product_name=name, price=price, unit=product.get("unit","und"),
            quantity=product.get("typical_qty",1), url=item.get("url",""))

    def _from_dict(self, item, product):
        name  = item.get("name") or item.get("productName") or item.get("title","")
        price = float(item.get("price") or item.get("sellingPrice") or 0)
        if not name or not price: return None
        return PriceResult(store=self.STORE_NAME, product_id=product["id"],
            product_name=name, price=price, unit=product.get("unit","und"),
            quantity=product.get("typical_qty",1), url=item.get("url",""))

    def _fallback(self, product):
        path = os.path.join(os.path.dirname(__file__), "..", "data", "manual_makro.json")
        if not os.path.exists(path): return []
        try:
            with open(path, encoding="utf-8") as f: manual = json.load(f)
            entry = manual.get(product["id"])
            if entry:
                return [PriceResult(store=self.STORE_NAME, product_id=product["id"],
                    product_name=entry.get("name", product["name"]),
                    price=float(entry["price"]), unit=product.get("unit","und"),
                    quantity=product.get("typical_qty",1), url="manual")]
        except Exception as e: self.logger.warning(f"manual_makro.json: {e}")
        return []

    def _p(self, text):
        c = re.sub(r"[^\d]","",str(text)); return float(c) if c else 0.0
