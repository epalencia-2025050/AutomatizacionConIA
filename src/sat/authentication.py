"""Autenticación en la Agencia Virtual de SAT Guatemala.

Flujo real (verificado en el HTML del portal):
 1. Formulario: NIT/CUI + contraseña  -> botón "Iniciar Sesión"
 2. Segundo factor: código de 6 dígitos de Microsoft Authenticator
    (requiere intervención humana; el program NO lo automatiza)
 3. La sesión se guarda en storage/sat_av_state.json para reusarla.
"""
import logging
import os
import time
from datetime import datetime
from pathlib import Path

from playwright.sync_api import Page

logger = logging.getLogger(__name__)


class SatAuthentication:
    def __init__(self, settings: dict, selectors: dict, browser_manager):
        self.sat = settings["sat"]
        self.sel = selectors["login"]
        self.run_cfg = settings["run"]
        self.browser = browser_manager
        self.page = None

    # ------------------------------------------------------------------
    def login(self) -> Page:
        """Inicia sesión. Devuelve una Page autenticada."""
        nit = os.getenv("SAT_NIT", "").strip()
        password = os.getenv("SAT_PASSWORD", "")
        if not nit or not password:
            raise ValueError(
                "Faltan SAT_NIT o SAT_PASSWORD. Configúralos en "
                ".env o src/.env (ambos junto a main.py o dentro de src)."
            )

        url_login = "https://farm3.sat.gob.gt/menu/login.jsf"
        timeout = self.sat["timeouts"]["login_ms"]

        self.page = self.browser.new_page() if (self.page is None) else self.page
        logger.info("Abriendo Agencia Virtual: %s", url_login)
        self.page.goto(url_login, timeout=timeout, wait_until="domcontentloaded")

        if self._already_logged_in():
            logger.info("Sesión activa vigente; se omite el login")
            return self.page

        self._fill_credentials(nit, password, timeout)
        outcome = self._wait_login_outcome(timeout)

        if outcome == "mfa":
            self._wait_for_human_mfa()
            # tras el 2FA se debe completar el redirect del menú principal
        elif outcome == "cred_error":
            detail = self._error_text()
            self.page.screenshot(path=f"logs/login_error_{int(time.time())}.png")
            raise PermissionError(f"Login rechazado por la SAT: {detail}")

        if not self._already_logged_in():
            raise RuntimeError("El login no finalizó en estado autenticado")

        self.browser.save_state()
        logger.info("Autenticación exitosa en Agencia Virtual")
        return self.page

    # ------------------------------------------------------------------
    def _already_logged_in(self) -> bool:
        """True si NO se muestra el formulario de login (ya autenticado)."""
        try:
            visible = self.page.locator(self.sel["login_card"]).first.is_visible()
            return not visible
        except Exception:
            return True   # formulario ausente => probablemente logueado

    def _fill_credentials(self, nit: str, password: str, timeout: int) -> None:
        self.page.fill(self.sel["username_input"], nit, timeout=timeout)
        self.page.fill(self.sel["password_input"], password, timeout=timeout)
        logger.info("Enviando credenciales...")
        self.page.click(self.sel["submit_button"], timeout=timeout)

    def _wait_login_outcome(self, timeout: int) -> str:
        """Espera la reacción del portal: error | mfa | success."""
        deadline = time.time() + timeout / 1000 + 10
        while time.time() < deadline:
            url = self.page.url
            if "login.jsf" not in url:
                return "success"
            try:
                if self.page.locator(self.sel["error_selector"]).first.is_visible():
                    return "cred_error"
                if self.page.locator(self.sel["mfa_input"]).first.is_visible():
                    return "mfa"
            except Exception:
                pass
            time.sleep(0.5)
        return "unknown"

    def _wait_for_human_mfa(self) -> None:
        """Intervención humana: el usuario escribe el código 2FA en el navegador."""
        seconds = int(self.sat["timeouts"]["mfa_s"])
        deadline = time.time() + seconds
        print("\n" + "=" * 60)
        print("  INTERVENCIÓN REQUERIDA: revisa tu app Microsoft Authenticator")
        print("  y teclea el código de 6 dígitos en la ventana del navegador")
        print(f"  (esperando hasta {seconds} segundos...)")
        print("=" * 60 + "\n")
        logger.info("Esperando código MFA humano (máx %s s)", seconds)
        # Fase 7: alerta visual en GUI + correo (marcador que la GUI detecta)
        logger.info("ALERTA_SAT_PIDE_2FA: ingresa el código en el navegador")
        try:
            import yaml as _yaml
            root = Path(__file__).resolve().parents[2]
            settings = _yaml.safe_load(open(root / "config" / "settings.yaml",
                                            encoding="utf-8"))
            EmailSender(settings).alerta_2fa()
        except Exception:
            logger.debug("Alerta 2FA por correo no enviada (sin config)")
        while time.time() < deadline:
            url = self.page.url
            mfa_visible = False
            try:
                mfa_visible = self.page.locator(self.sel["mfa_input"]).first.is_visible()
            except Exception:
                pass
            if "login.jsf" not in url or not mfa_visible:
                logger.info("2FA completado; continuando")
                return
            time.sleep(1.0)
        self.page.screenshot(path=f"logs/mfa_timeout_{int(time.time())}.png")
        raise TimeoutError("El código de 2FA no se ingresó a tiempo")

    def _error_text(self) -> str:
        try:
            return self.page.locator(self.sel["error_selector"]).first.inner_text().strip()
        except Exception:
            return "(mensaje no legible)"
