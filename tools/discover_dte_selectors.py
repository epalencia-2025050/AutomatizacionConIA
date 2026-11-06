"""Herramienta de descubrimiento para la pantalla interna "Consultar DTE".

¿Para qué sirve?
La interfaz "Consultar DTE" solo es accesible tras iniciar sesión con
2FA, por lo que sus selectores no pudieron verificarse automáticamente.
Este script:
 1. abre Chromium visible con la página de login de Agencia Virtual;
 2. espera a que TÚ completes login + código 2FA (la sesión se guarda);
 3. navega al módulo y, bajo un menú interactivo, inspecciona la
    página actual y exporta un resumen DOM a tools/dte_dom_snapshot.json;
 4. muestra inputs/selects/botones/tables con sus IDs y textos para que
    copies los selectores definitivos en config/selectors.yaml.

Ejecución:
  python tools/discover_dte_selectors.py [--url URL_MODULO]
"""
import argparse
import json
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "tools" / "dte_dom_snapshot.json"


def resumen_dom(page) -> dict:
    def info(sel):
        datos = []
        for el in page.query_selector_all(sel)[:60]:
            texto = ""
            try:
                texto = (el.inner_text() or el.get_attribute("value") or "").strip()
            except Exception:
                pass
            datos.append({
                "id": el.get_attribute("id"),
                "name": el.get_attribute("name"),
                "type": el.get_attribute("type"),
                "texto": texto[:80],
            })
        return datos

    return {
        "url": page.url,
        "inputs": info("input"),
        "selects": info("select"),
        "labels": info("label"),
        "buttons": info("button"),
        "links": [l for l in info("a") if l.get("texto")],
        "tablas_con_filas": [
            {"filas": len(t.query_selector_all("tbody tr")),
             "cabecera": [c.inner_text().strip()
                          for fila in t.query_selector_all("tr")[:1]
                          for c in fila.query_selector_all("th, td")]}
            for t in page.query_selector_all("table")
        ][:10],
    }


def esperar_login(page, timeout_s=360):
    print("Completa el login (NIT, contraseña y código 2FA) en la ventana del navegador.")
    print(f"Esperando hasta {timeout_s}s hasta que la sesión esté lista...")
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if "login.jsf" not in page.url and not page.locator("#loginFormulario").count():
            print("Login detectado como completado\n")
            return True
        time.sleep(1.5)
    return False


def simulado_descubrimiento(page, url_modulo=None):
    if url_modulo:
        page.goto(url_modulo, wait_until="domcontentloaded")
    else:
        resp = input("Pega la URL del módulo 'Consultar DTE' si la conoces "
                     "(intro para omitir): ").strip()
        if resp:
            page.goto(resp, wait_until="domcontentloaded")

    while True:
        accion = input("\n[n]avegar / [i]nspeccionar / [s]alir: ").strip().lower()
        if accion == "n":
            nueva = input("URL a navegar: ").strip()
            if nueva:
                page.goto(nueva, wait_until="domcontentloaded")
        elif accion == "i":
            datos = resumen_dom(page)
            SNAPSHOT.write_text(json.dumps(datos, ensure_ascii=False, indent=2),
                                encoding="utf-8")
            print(f"DOM capturado -> {SNAPSHOT}")
            print(json.dumps(datos, ensure_ascii=False, indent=2)[:3000])
        elif accion == "s":
            break


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", help="URL del módulo Consultar DTE (opcional)")
    parser.add_argument("--headful", action="store_true", default=True)
    args = parser.parse_args()

    sys.path.insert(0, str(ROOT))
    import yaml
    settings = yaml.safe_load(open(ROOT / "config/settings.yaml", encoding="utf-8"))
    session = ROOT / "storage" / "sat_av_state.json"

    with sync_playwright() as pw:
        ctx_opts = {"viewport": {"width": 1366, "height": 850},
                    "locale": "es-GT", "timezone_id": "America/Guatemala"}
        if session.exists():
            ctx_opts["storage_state"] = str(session)
            print("Reutilizando sesión previa si sigue vigente...")
        context = pw.chromium.launch(headless=False).new_context(**ctx_opts)
        page = context.new_page()
        page.goto("https://farm3.sat.gob.gt/menu/login.jsf",
                  wait_until="domcontentloaded")
        if not esperar_login(page):
            print("Timeout esperando login manual")
            return 1
        context.storage_state(path=str(session))
        simulado_descubrimiento(page, args.url)
        context.storage_state(path=str(session))
        context.close()
    print("Sesión guardada; ya puedes usarla con python main.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
