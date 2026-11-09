"""Herramienta de descubrimiento para el módulo Odoo (Fase 3).

1. Abre Chromium a tu instancia Odoo.
2. Completa login manualmente si hace falta (2FA incluido).
3. Navega con [n] a la vista "Facturas de proveedor" y al form "Nueva".
4. [i] inspecciona la página: inputs con name/id, botones, breadcrumbs
   y versión de Odoo detectable; exporta tools/odoo_dom_snapshot.json.

Con la salida llena: config/selectors.yaml -> destination.odoo
"""
import argparse
import json
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "tools" / "odoo_dom_snapshot.json"


def resumen(page) -> dict:
    def info(sel):
        out = []
        for el in page.query_selector_all(sel)[:80]:
            val = ""
            try:
                val = (el.input_value() if sel == "input" else
                       el.inner_text())[:60] if sel != "input" else ""
            except Exception:
                val = ""
            out.append({"id": el.get_attribute("id"),
                        "name": el.get_attribute("name"),
                        "placeholder": el.get_attribute("placeholder"),
                        "type": el.get_attribute("type") or "",
                        "valor": val})
        return out

    version = ""
    try:
        version = page.locator("script:has-text('odoo.version')").count() and \
            "script odoo.version presente" or ""
        meta = page.locator("meta[name='generator']").first.get_attribute("content")
        version = version or meta or ""
    except Exception:
        pass
    return {
        "url": page.url,
        "version_hint": version,
        "inputs": info("input"),
        "textareas": info("textarea"),
        "botones": [{"texto": b.inner_text().strip()[:40],
                     "clases": (b.get_attribute("class") or "")[:60]}
                    for b in page.query_selector_all("button, .btn")][:60],
        "campos_formulario": [
            {"texto": l.inner_text().strip(),
             "for": l.get_attribute("for") or ""}
            for l in page.query_selector_all("label.o_form_label, label")][:60],
        "breadcrumbs": [b.inner_text().strip()
                        for b in page.query_selector_all(".o_breadcrumb a, nav a")][:20],
    }


def esperar_login(page, timeout_s=420):
    print("Completa el login (email + contrasena [+ 2FA si aplica]) en el navegador.")
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            if page.locator("span.o_avatar, .o_user_menu").count():
                print("Login OK\n")
                return True
        except Exception:
            pass
        time.sleep(1.5)
    return False


def main():
    p = argparse.ArgumentParser()
    p.add_argument("url", help="URL de la instancia Odoo (ej. https://empresa.odoo.com)")
    args = p.parse_args()

    session = ROOT / "storage" / "dest_state.json"
    with sync_playwright() as pw:
        opts = {"viewport": {"width": 1400, "height": 900}, "locale": "es-GT"}
        if session.exists():
            opts["storage_state"] = str(session)
        ctx = pw.chromium.launch(headless=False).new_context(**opts)
        page = ctx.new_page()
        page.goto(args.url.rstrip("/") + "/web/login", wait_until="domcontentloaded")
        if not esperar_login(page):
            print("Timmeout esperando login"); return 1
        ctx.storage_state(path=str(session))
        print("Sesión guardada. Navega con [n], inspecciona con [i], [s] al salir")
        while True:
            act = input("\n[n]avegar / [i]nspeccionar / [s]alir: ").strip().lower()
            if act == "n":
                dest = input("URL: ").strip()
                if dest:
                    page.goto(dest, wait_until="domcontentloaded")
            elif act == "i":
                datos = resumen(page)
                SNAPSHOT.write_text(json.dumps(datos, ensure_ascii=False, indent=2),
                                    encoding="utf-8")
                print(f"Snapshot -> {SNAPSHOT}\n")
                for seccion in ("inputs", "campos_formulario", "breadcrumbs"):
                    print(f"-- {seccion} --")
                    for item in (datos[seccion] or [])[:20]:
                        print(json.dumps(item, ensure_ascii=False))
            elif act == "s":
                break
        ctx.storage_state(path=str(session))
        ctx.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
