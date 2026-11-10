import re

h = open("logs/results_dom.html", encoding="utf-8", errors="ignore").read()

print("== ESTRUCTURA DE UNA FILA (primer mat-row completo) ==")
filas = re.findall(r'<mat-row[^>]*>.*?</mat-row>', h, re.S)
print("mat-row completas:", len(filas))
if filas:
    fila = filas[0]
    # limpiar espacios
    fila_limpia = re.sub(r'\s+', ' ', fila)
    print(fila_limpia[:3000])

print("\n== COLUMNAS (mat-cell con nombres) ==")
cols = re.findall(r'<mat-cell[^>]*class="([^"]*)"', h)
print(sorted(set(cols))[:20])

print("\n== CHECKBOX MARCA ==")
for m in re.finditer(r'<mat-checkbox[^>]*>', h):
    tag = m.group(0).replace("\n", " ")
    if "marc" in tag.lower() or "mArc".lower():
        pass
print("primeros 3 mat-checkbox attrs:")
for i, m in enumerate(re.finditer(r'<mat-checkbox[^>]{0,300}>', h)):
    print(" ", i, re.sub(r'\s+', ' ', m.group(0))[:250])
    if i >= 3:
        break

print("\n== ICONOS/BOTONES DE EXPORTACIÓN ==")
for m in re.finditer(r'.{250}(?i)(xml|download_dte|exporta).{250}', h):
    frag = re.sub(r'\s+', ' ', m.group(0))
    print(frag[:500])
    print('-----')
