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


URL_LOGIN = "https://farm3.sat.gob.gt/menu/login.jsf"
URL_PORTADA = "https://farm3.sat.gob.gt/menu/portada.jsf"


class SatAuthentication:
    def __init__(self, settings: dict, selectors: dict, browser_manager):
        self.sat = settings["sat"]
        self.sel = selectors["login"]
        self.run_cfg = settings["run"]
        self.browser = browser_manager
        self.page = None

    # ------------------------------------------------------------------
    def login(self) -> Page:
        """Inicia sesión. Devuelve una Page autenticada.

        La sesión se valida contra la PORTADA (no contra login.jsf):
        con cookies guardadas el portal puede responder 'Acceso no
        autorizado' aunque se parezca logueado; en ese caso se limpia
        la sesión y se loguea desde cero, todo automático.
        """
        nit = os.getenv("SAT_NIT", "").strip()
        password = os.getenv("SAT_PASSWORD", "")
        if not nit or not password:
            raise ValueError(
                "Faltan SAT_NIT o SAT_PASSWORD. Configúralos en "
                ".env o src/.env (ambos junto a main.py o dentro de src)."
            )

        url_login = URL_LOGIN
        url_portada = (self.sat.get("portada_url") or "").strip() or URL_PORTADA
        timeout = self.sat["timeouts"]["login_ms"]

        self.page = self.browser.new_page() if (self.page is None) else self.page
        logger.info("Validando sesión contra la portada: %s", url_portada)
        try:
            self.page.goto(url_portada, timeout=timeout,
                           wait_until="domcontentloaded")
        except Exception as exc:
            logger.debug("Portada no cargó (%s); se abre el login directo", exc)
            self.page.goto(url_login, timeout=timeout,
                           wait_until="domcontentloaded")

        if self._acceso_denegado() and "login.jsf" in self.page.url:
            # Cookie declarada viva además NO autentica la vista de login
            # (sesión muerta real: el login card no existe ahí)
            logger.warning("Sesión guardada inválida ('Acceso no autorizado "
                           "para el usuario'): se limpia y re-loguea solo")
            self._reiniciar_sesion()
            self.page.goto(url_login, timeout=timeout,
                           wait_until="domcontentloaded")

        if self._already_logged_in():
            if self._portal_interno_vencido():
                # Las cookies TTL del portal siguen vigentes, pero la app
                # Angular del DTE (felcons) rechaza con 'Acceso no
                # autorizado': requiere re-login completo para regenerar
                # la autorización interna y el parámetro Clave del iframe.
                logger.warning("Sesión del portal viva pero la app interna "
                               "del DTE está vencida: re-login completo")
                self._reiniciar_sesion()
                self.page.goto(url_login, timeout=timeout,
                               wait_until="domcontentloaded")
            else:
                logger.info("Sesión activa vigente; se omite el login")
                return self.page

        self._fill_credentials(nit, password, timeout)
        outcome = self._wait_login_outcome(timeout)

        if outcome == "success":
            pass   # el portal redirigió; se valida abajo antes de seguir
        elif outcome == "mfa":
            self._wait_for_human_mfa()
            # tras el 2FA se debe completar el redirect del menú principal
        elif outcome == "cred_error":
            detail = self._error_text()
            self.page.screenshot(path=f"logs/login_error_{int(time.time())}.png")
            raise PermissionError(f"Login rechazado por la SAT: {detail}")
        else:
            # outcome 'unknown': el portal no completó el login a tiempo.
            # Suele pasar al re-loguear muy rápido tras cerrar el proceso
            # (el SAT aplica un enfriamiento breve). Es transitorio: se
            # aborta con RuntimeError para que el reintento con espera
            # (backoff 1/2/5 min) lo resuelva automáticamente.
            logger.warning("Login sin finalizar a tiempo (posible "
                           "enfriamiento del SAT tras un relogueo rápido); "
                           "se libera para reintento con espera")
            raise RuntimeError(
                "El login no finalizó a tiempo en el portal (transitorio; "
                "reintento automático con espera)")

        if not self._already_logged_in():
            raise RuntimeError("El login no finalizó en estado autenticado")

        self.browser.save_state()
        logger.info("Autenticación exitosa en Agencia Virtual")
        return self.page

    # ------------------------------------------------------------------
    def _already_logged_in(self) -> bool:
        """True si NO se muestra el formulario de login (ya autenticado).

        OJO: el portlet central de la portada puede decir 'Acceso no
        autorizado' aunque la sesión esté viva (portlet sin permiso del
        perfil); NO es señal de deslogin. Sesión muerta real = se está
        en login.jsf (el portal redirige ahí al expirar)."""
        try:
            if "login.jsf" in getattr(self.page, "url", ""):
                logger.info("Vista en login.jsf: sesión no activa")
                return False
        except Exception:
            pass
        try:
            visible = self.page.locator(self.sel["login_card"]).first.is_visible()
            return not visible
        except Exception:
            return True   # formulario ausente => probablemente logueado

    def _acceso_denegado(self) -> bool:
        """True cuando el portal responde 'Acceso no autorizado...'."""
        try:
            return self.page.locator(
                'text=Acceso no autorizado').first.is_visible()
        except Exception:
            return False

    def _portal_interno_vencido(self) -> bool:
        """True si el iframe interno del DTE (felcons) dice 'Acceso no autorizado'.

        La app Angular del DTE tiene su PROPIA autorización, distinta de
        las cookies TTL del portal: puede vencer aunque la portada siga
        viva (el mismo Clave=... reaparece entre corridas). El mensaje
        vive DENTRO del frame, no en la página principal.
        """
        frames = getattr(self.page, "frames", None) or []
        for fr in frames:
            if fr is getattr(self.page, "main_frame", None):
                continue
            url = (fr.url or "").lower()
            if (fr.name == "iframeContent" or "felcons" in url
                    or "dte-agencia" in url or "dte-consulta" in url):
                try:
                    if fr.locator(
                            'text=Acceso no autorizado').first.is_visible():
                        logger.warning("App interna del DTE vencida: "
                                       "'Acceso no autorizado' en "
                                       "iframe %r (%s)", fr.name, fr.url)
                        return True
                except Exception:
                    continue
        return False

    def _reiniciar_sesion(self) -> None:
        """Limpia cookies del contexto y borra la sesión guardada.

        Permitirá al portal renderizar el formulario de login limpio
        (la sesión guardada quedó inválida del lado del servidor).
        """
        # 1) borrar el archivo de sesión para no reutilizar nada
        try:
            if self.browser.session_path.exists():
                self.browser.session_path.unlink()
                logger.info("Archivo de sesión eliminado: %s",
                            self.browser.session_path)
        except Exception as exc:
            logger.warning("No se pudo borrar el archivo de sesión: %s", exc)
        # 2) limpiar cookies del contexto activo
        try:
            self.page.context.clear_cookies()
            logger.info("Cookies del navegador limpiadas")
        except Exception as exc:
            logger.warning("No se pudieron limpiar cookies: %s", exc)

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
