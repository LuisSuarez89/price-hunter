"""
Scraper para Olímpica (olimpica.com).
URL real confirmada: https://www.olimpica.com/carne?_q=TERM&map=ft

Olímpica usa VTEX IO — plataforma de ecommerce con:
- HTML con JSON-LD de productos
- API de búsqueda: GET /api/catalog_system/pub/products/search/?ft=TERM
- Script de estado "__STATE__" con datos JSON completos
"""
import json, os, re
import requests
from bs4 import BeautifulSoup
from scrapers.base_scraper import BaseScraper, PriceResult

class OlimpicaScraper(BaseScraper):
    STORE_NAME = "olimpica"
    BASE_URL   = "https://www.olimpica.com"
    SEARCH_URL = "https://www.olimpica.com/{term}?_q={query}&map=ft"
    # API VTEX nativa (más estable que HTML)
    VTEX_API   = "https://www.olimpica.com/api/catalog_system/pub/products/search/?ft={query}&_from=0&_to=9"

    HEADERS = {
        "User-Agent":    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36",
        "Accept":        "application/json, text/html, */*",
        "Accept-Language": "es-CO,es;q=0.9",
        "Referer":       "https://www.olimpica.com/",
    }

    def search_product(self, product: dict) -> list[PriceResult]:
        results = []
        for term in product.get("search_terms", [product["name"]]):
            # Intento 1: API VTEX (JSON puro, más confiable)
            found = self._try_vtex_api(term, product)
            if found:
                results.extend(found); break

            # Intento 2: HTML con JSON-LD
            found = self._try_html(term, product)
            if found:
                results.extend(found); break

            self._sleep(1, 2)

        if not results:
            results = self._fallback(product)
        return results

    def _try_vtex_api(self, term: str, product: dict) -> list[PriceResult]:
        try:
            url  = self.VTEX_API.format(query=requests.utils.quote(term))
            resp = requests.get(url, headers={**self.HEADERS, "Accept": "application/json"}, timeout=15)
            if resp.status_code != 200: return []
            items = resp.json()
            if not isinstance(items, list): return []
            results = []
            for item in items[:self.MAX_RESULTS_PER_PRODUCT]:
                name = item.get("productName","") or item.get("name","")
                brand = item.get("brand","")
                # Precio en VTEX: items[0].sellers[0].commertialOffer.Price
                price = 0.0
                try:
                    price = item["items"][0]["sellers"][0]["commertialOffer"]["Price"]
                except (KeyError, IndexError): pass
                if not name or not price: continue
                link = item.get("link","") or item.get("url","")
                results.append(PriceResult(
                    store=self.STORE_NAME, product_id=product["id"],
                    product_name=name, brand=brand, price=float(price),
                    unit=product.get("unit","und"), quantity=product.get("typical_qty",1),
                    url=link))
            return results
        except Exception as e:
            self.logger.debug(f"Olímpica VTEX API error '{term}': {e}")
            return []

    def _try_html(self, term: str, product: dict) -> list[PriceResult]:
        try:
            url  = self.SEARCH_URL.format(term=requests.utils.quote(term),
                                          query=requests.utils.quote(term))
            resp = requests.get(url, headers=self.HEADERS, timeout=15)
            if resp.status_code != 200: return []
            soup = BeautifulSoup(resp.text, "html.parser")

            # Intentar JSON-LD
            results = self._parse_json_ld(soup, product)
            if results: return results

            # Intentar __STATE__ (VTEX inyecta estado en script)
            for script in soup.find_all("script"):
                txt = script.string or ""
                if "__STATE__" in txt:
                    m = re.search(r'__STATE__\s*=\s*(\{.*\})', txt, re.DOTALL)
                    if m:
                        try:
                            state = json.loads(m.group(1))
                            results = self._parse_vtex_state(state, product)
                            if results: return results
                        except Exception: pass

            # Selectores VTEX IO típicos
            for sel in [".vtex-product-summary", "[class*='productSummary']",
                        "[class*='product-summary']", "article.product"]:
                cards = soup.select(sel)
                if not cards: continue
                for card in cards[:self.MAX_RESULTS_PER_PRODUCT]:
                    name_el  = card.select_one("[class*='productBrand'],[class*='name'],h3,h2")
                    price_el = card.select_one("[class*='sellingPrice'],[class*='price'],span.price")
                    if not name_el or not price_el: continue
                    price = self._p(price_el.get_text())
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
        except Exception as e:
            self.logger.warning(f"Olímpica HTML error '{term}': {e}")
            return []

    def _parse_vtex_state(self, state: dict, product: dict) -> list[PriceResult]:
        """VTEX inyecta todos los datos de producto en window.__STATE__ como JSON."""
        results = []
        for key, val in state.items():
            if not isinstance(val, dict): continue
            if val.get("__typename") != "Product": continue
            name  = val.get("productName","")
            brand = val.get("brand","")
            price = 0.0
            items = val.get("items",[])
            try: price = items[0]["sellers"][0]["commertialOffer"]["Price"]
            except (KeyError, IndexError): pass
            if name and price:
                results.append(PriceResult(
                    store=self.STORE_NAME, product_id=product["id"],
                    product_name=name, brand=brand, price=float(price),
                    unit=product.get("unit","und"), quantity=product.get("typical_qty",1)))
            if len(results) >= self.MAX_RESULTS_PER_PRODUCT: break
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
        brand  = item.get("brand",{})
        brand  = brand.get("name","") if isinstance(brand, dict) else str(brand)
        offers = item.get("offers",{})
        if isinstance(offers, list): offers = offers[0] if offers else {}
        price  = self._p(str(offers.get("price","0")))
        if not name or not price: return None
        return PriceResult(store=self.STORE_NAME, product_id=product["id"],
            product_name=name, brand=brand, price=price,
            unit=product.get("unit","und"), quantity=product.get("typical_qty",1),
            url=item.get("url",""))

    def _fallback(self, product):
        path = os.path.join(os.path.dirname(__file__),"..","data","manual_olimpica.json")
        if not os.path.exists(path): return []
        try:
            with open(path, encoding="utf-8") as f: manual = json.load(f)
            entry = manual.get(product["id"])
            if entry:
                return [PriceResult(store=self.STORE_NAME, product_id=product["id"],
                    product_name=entry.get("name",product["name"]),
                    brand=entry.get("brand",""), price=float(entry["price"]),
                    unit=product.get("unit","und"), quantity=product.get("typical_qty",1),
                    url="manual")]
        except Exception as e: self.logger.warning(f"manual_olimpica.json: {e}")
        return []

    def _p(self, text):
        c = re.sub(r"[^\d]","",str(text)); return float(c) if c else 0.0
