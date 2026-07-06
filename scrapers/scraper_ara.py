"""
Scraper para Tiendas Ara — aratiendas.com

SITUACIÓN REAL CONFIRMADA:
  Ara NO tiene ecommerce ni precios en su web.
  aratiendas.com es un catálogo informativo sin precios.
  La única fuente digital de precios de Ara son los folletos PDF
  semanales publicados en:
    https://aratiendas.com/wp-content/uploads/YYYY/MM/<nombre>.pdf

ESTRATEGIA:
  1. Detectar el número de semana ISO actual.
  2. Probar las variantes de URL conocidas del folleto semanal.
  3. Descargar el PDF y extraer texto con pdfplumber.
  4. Buscar en el texto los productos de la canasta y sus precios.
  5. Fallback: data/manual_ara.json si no se encuentra el PDF.

PATRONES DE URL CONOCIDOS (del historial de folletos):
  - Ahorro-Folleto-S{N}_TiendasARA_Nacional_DIGITAL.pdf  (2026)
  - DIGITAL-NACIONAL-_-S{N}-VF.pdf                       (2026)
  - S{N}-FOLLETO-DIGITAL-AF.pdf                          (2025)
  - FOLLETO-DIGITAL-ASEO-S{N}-AF.pdf                     (aseo)
"""

import io
import json
import os
import re
import datetime
from typing import Optional

import requests

from scrapers.base_scraper import BaseScraper, PriceResult

try:
    import pdfplumber
    HAS_PDFPLUMBER = True
except ImportError:
    HAS_PDFPLUMBER = False


def _week_num() -> int:
    """Número de semana ISO del año actual."""
    return datetime.date.today().isocalendar()[1]


def _year_month() -> tuple[int, int]:
    t = datetime.date.today()
    return t.year, t.month


