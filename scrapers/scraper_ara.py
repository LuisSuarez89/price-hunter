"""
Scraper para Tiendas Ara — aratiendas.com/ahorro-ara/

ESTRATEGIA CONFIRMADA:
  Ara publica folletos PDF semanales en wp-content/uploads.

  Patrones de nombre CONFIRMADOS del historial real:
  - Folleto-S{N}_TiendasARA_Nacional_205x27cm_NACIONAL-copia.pdf  (jul 2026, S27)
  - Folleto-S{N}_TiendasARA_Nacional_205x27cm_NACIONAL.pdf
  - Ahorro-Folleto-S{N}_TiendasARA_Nacional_DIGITAL.pdf           (jun 2026)
  - DIGITAL-NACIONAL-_-S{N}-VF.pdf                               (feb 2026)
  - S{N}-FOLLETO-DIGITAL-AF.pdf                                   (2025)
"""

import io, json, os, re, datetime
from typing import Optional
import requests
from scrapers.base_scraper import BaseScraper, PriceResult

try:
    import pdfplumber
    HAS_PDF = True
except ImportError:
    HAS_PDF = False


def _iso_week() -> int:
    return datetime.date.today().isocalendar()[1]

def _year_month_for_offset(offset_weeks: int) -> tuple:
    d = datetime.date.today() - datetime.timedelta(weeks=offset_weeks)
    return d.year, d.month


class AraScraper(BaseScraper):

    STORE_NAME = "ara"
    BASE_URL   = "https://aratiendas.com"

    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36",
        "Accept":     "application/pdf,*/*",
        "Referer":    "https://aratiendas.com/ahorro-ara/",
    }

    # Plantillas en orden de probabilidad descendiente
    PDF_TEMPLATES = [
        "https://aratiendas.com/wp-content/uploads/{year}/{month:02d}/Folleto-S{week}_TiendasARA_Nacional_205x27cm_NACIONAL-copia.pdf",
        "https://aratiendas.com/wp-content/uploads/{year}/{month:02d}/Folleto-S{week}_TiendasARA_Nacional_205x27cm_NACIONAL.pdf",
        "https://aratiendas.com/wp-content/uploads/{year}/{month:02d}/Ahorro-Folleto-S{week}_TiendasARA_Nacional_DIGITAL.pdf",
        "https://aratiendas.com/wp-content/uploads/{year}/{month:02d}/Ahorro-Folleto-S{week}_TiendasARA_Nacional_DIGITAL-1.pdf",
        "https://aratiendas.com/wp-content/uploads/{year}/{month:02d}/DIGITAL-NACIONAL-_-S{week}-VF.pdf",
        "https://aratiendas.com/wp-content/uploads/{year}/{month:02d}/FINAL-ASEO-NACIONAL-S{week}.pdf",
        "https://aratiendas.com/wp-content/uploads/{year}/{month:02d}/S{week}-FOLLETO-DIGITAL-AF.pdf",
    ]

    def __init__(self):
        super().__init__()
        self._pdf_text: Optional[str] = None

    def scrape_all(self, products: list[dict]) -> list[PriceResult]:
        self._pdf_text = self._download_pdf()
        if not self._pdf_text:
            self.logger.warning("No se encontró el folleto PDF de Ara. Usando precios manuales.")
        self.results = []
        for i, product in enumerate(products, 1):
            self.logger.info(f"[{i}/{len(products)}] Buscando '{product['name']}' en ara...")
            found = self.search_product(product)
            found = [self._enrich(r) for r in found]
            self.results.extend(found)
            self.logger.info(f"  → {len(found)} resultado(s)")
        return self.results

    def search_product(self, product: dict) -> list[PriceResult]:
        results = []
        if self._pdf_text:
            results = self._search_pdf(product)
        if not results:
            results = self._fallback_manual(product)
        return results

    def _download_pdf(self) -> Optional[str]:
        if not HAS_PDF:
            self.logger.warning("pdfplumber no instalado")
            return None
        week = _iso_week()
        for offset in range(4):
            y, m = _year_month_for_offset(offset)
            w = week - offset
            if w < 1:
                w += 52; y -= 1
            for tmpl in self.PDF_TEMPLATES:
                url  = tmpl.format(year=y, month=m, week=w)
                text = self._try_pdf(url)
                if text:
                    self.logger.info(f"✓ Folleto Ara S{w}: {len(text)} chars")
                    return text
        self.logger.warning(f"No se encontró el folleto PDF de Ara para semana {week}.")
        return None

    def _try_pdf(self, url: str) -> Optional[str]:
        try:
            resp = requests.get(url, headers=self.HEADERS, timeout=20)
            if resp.status_code != 200:
                return None
            if "pdf" not in resp.headers.get("content-type","") and len(resp.content) < 2000:
                return None
            with pdfplumber.open(io.BytesIO(resp.content)) as pdf:
                text = "\n".join(p.extract_text() or "" for p in pdf.pages)
            return text if len(text) > 100 else None
        except Exception as e:
            self.logger.debug(f"PDF no disponible {url}: {e}")
            return None

    def _search_pdf(self, product: dict) -> list[PriceResult]:
        lines   = self._pdf_text.split("\n")
        results = []
        for term in product.get("search_terms", [product["name"]]):
            for i, line in enumerate(lines):
                if term.lower() not in line.lower():
                    continue
                price = self._price_near(lines, i)
                if not price:
                    continue
                results.append(PriceResult(
                    store=self.STORE_NAME, product_id=product["id"],
                    product_name=line.strip()[:80], price=price,
                    unit=product.get("unit","und"), quantity=product.get("typical_qty",1),
                    url=f"{self.BASE_URL}/ahorro-ara/"))
                if len(results) >= self.MAX_RESULTS_PER_PRODUCT:
                    break
            if results:
                break
        return results

    def _price_near(self, lines: list, start: int, window: int = 4) -> float:
        pat_dollar = re.compile(r'\$\s*([\d\.]+)')
        pat_num    = re.compile(r'\b(\d{1,2}[.,]\d{3})\b')
        for line in lines[start:min(start+window, len(lines))]:
            m = pat_dollar.search(line)
            if m:
                p = self._p(m.group(1))
                if 500 < p < 300_000:
                    return p
            m2 = pat_num.search(line)
            if m2:
                p = self._p(m2.group(1))
                if 500 < p < 300_000:
                    return p
        return 0.0

    def _fallback_manual(self, product: dict) -> list[PriceResult]:
        path = os.path.join(os.path.dirname(__file__),"..","data","manual_ara.json")
        if not os.path.exists(path):
            return []
        try:
            with open(path, encoding="utf-8") as f:
                manual = json.load(f)
            entry = manual.get(product["id"])
            if entry:
                self.logger.info(f"  → [manual Ara] '{product['id']}': ${entry['price']:,}")
                return [PriceResult(
                    store=self.STORE_NAME, product_id=product["id"],
                    product_name=entry.get("name", product["name"]),
                    price=float(entry["price"]), unit=product.get("unit","und"),
                    quantity=product.get("typical_qty",1),
                    url=f"{self.BASE_URL}/ahorro-ara/",
                    discount_pct=entry.get("discount_pct",0))]
        except Exception as e:
            self.logger.warning(f"manual_ara.json error: {e}")
        return []

    def _p(self, text: str) -> float:
        c = re.sub(r"[^\d]","",str(text)); return float(c) if c else 0.0