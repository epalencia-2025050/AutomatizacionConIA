"""Autenticación en el sistema destino."""
import logging
import os
import time

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout

logger = logging.getLogger(__name__)


class DestinationAuthentication:
    """Inicia sesión en el portal del sistema destino."""

    def __init__(self, settings: dict, selectors: dict):
        self.settings = settings["destination"]
        self.selectors = selectors["destination"]["login"]
        self.page: Page = Page

    def login(self, page: Page) -> Page:
        self.page = page
        user = os.getenv("DEST_USER", "")
        password = os.getenv("DEST_PASSWORD", "")
        if not user or not password:
            raise ValueError("DEST_USER y DEST_PASSWORD deben estar definidos en .env")

        url = self.settings["login_url"] or self.settings["portal_url"]
        timeout = self.settings["timeouts"].get("login", 30) * 1000
        logger.info("Abriendo sistema destino: %s", url)

        try:
            self.page.goto(url, timeout=timeout, wait_until="domcontentloaded")
            self._fill_form(user, password, timeout)
        except PlaywrightTimeout:
            logger.error("Timeout en login del sistema destino")
            self.page.screenshot(path=f"logs/dest_login_error_{int(time.time())}.png")
            raise

        logger.info("Login en el sistema destino exitoso")
        return self.page

    def _fill_form(self, user: str, password: str, timeout: int) -> None:
        s = self.selectors
        self.page.fill(s["user_input"], user, timeout=timeout)
        self.page.fill(s["password_input"], password, timeout=timeout)
        self.page.click(s["submit_button"], timeout=timeout)
        self.page.wait_for_load_state("domcontentloaded", timeout=timeout)
