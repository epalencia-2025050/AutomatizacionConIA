"""Módulo de destino: Odoo (Fase 3 real).

Login: selectors estándar de Odoo (iguales en self-hosted y Odoo Online
en la página /web/login) - VERIFICADOS contra el base_theme de Odoo:
  <input name="login">
  <input name="password">
  <button type="submit">
Registro de facturas: flujo configurable en config/selectors.yaml ->
destination.odoo, con valores POR CONFIRMAR contra la instancia real
(según versión Odoo 16/17/18 y app Contabilidad o Facturación).
"""
import logging
import os
from pathlib import Path

from playwright.sync_api import TimeoutError as PWTimeout

from src.destination.module import (DestinationModule, NoConfiguradoError,
                                    ResultadoEnvio)

logger = logging.getLogger(__name__)

# Selectores del login estándar de Odoo (todas las versiones recientes)
ODOO_LOGIN_SELECTORS = {
    "url": "/web/login",
    "user_field": 'input[name="login"]',
    "password_field": 'input[name="password"]',
    "submit_button": 'button[type="submit"]',
    "user_menu": "span.o_avatar, .o_user_menu",
}

CAMPOS_OBLIGATORIOS = ("campos", "crear_btn", "guardar_btn")


class OdooDestinationModule(DestinationModule):
    """Plug-in destino Odoo: captura de facturas de proveedor (account.move)."""

    name = "odoo"

    def __init__(self, settings: dict, selectors: dict, browser=None):
        self.settings = settings
        self.dest = settings.get("destination") or {}
        self.sel_odoo = (selectors.get("destination") or {}).get("odoo") or {}
        self.browser = browser
        self.page = browser.page if browser is not None else None
        self.configurado = self._configurado_completo()

    # ------------------------------------------------------------------
    def _configurado_completo(self) -> bool:
        """Configuración mínima: URL de instancia + toggles del envío.

        El login no exige nada extra (selectors estándar); el envío exige
        mapping de campos y botones definidos por el usuario.
        """
        if not self.dest.get("habilitado") or not (self.dest.get("url") or "").strip():
            return False
        envio = self.sel_odoo.get("envio") or {}
        if not envio.get("campos"):
            return False
        return all((envio.get(k) or "").strip() for k in CAMPOS_OBLIGATORIOS[1:])

    # ------------------------------------------------------------------
    def login(self) -> None:
        if not (self.dest.get("url") or "").strip():
            raise NoConfiguradoError(
                "Odoo destino sin url: pega en settings.yaml "
                "destination.url la URL completa de tu instancia "
                "(ej. https://empresa.odoo.com)")
        base = self.dest["url"].rstrip("/")
        timeout = int((self.dest.get("timeouts") or {}).get("login_ms", 30000))
        url_login = f"{base}{ODOO_LOGIN_SELECTORS['url']}"
        logger.info("Abriendo login Odoo: %s", url_login)
        self.page.goto(url_login, timeout=timeout, wait_until="domcontentloaded")

        user = os.getenv("DEST_USER", "")
        password = os.getenv("DEST_PASSWORD", "")
        if not user or not password:
            raise ValueError("DEST_USER (email Odoo) y DEST_PASSWORD en .env")

        if self._logged_in():
            logger.info("Sesión Odoo vigente; se omite login")
            if self.browser is not None:
                self.browser.save_state()
            return

        self.page.fill(ODOO_LOGIN_SELECTORS["user_field"], user, timeout=timeout)
        self.page.fill(ODOO_LOGIN_SELECTORS["password_field"], password, timeout=timeout)

        # self-hosted con varias bases de datos: selector de BD opcional
        db_field = (self.sel_odoo.get("database_field") or "").strip()
        db_name = os.getenv("DEST_DB", "")
        if db_field and db_name:
            self.page.fill(db_field, db_name, timeout=timeout)

        self.page.click(ODOO_LOGIN_SELECTORS["submit_button"], timeout=timeout)
        try:
            self.page.wait_for_selector(ODOO_LOGIN_SELECTORS["user_menu"],
                                        timeout=timeout)
        except PWTimeout:
            err = self.page.locator(".oe_login_form p.alert, .alert-danger")
            detalle = err.first.inner_text().strip() if err.count() else "s/d"
            self.page.screenshot(path=f"logs/odoo_login_error_{int(__import__('time').time())}.png")
            raise PermissionError(f"Login Odoo rechazado: {detalle}")

        if self.browser is not None:
            self.browser.save_state()
        logger.info("Login en Odoo exitoso")

    def _logged_in(self) -> bool:
        try:
            return self.page.locator(ODOO_LOGIN_SELECTORS["user_menu"])\
                .first.is_visible()
        except Exception:
            return False

    # ------------------------------------------------------------------
    def enviar(self, factura: dict, xml_path=None, pdf_path=None) -> ResultadoEnvio:
        """Crea una factura/proyecto de proveedor y adjunta XML + PDF.

        Los pasos: abrir app -> Nueva -> llenar campos -> adjuntar
        archivos -> Guardar. Todo definido en config/selectors.yaml ->
        destination.odoo (sel_odoo).
        """
        if not self.configurado:
            raise NoConfiguradoError("Odoo: envío sin mapear a la app real")
        envio = self.sel_odoo.get("envio") or {}
        adjuntos = self.sel_odoo.get("adjuntos") or {}
        timeout = int((self.dest.get("timeouts") or {}).get("timeout_ms", 20000))

        try:
            for paso in envio.get("menu_path", []):
                self.page.locator(paso).first.click(timeout=timeout)
                self.page.wait_for_load_state("domcontentloaded")

            self.page.locator(envio["crear_btn"]).first.click(timeout=timeout)
            self.page.wait_for_timeout(1500)   # Odoo renderiza el form async

            # campo formulario : valor (Many2one se llena + Enter)
            for campo, selector in (envio["campos"] or {}).items():
                valor = factura.get(campo)
                if valor is None:
                    continue
                campo_el = self.page.locator(selector).first
                campo_el.click(timeout=timeout)
                campo_el.fill(str(valor), timeout=timeout)
                if (envio.get("campos_many2one") or {}).get(campo):
                    self.page.keyboard.press("Enter")
                    self.page.wait_for_timeout(600)

            for archivo in (xml_path, pdf_path):
                if archivo and Path(str(archivo)).exists() and adjuntos.get("input_archivo"):
                    self.page.set_input_files(adjuntos["input_archivo"],
                                              str(archivo), timeout=timeout)

            self.page.locator(envio["guardar_btn"]).first.click(timeout=timeout)
            self.page.wait_for_timeout(1500)

            ok_conf = envio.get("confirmacion_selector") or ""
            if ok_conf and self.page.locator(ok_conf).count():
                return (ResultadoEnvio.SIN_CONFIRMACION if not
                        self.verificar(factura.get("uuid") or "")
                        else ResultadoEnvio.SUBIDA)
            return (ResultadoEnvio.SIN_CONFIRMACION if not
                    self.verificar(factura.get("uuid") or "")
                    else ResultadoEnvio.SUBIDA)
        except PWTimeout as exc:
            logger.error("Odoo envío no respondió: %s", exc)
            if self.page is not None:
                self.page.screenshot(path=f"logs/odoo_envio_error_{factura.get('uuid','x')}.png")
            return ResultadoEnvio.ERROR
        except Exception as exc:   # pylint: disable=broad-except
            logger.exception("Fallo de envío a Odoo: %s", exc)
            return ResultadoEnvio.ERROR

    # ------------------------------------------------------------------
    def verificar(self, uuid: str) -> bool:
        """Verifica que el registro existe por búsqueda (URL con {uuid})."""
        envio = self.sel_odoo.get("envio") or {}
        url = (envio.get("verificacion_url") or "").strip()
        persona_sel = (envio.get("verificacion_selector") or "").strip()
        if (not url and not persona_sel) or not uuid:
            return False
        try:
            if url:
                self.page.goto(url.replace("{uuid}", uuid),
                               wait_until="domcontentloaded")
            if persona_sel:
                for s in persona_sel.split("|"):
                    if self.page.locator(s.strip()).count() > 0:
                        return True
                return False
            return True
        except Exception:   # pylint: disable=broad-except
            return False
