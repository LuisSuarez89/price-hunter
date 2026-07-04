# 🛒 SOS Price Hunter

Sistema automatizado de comparación de precios para supermercados colombianos.
Se ejecuta el **día 25 de cada mes** vía GitHub Actions y envía un reporte por email
indicando qué comprar en cada almacén al mejor precio.

## Tiendas soportadas
- 🔴 D1
- 🟠 Ara
- 🔵 Alkosto
- 🟢 Makro

---

## Setup en 5 pasos

### 1. Crear repositorio en GitHub
```bash
git clone https://github.com/TU_USUARIO/sos-price-hunter.git
cd sos-price-hunter
```

### 2. Configurar los Secrets en GitHub
Ve a **Settings → Secrets and variables → Actions → New repository secret**:

| Secret | Valor |
|---|---|
| `EMAIL_SENDER` | Tu correo Gmail (ej. `tuemail@gmail.com`) |
| `EMAIL_RECIPIENT` | Correo donde recibes el reporte (puede ser el mismo) |
| `EMAIL_PASSWORD` | **App Password de Gmail** (no tu contraseña normal) |

> Para crear un App Password de Gmail:
> Gmail → Cuenta → Seguridad → Verificación en 2 pasos → Contraseñas de aplicaciones
> Nombre: "SOS Price Hunter" → Copiar la contraseña de 16 caracteres generada

### 3. Subir el código
```bash
git add .
git commit -m "feat: inicial SOS Price Hunter"
git push origin main
```

### 4. Probar manualmente
En GitHub → Actions → "SOS Price Hunter" → "Run workflow"

### 5. Actualizar tu canasta mensual
Edita `data/my_products.json` para agregar, quitar o modificar productos.
Edita `data/manual_d1.json` cuando cambien precios en D1 (actualización mensual rápida).

---

## Estructura del proyecto

```
sos-price-hunter/
├── .github/
│   └── workflows/
│       └── price_hunter.yml      # cron día 25
├── scrapers/
│   ├── base_scraper.py           # clase base — heredar para nuevas tiendas
│   ├── scraper_d1.py
│   ├── scraper_ara.py
│   ├── scraper_alkosto.py
│   └── scraper_makro.py
├── data/
│   ├── my_products.json          # TU canasta de referencia ← editar esto
│   ├── manual_d1.json            # precios manuales fallback D1
│   └── raw/                      # resultados de scrapers (generado automático)
├── reports/                      # reportes HTML generados
├── main.py                       # orquestador del pipeline
├── comparador.py                 # normalización y comparación de precios
├── report_generator.py           # genera HTML y envía email
└── requirements.txt
```

---

## Agregar una nueva tienda

1. Crea `scrapers/scraper_nueva_tienda.py` heredando de `BaseScraper`
2. Define `STORE_NAME` y `search_product()`
3. Agrega la clase a `SCRAPERS` en `main.py`
4. Agrega el color/emoji en `STORE_LABELS` en `report_generator.py`

---

## Cómo funciona el precio normalizado

Para comparar productos con distintas presentaciones, el comparador
normaliza todo a una unidad común:

| Tipo | Normalización |
|---|---|
| Productos en gramos/kg | precio por 100g |
| Líquidos (aceite, detergente) | precio por litro |
| Unidades empacadas | precio por unidad |

El comparador extrae el gramaje del nombre del producto automáticamente
(ej. "Arroz 5kg" → 5000g → precio/100g).

---

## Correr localmente

```bash
pip install -r requirements.txt

# Pipeline completo
python main.py

# Solo tiendas específicas
python main.py --stores d1,alkosto

# Solo comparar (sin scrapear de nuevo)
python main.py --skip-scraping

# Sin enviar email
python main.py --skip-email
```
