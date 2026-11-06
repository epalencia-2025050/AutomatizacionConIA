"""Gestión del navegador para el sistema destino."""
from playwright.sync_api import BrowserContext, Browser, Page, sync_playwright


class DestinationBrowser:
    """Crea y administra sesiones del navegador hacia el sistema destino."""

    def __init__(self):
        self._playwright = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self.page: Page | None = None

    def start(self, headless: bool = True) -> None:
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=headless)
        self._context = self._browser.new_context(
            viewport={"width": 1280, "height": 800},
            accept_downloads=True,
            locale="es-MX",
        )
        self.page = self._context.new_page()

    def close(self) -> None:
        for resource in (self._context, self._browser, self._playwright):
            if resource:
                try:
                    resource.close()
                except Exception:
                    pass
        self._playwright = None
        self._browser = None
        self._context = None
        self.page = None
