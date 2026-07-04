"""
scripts/summary.py
Genera el resumen Markdown para GitHub Actions Step Summary.
Se llama desde el workflow: python scripts/summary.py >> $GITHUB_STEP_SUMMARY
"""
import json
import glob

print("## Resultados SOS Price Hunter")
print("")

files = glob.glob("data/comparison_*.json")
if not files:
    print("No se encontraron archivos de comparacion.")
else:
    with open(sorted(files)[-1]) as f:
        d = json.load(f)
    print(f"- Productos comparados: {d['products_compared']}")
    print(f"- Tiendas encontradas: {', '.join(d['stores_found'])}")
    savings = d['total_savings_estimate']
    print(f"- Ahorro estimado comprando al mejor precio: ${savings:,.0f} COP")
    print("")
    print("### Mejor tienda por producto")
    for store, pids in d.get("by_store", {}).items():
        print(f"- **{store.upper()}**: {len(pids)} producto(s)")
