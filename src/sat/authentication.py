"""Autenticación en el portal del SAT."""
import logging
import os
import time

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout

logger = logging.getLogger(__name__)


class SatAuthentication:
    """Maneja el login en https://portalcfdi.facturaelectronica.sat.gob.mx"""

    def __init__(self, settings: dict, selectors: dict):
        self.settings = settings
        self.selectors = selectors
        self.sat_settings = settings["sat"]
        self.page: Page = Page  # se asigna en login()

    def login(self, page: Page) -> Page:
        """Inicia sesión con RFC y contraseña desde variables de entorno."""
        self.page = page
        rfc = os.getenv("SAT_RFC", "")
        password = os.getenv("SAT_PASSWORD", "")
        if not rfc or not password:
            raise ValueError("SAT_RFC y SAT_PASSWORD deben estar definidos en .env")

        timeout = (self.sat_settings["timeouts"].get("login", 30)) * 1000
        logger.info("Abriendo portal del SAT...")
        page.goto(self.sat_settings["portal_url"], timeout=timeout, wait_until="domcontentloaded")

        if self._session_valid():
            logger.info("Sesión existente válida, se omite login")
            return self.page

        try:
            self._fill_login_form(rfc, password, timeout)
            self._verify_login(timeout)
        except PlaywrightTimeout:
            logger.error("Timeout en el login del SAT")
            screenshot = f"logs/sat_login_error_{int(time.time())}.png"
            page.screenshot(path=screenshot)
            logger.info("Captura de pantalla de error: %s", screenshot)
            raise

        logger.info("Autenticación en el SAT exitosa")
        return self.page

    def _session_valid(self) -> bool:
        """Detecta si el navegador conserva la sesión activa."""
        return "ListaRecibidos" in self.page.url or self.page.query_selector(
            self.selectors["menu"]["received_tab"]
        )

    def _fill_login_form(self, rfc: str, password: str, timeout: int) -> None:
        s = self.selectors["login"]
        self.page.fill(s["rfc_input"], rfc, timeout=timeout)
        self.page.fill(s["password_input"], password, timeout=timeout)
        self.page.click(s["submit_button"], timeout=timeout)
        # Esperar que el portal regrese después de validar
        self.page.wait_for_load_state("domcontentloaded", timeout=timeout)

    def _verify_login(self, timeout: int) -> None:
        s = self.selectors["login"]
        if self.page.query_selector(s["alert_error"]):
            error_text = self.page.inner_text(s["alert_error"]).strip()
            raise PermissionError(f"Login del SAT rechazado: {error_text}")
        # Confirmar llegada a la bandeja de facturas recibidas
        self.page.wait_for_selector(
            self.selectors["menu"]["received_tab"], timeout=timeout
        )
