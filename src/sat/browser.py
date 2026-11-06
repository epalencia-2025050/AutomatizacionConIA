"""Gestión de navegadores: creación y configuración de sesiones."""
import os
from pathlib import Path

from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright


class BrowserManager:
    """Crea y administra instancias del navegador."""

    def __init__(self):
        self._playwright = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None

    @property
    def headless(self) -> bool:
        return os.getenv("HEADLESS", "true").lower() == "true"

    def start(self) -> None:
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=self.headless)
        self._context = self._browser.new_context(
            viewport={"width": 1280, "height": 800},
            accept_downloads=True,
            locale="es-MX",
        )

    def new_page(self) -> Page:
        if self._context is None:
            self.start()
        return self._context.new_page()

    def save_state(self, path: str = "storage/sat_state.json") -> None:
        """Guarda el estado de sesión para reutilizarlo (evitar re-login)."""
        if self._context:
            path_obj = Path(path)
            path_obj.parent.mkdir(parents=True, exist_ok=True)
            self._context.storage_state(path=str(path_obj))

    def load_state(self, path: str) -> bool:
        """Intenta crear el contexto a partir de una sesión previa."""
        if not Path(path).exists():
            return False
        self._context = self._browser.new_context(
            storage_state=path, accept_downloads=True, locale="es-MX"
        )
        return True

    def stop(self) -> None:
        for resource in (self._context, self._browser, self._playwright):
            if resource:
                try:
                    resource.close()
                except Exception:
                    pass
        self._playwright = None
        self._browser = None
        self._context = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
