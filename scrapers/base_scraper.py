"""
Base scraper — todos los scrapers de tienda heredan de esta clase.
"""
import json, logging, re, time, random
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from typing import Optional
from datetime import date

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s — %(message)s")


def extract_quantity_display(name: str) -> str:
    """
    Extrae presentación legible del nombre del producto.
    Maneja: 350g, 5kg, 2.5kg, 4.000g, 4.000 ml, 3L, x6 110g, x90u
    """
    s = name.lower()
    parts = []

    # ── Multiplicidad ─────────────────────────────────────────────────────────
    m = re.search(r'[x×]\s*(\d+)\s*(?:u|und|un)?\b', s)
    if m:
        parts.append(f'x{m.group(1)}')
    else:
        m2 = re.search(r'\b(\d+)\s*(?:u|und|un|unidades?)\b', s)
        if m2 and int(m2.group(1)) > 1:
            parts.append(f'x{m2.group(1)}')

    unit_re  = r'(kg|kgr|k\b|g\b|gr\b|l\b|lt\b|ml\b|cc\b)'
    unit_map = {'kgr':'kg','gr':'g','lt':'L','cc':'ml','k':'kg','l':'L'}
    val_str = unit_str = None

    # Orden de prioridad: miles > decimal > entero
    # 1. Miles con punto (DD.DDD): 4.000g, 4.000 ml, 5.000 G
    #    Requiere exactamente 3 dígitos después del punto → no confunde con decimal
    m4 = re.search(rf'\b(\d{{1,3}}(?:[.]\d{{3}})+)\s*{unit_re}', s)
    if m4:
        val_str  = m4.group(1).replace('.', '')   # 4.000 → 4000
        unit_str = m4.group(2).rstrip('.')

    # 2. Decimal (1-2 decimales): 2.5kg, 4,5L
    #    Usa {1,2} para NO capturar miles (3 decimales)
    if not val_str:
        m3 = re.search(rf'\b(\d+[.,]\d{{1,2}})\s*{unit_re}', s)
        if m3:
            val_str  = m3.group(1).replace(',', '.')
            unit_str = m3.group(2).rstrip('.')

    # 3. Entero: 500g, 3L, 946 ml
    if not val_str:
        m5 = re.search(rf'\b(\d+)\s*{unit_re}', s)
        if m5:
            val_str  = m5.group(1)
            unit_str = m5.group(2).rstrip('.')

    if val_str and unit_str:
        unit_str = unit_map.get(unit_str, unit_str)
        parts.append(f'{val_str}{unit_str}')

    return ' '.join(parts) if parts else ''


KNOWN_BRANDS = [
    'colanta','zenú','zenu','alquería','alqueria','alpina','friko','campollo',
    'bimbo','noel','ramo','diana','doria','cayena','viand','lorenzano','rica',
    'protex','dove','vanish','ariel','fab','axion','riel','dersa',
    'kelloggs','quaker','nestlé','nestle','nescafé','nescafe','maggi','knorr',
    'heinz','california','captain bay',
]

def extract_brand(name: str) -> str:
    nl = name.lower()
    for brand in KNOWN_BRANDS:
        if brand in nl:
            return brand.title()
    # Heurística: primera palabra que no sea artículo/descriptor genérico
    stopwords = {
        'el','la','los','las','de','del','un','una','con','sin','para','y',
        'filete','filetes','carne','pollo','res','cerdo','pan','arroz','cafe',
        'leche','aceite','azucar','sal','jabon','jabón','galleta','galletas',
        'bebida','yogurt','queso','chorizo','salchicha','costilla','molida',
    }
    for word in name.strip().split():
        if word.lower() not in stopwords and len(word) > 2 and word[0].isupper():
            return word
    return ""


@dataclass
class PriceResult:
    store:            str
    product_id:       str
    product_name:     str
    brand:            str   = ""
    price:            float = 0.0
    unit:             str   = "und"
    quantity:         float = 1.0
    quantity_display: str   = ""    # "350g", "x6 110g", "2.5kg"
    price_per_unit:   float = 0.0   # normalizado por comparador
    unit_label:       str   = ""    # "/100g", "/L", "/und"
    url:              str   = ""
    date:             str   = field(default_factory=lambda: str(date.today()))
    in_stock:         bool  = True
    discount_pct:     float = 0.0
    original_price:   Optional[float] = None

    def to_dict(self):
        return asdict(self)


class BaseScraper(ABC):
    STORE_NAME:              str = ""
    BASE_URL:                str = ""
    MAX_RESULTS_PER_PRODUCT: int = 10

    HEADERS = {
        "User-Agent":    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Accept":        "text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language": "es-CO,es;q=0.9",
    }

    def __init__(self):
        self.logger  = logging.getLogger(self.__class__.__name__)
        self.results: list[PriceResult] = []

    def _sleep(self, a=1.5, b=3.5):
        time.sleep(random.uniform(a, b))

    def _enrich(self, r: PriceResult) -> PriceResult:
        if not r.quantity_display:
            r.quantity_display = extract_quantity_display(r.product_name)
        if not r.brand:
            r.brand = extract_brand(r.product_name)
        return r

    @abstractmethod
    def search_product(self, product: dict) -> list[PriceResult]:
        raise NotImplementedError

    def scrape_all(self, products: list[dict]) -> list[PriceResult]:
        self.results = []
        for i, product in enumerate(products, 1):
            self.logger.info(f"[{i}/{len(products)}] '{product['name']}' en {self.STORE_NAME}...")
            try:
                found = self.search_product(product)
                found = [self._enrich(r) for r in found]
                self.results.extend(found)
                self.logger.info(f"  → {len(found)} resultado(s)")
            except Exception as e:
                self.logger.warning(f"  → Error: {e}")
            self._sleep()
        return self.results

    def save_results(self, path: str):
        data = {"store": self.STORE_NAME, "scraped_at": str(date.today()),
                "count": len(self.results),
                "results": [r.to_dict() for r in self.results]}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        self.logger.info(f"Guardados {len(self.results)} en {path}")
