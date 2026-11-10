"""Herramienta de descubrimiento e inspección para "Consultar DTE" en Agencia Virtual.

¿Para qué sirve?
La consulta DTE no tiene una URL independiente: se encuentra integrada
dentro de la misma página de Agencia Virtual tras navegar por el menú
(ej. https://farm3.sat.gob.gt/menu/portada.jsf o módulos asociados).

Este script:
 1. Abre Chromium visible y carga la sesión guardada (si existe);
 2. Si no hay sesión o expiró, espera a que ingreses credenciales + 2FA;
 3. Te permite navegar interactivamente en el navegador hasta la pantalla
    de "CONSULTA DE DTE";
 4. Inspecciona tanto la página principal como TODOS los iframes/frames presentes;
 5. Identifica y descubre los elementos clave solicitados:
    - Tipo de Operación: selección de "Recibidos" (radio, select, dropdown)
    - Fecha de Emisión: campo Desde
    - Fecha de Emisión: campo Hasta
    - Botón Buscar
    - Contenedor / tabla de resultados debajo del formulario
 6. Guarda los hallazgos en tools/dte_dom_snapshot.json y muestra en consola
    los selectores recomendados para config/selectors.yaml.

Ejecución:
  python tools/discover_dte_selectors.py
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "tools" / "dte_dom_snapshot.json"


def extraer_info_elementos(contexto, tag: str, max_items: int = 100) -> list[dict]:
    """Extrae atributos clave de elementos en una página o frame."""
    datos = []
    try:
        elementos = contexto.query_selector_all(tag)[:max_items]
    except Exception:
        return datos

    for el in elementos:
        try:
            texto = (el.inner_text() or el.get_attribute("value") or el.get_attribute("title") or "").strip()
            datos.append({
                "tag": tag,
                "id": el.get_attribute("id") or "",
                "name": el.get_attribute("name") or "",
                "type": el.get_attribute("type") or "",
                "class": el.get_attribute("class") or "",
                "value": el.get_attribute("value") or "",
                "placeholder": el.get_attribute("placeholder") or "",
                "aria_label": el.get_attribute("aria-label") or "",
                "onclick": (el.get_attribute("onclick") or "")[:120],
                "texto": texto[:100],
            })
        except Exception:
            continue
    return datos


def analizar_contexto(ctx, nombre_contexto: str, url_contexto: str) -> dict:
    """Inspecciona una página o frame específico y detecta candidatos DTE."""
    inputs = extraer_info_elementos(ctx, "input")
    selects = extraer_info_elementos(ctx, "select")
    buttons = extraer_info_elementos(ctx, "button")
    labels = extraer_info_elementos(ctx, "label")
    links = [l for l in extraer_info_elementos(ctx, "a") if l.get("texto")]

    # Detectar campos de fecha
    candidatos_desde = []
    candidatos_hasta = []
    candidatos_fechas_genericos = []
    for inp in inputs:
        txt_full = f"{inp['id']} {inp['name']} {inp['placeholder']} {inp['value']}".lower()
        if any(w in txt_full for w in ["desde", "ini", "start", "from"]):
            candidatos_desde.append(inp)
        elif any(w in txt_full for w in ["hasta", "fin", "end", "to"]):
            candidatos_hasta.append(inp)
        elif any(w in txt_full for w in ["fecha", "date", "fec"]):
            candidatos_fechas_genericos.append(inp)

    # Detectar tipo de operación (Recibidos / Emitidos)
    candidatos_operacion = []
    for s in selects:
        txt_full = f"{s['id']} {s['name']}".lower()
        if any(w in txt_full for w in ["operacion", "tipo", "recibido", "emision"]):
            candidatos_operacion.append(s)
    # También buscar radios o checkboxes o etiquetas con "recibido"
    for inp in inputs:
        if inp["type"] in ["radio", "checkbox"] or "recib" in f"{inp['id']} {inp['name']} {inp['value']}".lower():
            candidatos_operacion.append(inp)
    for lbl in labels:
        if "recib" in lbl["texto"].lower() or "operac" in lbl["texto"].lower():
            candidatos_operacion.append({"tag": "label", **lbl})

    # Detectar botón buscar
    candidatos_buscar = []
    for btn in buttons + [i for i in inputs if i["type"] in ["button", "submit"]] + links:
        txt_full = f"{btn.get('id', '')} {btn.get('name', '')} {btn.get('value', '')} {btn.get('texto', '')}".lower()
        if "buscar" in txt_full or "search" in txt_full or "consultar" in txt_full:
            candidatos_buscar.append(btn)

    # Detectar tablas de resultados
    tablas = []
    try:
        for t in ctx.query_selector_all("table")[:15]:
            filas_tbody = len(t.query_selector_all("tbody tr"))
            filas_total = len(t.query_selector_all("tr"))
            cabeceras = [
                c.inner_text().strip()
                for fila in t.query_selector_all("tr")[:2]
                for c in fila.query_selector_all("th, td")
                if c.inner_text().strip()
            ]
            t_id = t.get_attribute("id") or ""
            t_class = t.get_attribute("class") or ""
            tablas.append({
                "id": t_id,
                "class": t_class,
                "filas_tbody": filas_tbody,
                "filas_total": filas_total,
                "cabeceras": cabeceras[:10],
            })
    except Exception:
        pass

    return {
        "contexto": nombre_contexto,
        "url": url_contexto,
        "candidatos_dte": {
            "tipo_operacion": candidatos_operacion,
            "fecha_desde": candidatos_desde,
            "fecha_hasta": candidatos_hasta,
            "fechas_genericas": candidatos_fechas_genericos,
            "boton_buscar": candidatos_buscar,
            "tablas_resultados": tablas,
        },
        "detalles": {
            "inputs": inputs,
            "selects": selects,
            "buttons": buttons,
            "labels": labels,
            "links": links[:40],
        }
    }


def inspeccionar_todo(page) -> dict:
    """Inspecciona la página principal y cada iframe hijo."""
    resultados = {
        "pagina_url": page.url,
        "pagina_titulo": page.title(),
        "marcos": [],
    }

    # 1. Página principal
    print(f"\n--- Analizando Documento Principal ({page.url}) ---")
    res_main = analizar_contexto(page, "main_frame", page.url)
    resultados["marcos"].append(res_main)

    # 2. Frames / iframes
    frames = page.frames
    print(f"Total frames/iframes detectados: {len(frames)}")
    for i, frame in enumerate(frames):
        if frame == page.main_frame:
            continue
        nombre = frame.name or f"iframe_{i}"
        f_url = frame.url or "(sin url)"
        print(f"--- Analizando iframe [{i}]: name='{frame.name}' url={f_url} ---")
        res_frame = analizar_contexto(frame, f"iframe_{nombre}", f_url)
        resultados["marcos"].append(res_frame)

    return resultados


def imprimir_resumen_candidatos(snapshot_data: dict) -> None:
    """Muestra un reporte amigable en terminal con los selectores encontrados."""
    print("\n" + "=" * 70)
    print(" RESUMEN DE ELEMENTOS DETECTADOS PARA 'CONSULTA DE DTE'")
    print("=" * 70)

    encontrado_en_alguno = False
    for item in snapshot_data.get("marcos", []):
        ctx = item["contexto"]
        cands = item.get("candidatos_dte", {})
        op = cands.get("tipo_operacion", [])
        desde = cands.get("fecha_desde", [])
        hasta = cands.get("fecha_hasta", [])
        f_gen = cands.get("fechas_genericas", [])
        btn = cands.get("boton_buscar", [])
        tabs = cands.get("tablas_resultados", [])

        tiene_elementos = bool(op or desde or hasta or f_gen or btn or tabs)
        if not tiene_elementos:
            continue

        encontrado_en_alguno = True
        print(f"\n[+] En el contexto: {ctx} (URL: {item['url']})")

        print("  * Tipo de Operación (Recibidos):")
        if op:
            for el in op[:5]:
                print(f"    - tag={el.get('tag')} id='{el.get('id')}' name='{el.get('name')}' texto='{el.get('texto')}'")
        else:
            print("    (No se detectó un campo obvio con 'recibido' u 'operacion')")

        print("  * Fecha Emisión - DESDE:")
        if desde:
            for el in desde[:3]:
                print(f"    - id='{el.get('id')}' name='{el.get('name')}' placeholder='{el.get('placeholder')}'")
        elif f_gen:
            print("    (Candidatos genéricos de fecha):")
            for el in f_gen[:3]:
                print(f"    - id='{el.get('id')}' name='{el.get('name')}'")
        else:
            print("    (No detectado)")

        print("  * Fecha Emisión - HASTA:")
        if hasta:
            for el in hasta[:3]:
                print(f"    - id='{el.get('id')}' name='{el.get('name')}' placeholder='{el.get('placeholder')}'")
        elif len(f_gen) > 1:
            print("    (Segundo candidato genérico de fecha):")
            print(f"    - id='{f_gen[1].get('id')}' name='{f_gen[1].get('name')}'")
        else:
            print("    (No detectado)")

        print("  * Botón Buscar:")
        if btn:
            for el in btn[:3]:
                print(f"    - tag={el.get('tag')} id='{el.get('id')}' name='{el.get('name')}' texto='{el.get('texto')}' value='{el.get('value')}'")
        else:
            print("    (No detectado)")

        print("  * Tablas / Resultados:")
        if tabs:
            for t in tabs[:3]:
                print(f"    - id='{t.get('id')}' class='{t.get('class')}' filas={t.get('filas_tbody')} cabeceras={t.get('cabeceras')}")
        else:
            print("    (No detectadas aún o tabla vacía)")

    if not encontrado_en_alguno:
        print("\nNo se detectaron elementos específicos de DTE en los marcos actuales.")
        print("Asegúrate de estar en la vista donde se muestra el formulario de CONSULTA DE DTE.")

    print("\n" + "=" * 70)


def esperar_login_o_sesion(page, timeout_s=360):
    print("\nVerificando estado de inicio de sesión...")
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        url = page.url
        login_card = False
        try:
            login_card = page.locator("#loginFormulario").is_visible()
        except Exception:
            pass

        if "login.jsf" not in url and not login_card:
            print("Sesión activa o login completado exitosamente.\n")
            return True
        time.sleep(1.5)
    return False


def bucle_interactivo(page):
    print("\n=======================================================")
    print(" INSTRUCCIONES:")
    print(" 1. En la ventana abierta del navegador, navega hasta el")
    print("    módulo 'CONSULTA DE DTE' (a través del menú de Agencia Virtual).")
    print(" 2. Cuando veas el formulario en pantalla (Tipo de Operación,")
    print("    Fechas Desde/Hasta, Botón Buscar), vuelve aquí.")
    print(" 3. Escribe 'i' y presiona Enter para inspeccionar el DOM.")
    print("=======================================================\n")

    while True:
        try:
            accion = input("\nOpciones: [i]nspeccionar / [u]rl actual / [s]alir: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            break

        if accion == "i":
            print("\nInspeccionando DOM y todos los iframes actuales...")
            snapshot = inspeccionar_todo(page)
            SNAPSHOT.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
            imprimir_resumen_candidatos(snapshot)
            print(f"\n[OK] Snapshot completo guardado en: {SNAPSHOT}")
        elif accion == "u":
            print(f"\nURL actual: {page.url}")
            print(f"Título: {page.title()}")
            print(f"Frames: {len(page.frames)}")
            for idx, fr in enumerate(page.frames):
                print(f"  Frame [{idx}]: name='{fr.name}', url={fr.url}")
        elif accion == "s":
            break


def main():
    parser = argparse.ArgumentParser(description="Descubridor de selectores de DTE")
    parser.add_argument("--headful", action="store_true", default=True)
    parser.parse_args()

    session = ROOT / "storage" / "sat_av_state.json"

    with sync_playwright() as pw:
        ctx_opts = {
            "viewport": {"width": 1366, "height": 850},
            "locale": "es-GT",
            "timezone_id": "America/Guatemala",
        }
        if session.exists():
            ctx_opts["storage_state"] = str(session)
            print("Cargando sesión guardada existente...")

        context = pw.chromium.launch(headless=False).new_context(**ctx_opts)
        page = context.new_page()

        print("Abriendo Agencia Virtual...")
        # Ir a la portada si ya hay sesión, o al login
        url_destino = "https://farm3.sat.gob.gt/menu/portada.jsf" if session.exists() else "https://farm3.sat.gob.gt/menu/login.jsf"
        page.goto(url_destino, wait_until="domcontentloaded")

        if not esperar_login_o_sesion(page):
            print("Tiempo de espera agotado para el login.")
            return 1

        # Guardar estado de sesión actualizado
        session.parent.mkdir(parents=True, exist_ok=True)
        context.storage_state(path=str(session))

        bucle_interactivo(page)

        # Guardar sesión al salir para mantenerla
        context.storage_state(path=str(session))
        context.close()

    print("Finalizado.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

