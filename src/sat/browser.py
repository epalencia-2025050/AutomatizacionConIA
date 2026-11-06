"""Gestión del navegador Chromium con sesión persistente de Agencia Virtual.

Uso en cabeza (visible) para Cloudflare y el segundo factor (2FA).
La sesión (cookies/localStorage) se guarda en un file JSON y se
reutiliza entre ejecuciones para evitar logins repetidos.
"""
import logging
from pathlib import Path

from playwright.sync_api import BrowserContext, Page, sync_playwright

logger = logging.getLogger(__name__)


class BrowserManager:
    def __init__(self, headless: bool, session_path: Path):
        self.headless = headless
        self.session_path = Path(session_path)
        self._playwright = None
        self._context: BrowserContext | None = None

    # ------------------------------------------------------------------
    @property
    def has_saved_session(self) -> bool:
        return self.session_path.exists()

    def start(self) -> None:
        self._playwright = sync_playwright().start()
        launch = self._playwright.chromium.launch(headless=self.headless)
        options = {
            "viewport": {"width": 1366, "height": 850},
            "locale": "es-GT",
            "timezone_id": "America/Guatemala",
        }
        if self.has_saved_session:
            logger.info("Reutilizando sesión guardada de Agencia Virtual")
            options["storage_state"] = str(self.session_path)
        self._context = launch.new_context(**options)

    def new_page(self) -> Page:
        if self._context is None:
            self.start()
        return self._context.new_page()

    def save_state(self) -> None:
        if self._context is None:
            return
        self.session_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._context.storage_state(path=str(self.session_path))
            logger.info("Sesión guardada en %s", self.session_path)
        except Exception as exc:
            logger.warning("No se pudo guardar la sesión: %s", exc)

    def request_download(self, url: str) -> bytes:
        """Descarge vía HTTP con las cookies de la sesión activa (fallback PDF)."""
        if self._context is None:
            raise RuntimeError("Navegador no iniciado")
        response = self._context.request.get(url)
        response.raise_for_status()
        return response.body()

    def stop(self) -> None:
        if self._context is not None:
            try:
                self._context.close()
            except Exception:
                pass
        if self._playwright is not None:
            try:
                self._playwright.stop()
            except Exception:
                pass
        self._context = None
        self._playwright = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
