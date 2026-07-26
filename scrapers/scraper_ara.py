"""
Scraper para Tiendas Ara — aratiendas.com/ahorro-ara/

ESTRATEGIA DEFINITIVA (confirmada por inspección manual):
  1. GET https://aratiendas.com/ahorro-ara/
  2. Buscar el botón/enlace que apunta al PDF del folleto semanal.
     El PDF está en un <a href="...pdf"> vinculado a un <img> con
     src="...Asset-1descargar-pdf.svg"
  3. Descargar ese PDF y extraer texto con pdfplumber.
  4. Buscar cada producto en el texto extraído.
  5. Fallback: data/manual_ara.json si el HTML o PDF no están disponibles.

URL de ejemplo confirmada (semana 30):
  https://aratiendas.com/wp-content/uploads/2026/07/follelto-ahorro-s30.pdf
  (typo "follelto" con doble l — no normalizar, tomar la URL tal cual del HTML)
"""

import io, json, os, re
from typing import Optional

import requests
from bs4 import BeautifulSoup

from scrapers.base_scraper import BaseScraper, PriceResult

try:
    import pdfplumber
    HAS_PDF = True
except ImportError:
    HAS_PDF = False


class AraScraper(BaseScraper):

    STORE_NAME   = "ara"
    BASE_URL     = "https://aratiendas.com"
    AHORRO_URL   = "https://aratiendas.com/ahorro-ara/"
    # SVG del botón "Descargar PDF" — ancla para encontrar el enlace
    PDF_BTN_SVG  = "Asset-1descargar-pdf.svg"

    HEADERS_HTML = {
        "User-Agent":    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36",
        "Accept":        "text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language": "es-CO,es;q=0.9",
        "Referer":       "https://aratiendas.com/",
    }
    HEADERS_PDF = {
        "User-Agent":    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36",
        "Accept":        "application/pdf,*/*",
        "Referer":       "https://aratiendas.com/ahorro-ara/",
    }

    def __init__(self):
        super().__init__()
        self._pdf_text: Optional[str] = None

    # ── Pipeline ──────────────────────────────────────────────────────────────

    def scrape_all(self, products: list[dict]) -> list[PriceResult]:
        """Descarga el PDF una sola vez y busca todos los productos en él."""
        self._pdf_text = self._fetch_pdf()

        if not self._pdf_text:
            self.logger.warning(
                "No se pudo obtener el folleto PDF de Ara. "
                "Usando precios manuales."
            )

        self.results = []
        for i, product in enumerate(products, 1):
            self.logger.info(
                f"[{i}/{len(products)}] Buscando '{product['name']}' en ara..."
            )
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

    # ── Paso 1: encontrar la URL del PDF en la página ─────────────────────────

    def _fetch_pdf(self) -> Optional[str]:
        if not HAS_PDF:
            self.logger.warning("pdfplumber no instalado — agregar a requirements.txt")
            return None

        pdf_url = self._find_pdf_url()
        if not pdf_url:
            self.logger.warning(
                "No se encontró el enlace al PDF en aratiendas.com/ahorro-ara/"
            )
            return None

        self.logger.info(f"PDF encontrado: {pdf_url}")
        return self._download_pdf(pdf_url)

    def _find_pdf_url(self) -> Optional[str]:
        """
        Parsea https://aratiendas.com/ahorro-ara/ buscando el botón de descarga.

        El botón tiene esta estructura:
          <a href="...folleto.pdf">
            <img src="...Asset-1descargar-pdf.svg" ...>
          </a>

        Si el sitio bloquea el request, intenta las URLs de fallback
        con el patrón histórico de nombres de archivo.
        """
        try:
            resp = requests.get(
                self.AHORRO_URL, headers=self.HEADERS_HTML, timeout=15
            )
            if resp.status_code != 200:
                self.logger.warning(
                    f"aratiendas.com/ahorro-ara/ respondió {resp.status_code}"
                )
                return self._fallback_pdf_url()

            soup = BeautifulSoup(resp.text, "html.parser")

            # Buscar <img> cuyo src contiene el SVG del botón de descarga
            img = soup.find("img", src=lambda s: s and self.PDF_BTN_SVG in s)
            if img:
                # El enlace puede estar en el <a> padre o en un ancestro cercano
                for parent in [img.parent, img.parent.parent if img.parent else None]:
                    if parent and parent.name == "a":
                        href = parent.get("href", "")
                        if href.endswith(".pdf"):
                            url = href if href.startswith("http") else self.BASE_URL + href
                            return url

            # Búsqueda más amplia: cualquier <a href="...pdf"> en la página
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if href.endswith(".pdf") and "folleto" in href.lower():
                    url = href if href.startswith("http") else self.BASE_URL + href
                    self.logger.info(f"PDF encontrado por búsqueda amplia: {url}")
                    return url

            self.logger.warning(
                "No se encontró enlace a PDF en la página. "
                "Intentando URLs de fallback."
            )
            return self._fallback_pdf_url()

        except requests.RequestException as e:
            self.logger.warning(f"Error accediendo a ahorro-ara/: {e}")
            return self._fallback_pdf_url()

    def _fallback_pdf_url(self) -> Optional[str]:
        """
        Intenta URLs de patrón conocido cuando no se puede parsear la página.
        Incluye el typo confirmado 'follelto' (doble l) y variantes normales.
        """
        import datetime
        today = datetime.date.today()
        week  = today.isocalendar()[1]

        # Patrones ordenados por probabilidad, incluyendo el typo confirmado S30
        PATTERNS = [
            # Patrón con typo (confirmado semana 30)
            "https://aratiendas.com/wp-content/uploads/{year}/{month:02d}/follelto-ahorro-s{week}.pdf",
            # Patrón sin typo (puede aparecer en otras semanas)
            "https://aratiendas.com/wp-content/uploads/{year}/{month:02d}/folleto-ahorro-s{week}.pdf",
            # Patrones históricos anteriores
            "https://aratiendas.com/wp-content/uploads/{year}/{month:02d}/Folleto-S{week}_TiendasARA_Nacional_205x27cm_NACIONAL-copia.pdf",
            "https://aratiendas.com/wp-content/uploads/{year}/{month:02d}/Folleto-S{week}_TiendasARA_Nacional_205x27cm_NACIONAL.pdf",
            "https://aratiendas.com/wp-content/uploads/{year}/{month:02d}/Ahorro-Folleto-S{week}_TiendasARA_Nacional_DIGITAL.pdf",
            "https://aratiendas.com/wp-content/uploads/{year}/{month:02d}/DIGITAL-NACIONAL-_-S{week}-VF.pdf",
        ]

        for offset in range(4):
            d = today - datetime.timedelta(weeks=offset)
            y, m = d.year, d.month
            w = week - offset
            if w < 1:
                w += 52; y -= 1

            for pattern in PATTERNS:
                url = pattern.format(year=y, month=m, week=w)
                try:
                    head = requests.head(
                        url, headers=self.HEADERS_PDF, timeout=8
                    )
                    if head.status_code == 200:
                        ct = head.headers.get("content-type", "")
                        if "pdf" in ct or head.headers.get("content-length", "0") > "1000":
                            self.logger.info(
                                f"PDF fallback encontrado (S{w}): {url}"
                            )
                            return url
                except Exception:
                    continue

        return None

    # ── Paso 2: descargar y extraer texto del PDF ─────────────────────────────

    def _download_pdf(self, url: str) -> Optional[str]:
        try:
            resp = requests.get(url, headers=self.HEADERS_PDF, timeout=25)
            if resp.status_code != 200:
                self.logger.warning(f"PDF respondió {resp.status_code}: {url}")
                return None
            if len(resp.content) < 1000:
                self.logger.warning("PDF demasiado pequeño — posiblemente inválido")
                return None

            with pdfplumber.open(io.BytesIO(resp.content)) as pdf:
                text = "\n".join(p.extract_text() or "" for p in pdf.pages)

            if len(text) < 100:
                self.logger.warning("PDF descargado pero sin texto extraíble")
                return None

            self.logger.info(
                f"✓ Folleto Ara descargado: {len(text)} chars · {len(resp.content)//1024} KB"
            )
            return text

        except Exception as e:
            self.logger.warning(f"Error descargando PDF {url}: {e}")
            return None

    # ── Paso 3: buscar productos en el texto ──────────────────────────────────

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
                    store        = self.STORE_NAME,
                    product_id   = product["id"],
                    product_name = line.strip()[:80],
                    price        = price,
                    unit         = product.get("unit", "und"),
                    quantity     = product.get("typical_qty", 1),
                    url          = self.AHORRO_URL,
                ))
                if len(results) >= self.MAX_RESULTS_PER_PRODUCT:
                    break
            if results:
                break

        return results

    def _price_near(self, lines: list, start: int, window: int = 4) -> float:
        """Busca precio COP ($X.XXX o XX.XXX) en las líneas cercanas."""
        pat_dollar = re.compile(r'\$\s*([\d\.]+)')
        pat_num    = re.compile(r'\b(\d{1,2}[.,]\d{3})\b')

        for line in lines[start:min(start + window, len(lines))]:
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

    # ── Fallback manual ───────────────────────────────────────────────────────

    def _fallback_manual(self, product: dict) -> list[PriceResult]:
        path = os.path.join(
            os.path.dirname(__file__), "..", "data", "manual_ara.json"
        )
        if not os.path.exists(path):
            return []
        try:
            with open(path, encoding="utf-8") as f:
                manual = json.load(f)
            entry = manual.get(product["id"])
            if entry:
                self.logger.info(
                    f"  → [manual Ara] '{product['id']}': ${entry['price']:,}"
                )
                return [PriceResult(
                    store        = self.STORE_NAME,
                    product_id   = product["id"],
                    product_name = entry.get("name", product["name"]),
                    price        = float(entry["price"]),
                    unit         = product.get("unit", "und"),
                    quantity     = product.get("typical_qty", 1),
                    url          = self.AHORRO_URL,
                    discount_pct = entry.get("discount_pct", 0),
                )]
        except Exception as e:
            self.logger.warning(f"manual_ara.json error: {e}")
        return []

    def _p(self, text: str) -> float:
        c = re.sub(r"[^\d]", "", str(text))
        return float(c) if c else 0.0