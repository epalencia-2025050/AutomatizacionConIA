"""Login genérico en la plataforma destino (Fase 3).

Todo lo que hace se define en config (URLs y selectores en
config/selectors.yaml -> destination.login). Mientras esos campos
estén vacíos, esta clase LANZA error y el orquestador no toca nada
(regla del diseño: no inventar formularios).
"""
import logging
import os

from playwright.sync_api import Page

from src.destination.module import NoConfiguradoError

logger = logging.getLogger(__name__)

CAMPOS_OBLIGATORIOS = ("url", "user_field", "password_field", "submit_button")


class DestinationAuthentication:
    def __init__(self, settings: dict, selectors: dict, browser=None):
        self.settings = settings
        self.selectors = selectors
        self.page: Page | None = None
        if browser is not None:
            self.page = browser.page

    def configurado(self) -> bool:
        dest = self.settings.get("destination") or {}
        if not dest.get("habilitado") or not (dest.get("url") or "").strip():
            return False
        sel = self.selectors.get("destination") or {}
        login = sel.get("login") or {}
        return all((login.get(k) or "").strip() for k in CAMPOS_OBLIGATORIOS[1:])

    # ------------------------------------------------------------------
    def login(self) -> Page:
        if not self.configurado():
            raise NoConfiguradoError(
                "Página destino NO configurada: llenar settings.yaml "
                "(destination) y selectors.yaml (destination.login) con la "
                "plataforma real. Ver README Fase 3.")
        dest = self.settings["destination"]
        sel = self.selectors["destination"]["login"]
        user = os.getenv("DEST_USER", "")
        password = os.getenv("DEST_PASSWORD", "")
        if not user or not password:
            raise ValueError("DEST_USER y DEST_PASSWORD deben ir en .env")

        timeout = int(dest.get("timeouts", {}).get("login_ms", 30000))
        logger.info("Abriendo destino %s", dest["url"])

        if self._already_logged_in(sel):
            logger.info("Sesión del destino vigente; se omite login")
            return self.page

        self.page.goto(dest["url"], timeout=timeout, wait_until="domcontentloaded")
        self.page.fill(sel["user_field"], user, timeout=timeout)
        self.page.fill(sel["password_field"], password, timeout=timeout)
        self.page.click(sel["submit_button"], timeout=timeout)
        self.page.wait_for_load_state("domcontentloaded")

        self._verify_login(sel)
        logger.info("Login en destino exitoso")
        return self.page

    # ------------------------------------------------------------------
    def _already_logged_in(self, sel) -> bool:
        try:
            return self.page.locator(sel["user_field"]).count() == 0
        except Exception:
            return False

    def _verify_login(self, sel) -> None:
        if self._already_logged_in(sel):
            return
        detalle = ""
        try:
            err = self.page.locator(sel.get("error_selector", "")) \
                if sel.get("error_selector") else None
            if err and err.first.is_visible():
                detalle = err.first.inner_text().strip()
        except Exception:
            pass
        raise PermissionError(f"Login en destino rechazado: {detalle or 'estado desconocido'}")
