"""Navegador para la página de destino (Fase 3).

Idéntico en esencia al de SAT: Chromium con sesión persistente para
evitar logins repetidos. No se conecta a ninguna URL hasta que
config/settings.yaml/destination dicte la plataforma real.
"""
import logging
from pathlib import Path

from playwright.sync_api import BrowserContext, Page, sync_playwright

logger = logging.getLogger(__name__)


class DestinationBrowser:
    def __init__(self, headless: bool, session_path: Path):
        self.headless = headless
        self.session_path = Path(session_path)
        self._pw = None
        self._context: BrowserContext | None = None
        self.page: Page | None = None

    def start(self) -> None:
        self._pw = sync_playwright().start()
        launch = self._pw.chromium.launch(headless=self.headless)
        opts = {"viewport": {"width": 1366, "height": 850},
                "locale": "es-GT"}
        if self.session_path.exists():
            logger.info("Reutilizando sesión del destino")
            opts["storage_state"] = str(self.session_path)
        self._context = launch.new_context(**opts)
        self.page = self._context.new_page()

    def save_state(self) -> None:
        if self._context is None:
            return
        self.session_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._context.storage_state(path=str(self.session_path))
        except Exception as exc:
            logger.warning("Sesión del destino no guardada: %s", exc)

    def close(self) -> None:
        if self._context is not None:
            try:
                self._context.close()
            except Exception:
                pass
        if self._pw is not None:
            try:
                self._pw.stop()
            except Exception:
                pass
        self._context = None
        self.page = None
        self._pw = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
