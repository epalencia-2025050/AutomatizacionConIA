import re

h = open("logs/results_dom.html", encoding="utf-8", errors="ignore").read()

print("== CELDA MENU DE LA PRIMERA FILA (completa) ==")
filas = re.findall(r'<mat-row[^>]*>.*?</mat-row>', h, re.S)
fila = filas[0]
m = re.search(r'<mat-cell[^>]*cdk-column-menu.*?</mat-cell>', fila, re.S)
if m:
    print(re.sub(r"\s+", " ", m.group(0))[:2500])

print("\n== APARICIONES 'xml' (contexto) ==")
for i, m in enumerate(re.finditer(r'(?:[Xx][Mm][Ll])', h)):
    ini = max(0, m.start() - 200)
    frag = re.sub(r"\s+", " ", h[ini:m.end() + 200])
    print(f"--- #{i}: ...{frag}...")
    print()
    if i >= 4:
        break

print("\n== BOTONES con aria-haspopup o títulos en la página ==")
for i, m in enumerate(re.finditer(r'<(?:button|a)[^>]{0,350}(?:title[^>]{0,80}|aria-[a-z]+[^>]{0,80})[^>]*>', h)):
    tag = re.sub(r"\s+", " ", m.group(0))
    if any(k in tag.lower() for k in ("xml", "pdf", "excel", "download", "export", "descarg")):
        print(" ", tag[:300])
    if i > 200:
        break

print("\n== MAT-PAGINATOR / total filas ==")
mm = re.search(r'mat-paginator.*?</div>', h, re.S)
if mm:
    print(re.sub(r"\s+", " ", mm.group(0))[:600])