class AraScraper(BaseScraper):

    STORE_NAME = "ara"
    BASE_URL   = "https://aratiendas.com"

    HEADERS = {
        "User-Agent":    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36",
        "Accept":        "application/pdf,*/*",
        "Referer":       "https://aratiendas.com/",
    }

    # Plantillas de URL del folleto en orden de probabilidad
    PDF_URL_TEMPLATES = [
        # Formato 2026 (semana actual y anterior)
        "https://aratiendas.com/wp-content/uploads/{year}/{month:02d}/Ahorro-Folleto-S{week}_TiendasARA_Nacional_DIGITAL.pdf",
        "https://aratiendas.com/wp-content/uploads/{year}/{month:02d}/DIGITAL-NACIONAL-_-S{week}-VF.pdf",
        "https://aratiendas.com/wp-content/uploads/{year}/{month:02d}/FINAL-ASEO-NACIONAL-S{week}.pdf",
        # Formato 2025
        "https://aratiendas.com/wp-content/uploads/{year}/{month:02d}/S{week}-FOLLETO-DIGITAL-AF.pdf",
        "https://aratiendas.com/wp-content/uploads/{year}/{month:02d}/FOLLETO-DIGITAL-ASEO-S{week}-AF.pdf",
    ]

    def __init__(self):
        super().__init__()
        self._pdf_text: Optional[str] = None   # cache del PDF descargado

    # ── Pipeline principal ────────────────────────────────────────────────────

    def scrape_all(self, products: list[dict]) -> list[PriceResult]:
        """
        Sobreescribe el método base para descargar el PDF una sola vez
        y luego buscar todos los productos en él.
        """
        self._pdf_text = self._download_pdf_text()

        if not self._pdf_text:
            self.logger.warning(
                "No se pudo obtener el folleto PDF de Ara. "
                "Usando precios manuales para todos los productos."
            )

        self.results = []
        for i, product in enumerate(products, 1):
            self.logger.info(
                f"[{i}/{len(products)}] Buscando '{product['name']}' en ara..."
            )
            found = self.search_product(product)
            self.results.extend(found)
            self.logger.info(f"  → {len(found)} resultado(s)")

        return self.results

    def search_product(self, product: dict) -> list[PriceResult]:
        results = []

        # Buscar en el texto del PDF si está disponible
        if self._pdf_text:
            results = self._search_in_pdf(product)

        # Fallback: precios manuales
        if not results:
            results = self._fallback_manual(product)

        return results

    # ── Descarga del PDF ──────────────────────────────────────────────────────

    def _download_pdf_text(self) -> Optional[str]:
        """
        Intenta descargar el folleto PDF de Ara de la semana actual.
        Prueba la semana actual y la anterior para cubrir cambios de semana.
        Retorna el texto extraído o None si no lo encuentra.
        """
        if not HAS_PDFPLUMBER:
            self.logger.warning(
                "pdfplumber no instalado — agregar 'pdfplumber' a requirements.txt"
            )
            return None

        year, month = _year_month()
        week        = _week_num()

        # Probar semana actual y las 2 anteriores (Ara publica el jueves)
        for w in [week, week - 1, week - 2]:
            # El mes puede cambiar al retroceder semanas
            candidate_date = datetime.date.today() - datetime.timedelta(weeks=(week - w))
            y = candidate_date.year
            m = candidate_date.month

            for template in self.PDF_URL_TEMPLATES:
                url = template.format(year=y, month=m, week=w)
                text = self._try_download_pdf(url)
                if text:
                    self.logger.info(
                        f"✓ Folleto Ara descargado: semana {w} ({len(text)} chars)"
                    )
                    return text

        self.logger.warning("No se encontró el folleto PDF de Ara para esta semana.")
        return None

    def _try_download_pdf(self, url: str) -> Optional[str]:
        """Descarga un PDF y extrae su texto. Retorna None si falla."""
        try:
            resp = requests.get(url, headers=self.HEADERS, timeout=20)
            if resp.status_code != 200:
                return None

            content_type = resp.headers.get("content-type", "")
            if "pdf" not in content_type and len(resp.content) < 1000:
                return None

            with pdfplumber.open(io.BytesIO(resp.content)) as pdf:
                pages_text = []
                for page in pdf.pages:
                    t = page.extract_text()
                    if t:
                        pages_text.append(t)
                text = "\n".join(pages_text)

            return text if len(text) > 100 else None

        except Exception as e:
            self.logger.debug(f"PDF no disponible en {url}: {e}")
            return None

    # ── Búsqueda en texto del PDF ─────────────────────────────────────────────

    def _search_in_pdf(self, product: dict) -> list[PriceResult]:
        """
        Busca el producto en el texto del folleto PDF.
        Estrategia: buscar el término cerca de un precio ($XX.XXX).
        """
        text  = self._pdf_text
        lines = text.split("\n")
        results = []

        for term in product.get("search_terms", [product["name"]]):
            term_lower = term.lower().strip()

            for i, line in enumerate(lines):
                line_lower = line.lower()
                if term_lower not in line_lower:
                    continue

                # Buscar precio en la misma línea o en las 3 siguientes
                price = self._find_price_near(lines, i)
                if not price:
                    continue

                # Buscar cantidad/gramaje en la línea
                name = line.strip()[:80]  # limitar longitud

                results.append(PriceResult(
                    store        = self.STORE_NAME,
                    product_id   = product["id"],
                    product_name = name,
                    price        = price,
                    unit         = product.get("unit", "und"),
                    quantity     = product.get("typical_qty", 1),
                    url          = f"{self.BASE_URL}/wp-content/uploads/ (folleto PDF semana {_week_num()})",
                ))
                break  # un resultado por término es suficiente

            if results:
                break  # encontramos con este término, no seguir

        return results[:2]

    def _find_price_near(self, lines: list[str], start_idx: int, window: int = 4) -> float:
        """
        Busca el patrón de precio ($XX.XXX o $X.XXX) en las líneas cercanas.
        Los folletos de Ara usan formato colombiano: $12.900, $3.450
        """
        # Patrón: $ seguido de número con puntos (formato COP)
        price_pattern = re.compile(r'\$\s*([\d\.]+)')
        # También números sueltos estilo 12.900 o 12900 al final de línea
        num_pattern   = re.compile(r'\b(\d{1,2}[.,]\d{3})\b')

        end_idx = min(start_idx + window, len(lines))
        for line in lines[start_idx:end_idx]:
            # Buscar $XX.XXX
            m = price_pattern.search(line)
            if m:
                price = self._p(m.group(1))
                if 500 < price < 200_000:  # rango razonable para mercado Colombia
                    return price
            # Buscar XX.XXX sin $
            m2 = num_pattern.search(line)
            if m2:
                price = self._p(m2.group(1))
                if 500 < price < 200_000:
                    return price

        return 0.0

    # ── Fallback manual ───────────────────────────────────────────────────────

    def _fallback_manual(self, product: dict) -> list[PriceResult]:
        """Lee data/manual_ara.json si el PDF no está disponible."""
        manual_path = os.path.join(
            os.path.dirname(__file__), "..", "data", "manual_ara.json"
        )
        if not os.path.exists(manual_path):
            return []
        try:
            with open(manual_path, encoding="utf-8") as f:
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
                    url          = f"{self.BASE_URL}/ahorro-ara/ (folleto semanal)",
                    discount_pct = entry.get("discount_pct", 0),
                )]
        except Exception as e:
            self.logger.warning(f"Error leyendo manual_ara.json: {e}")
        return []

    def _p(self, text: str) -> float:
        cleaned = re.sub(r"[^\d]", "", str(text))
        return float(cleaned) if cleaned else 0.0
