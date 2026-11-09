"""Envío genérico de facturas a un formulario del destino (Fase 3).

El flujo del formulario real NO se inventa: se describe totalmente en
config/selectors.yaml -> destination.envio (campos del formulario, input
de archivos, botón guardar y selector/texto de confirmación).
Mientras esté vacío, el módulo se declara no configurado.
"""
import logging
from pathlib import Path

from playwright.sync_api import TimeoutError as PWTimeout

from src.destination.authentication import DestinationAuthentication
from src.destination.module import (DestinationModule, NoConfiguradoError,
                                    ResultadoEnvio)

logger = logging.getLogger(__name__)

CLAVES_ENVIO = ("form_url", "campos", "input_archivo", "guardar_btn",
                "confirmacion_selector")


class GenericDestinationModule(DestinationModule):
    """Implementación por configuración, activable cuando se conozca el sitio."""

    name = "generico-config"

    def __init__(self, settings: dict, selectors: dict, browser=None):
        self.settings = settings
        self.sel_envio = (selectors.get("destination") or {}).get("envio") or {}
        self.sel_login = (selectors.get("destination") or {}).get("login") or {}
        self.auth = DestinationAuthentication(settings, selectors,
                                              browser=browser)
        self.page = self.auth.page
        self.browser = browser
        self.configurado = self._configurado()

    def _configurado(self) -> bool:
        if not self.auth.configurado():
            return False
        return all((self.sel_envio.get(k) or "").strip()
                   for k in CLAVES_ENVIO if k != "campos") and \
            isinstance(self.sel_envio.get("campos"), dict) and \
            bool(self.sel_envio.get("campos"))

    # ------------------------------------------------------------------
    def login(self) -> None:
        self.page = self.auth.login()
        if self.browser is not None and self.page is not None:
            self.browser.save_state()

    def enviar(self, factura: dict, xml_path=None, pdf_path=None) -> ResultadoEnvio:
        if not self.configurado():
            raise NoConfiguradoError("Módulo de envío sin configurar")
        sel = self.sel_envio
        timeout = int(self.settings["destination"].get("timeouts", {})\
                      .get("timeout_ms", 20000))

        try:
            url_form = (sel["form_url"] or "").strip()
            if url_form:
                self.page.goto(url_form, timeout=timeout, wait_until="domcontentloaded")

            # Campo formulario <- valor de la factura (mapping en config)
            for campo_factura, selector in sel["campos"].items():
                valor = factura.get(campo_factura) or ""
                if selector and hasattr(valor, "isoformat"):
                    valor = str(valor)
                if not selector:
                    continue
                self.page.fill(selector, str(valor), timeout=timeout)

            for archivo in (xml_path, pdf_path):
                if archivo and Path(str(archivo)).exists():
                    self.page.set_input_files(sel["input_archivo"],
                                              str(archivo), timeout=timeout)

            self.page.click(sel["guardar_btn"], timeout=timeout)

            # Confirmación visible (toast/alert/mensaje) => verificable
            self.page.wait_for_selector(sel["confirmacion_selector"],
                                        timeout=timeout)
            return ResultadoEnvio.SIN_CONFIRMACION if not self.verificar(
                factura.get("uuid") or "") else ResultadoEnvio.SUBIDA

        except PWTimeout as exc:
            logger.error("Formulario del destino no respondió: %s", exc)
            return ResultadoEnvio.ERROR
        except Exception as exc:   # pylint: disable=broad-except
            logger.exception("Fallo de envío al destino: %s", exc)
            return ResultadoEnvio.ERROR

    def verificar(self, uuid: str) -> bool:
        """Verificación post-envío definida en config.

        destino.envio.verificacion_url + destino.envio.verificacion_selector
        Si no existe estrategia configurada, devuelve False (no se marca
        SUBIDA sin confirmación verificable, regla §8).
        """
        sel = self.sel_envio
        url = (sel.get("verificacion_url") or "").strip()
        sels = (sel.get("verificacion_selector") or "").strip()
        if (not url and not sels) or not uuid:
            return False
        try:
            if url:
                url_con_uuid = url.format(uuid=uuid)
                self.page.goto(url_con_uuid, wait_until="domcontentloaded")
            if sels:
                for s in sels.split("|"):
                    if self.page.locator(s.strip()).count() > 0:
                        return True
                return False
            return True   # url cargó y no hay selector que validar
        except Exception:   # pylint: disable=broad-except
            return False
