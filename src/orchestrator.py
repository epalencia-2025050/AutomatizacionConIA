"""Orquestador: FASE 1 (descarga SAT) + FASE 2 (procesamiento y BD).

Fase 1: login Agencia Virtual -> Consultar DTE recibidos -> descargar
        XML/PDF -> data/downloads.
Fase 2: leer XML (lxml) -> validar (NIT módulo 11, UUID, total, PDF)
        -> SQLite con máquina de estados -> data/processed | data/errors.

La Fase 3 (destino) se integra cuando se conozca la plataforma.
"""
import logging
from datetime import date, timedelta
from pathlib import Path

import yaml

from src.sat.browser import BrowserManager
from src.sat.authentication import SatAuthentication
from src.sat.invoice_search import InvoiceSearch
from src.sat.downloader import Downloader
from src.utils.file_manager import FileManager
from src.utils.logger import setup_logger
from src.database.repository import Repository
from src.processing.processor import InvoiceProcessor
from src.destination.browser import DestinationBrowser
from src.destination.uploader import DestinationUploader

logger = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).resolve().parents[1]


class Orchestrator:
    """Coordina el pipeline: SAT GT -> procesamiento -> BD -> archivos."""

    def __init__(self):
        self.settings = self._load_yaml("config/settings.yaml")
        self.selectors = self._load_yaml("config/selectors.yaml")
        self.files = FileManager(self.settings)
        self._repo = None

    # ------------------------------------------------------------------
    def _load_yaml(self, relative: str) -> dict:
        with open(ROOT_DIR / relative, "r", encoding="utf-8") as fh:
            return yaml.safe_load(fh)

    @property
    def db_path(self) -> Path:
        return ROOT_DIR / self.settings["database"]["ruta"]

    # ------------------------------------------------------------------
    def run(self, date_from: str = None, date_to: str = None,
            dry_run: bool = False, solo_procesar: bool = False,
            solo_subir: bool = False) -> dict:
        setup_logger()
        sat = self.settings["sat"]
        rango = self._normalizar_fechas(date_from, date_to, sat)
        estado = {"descargas": 0, "validos": 0, "duplicados": 0, "errores": 0,
                  "enviadas": 0, "sin_confirmacion": 0}

        logger.info("=== INICIO === %s | dry_run=%s solo_procesar=%s solo_subir=%s",
                    rango, dry_run, solo_procesar, solo_subir)

        if not solo_procesar and not solo_subir:
            estado["descargas"] = self._fase_sat(sat, rango, dry_run)

        # ---- FASE 2: procesamiento y almacenamiento ----
        if not dry_run and not solo_subir:
            estado_proceso = self._fase_procesamiento()
            estado.update({"validos": estado_proceso.get("validos", 0),
                           "duplicados": estado_proceso.get("duplicados", 0),
                           "errores": estado_proceso.get("errores", 0)})
            logger.info("Resumen por estado en BD: %s", self._repo_resumen())

        # ---- FASE 3: transferencia al destino ----
        if not dry_run:
            f3 = self._fase_destino()
            estado.update({"enviadas": f3.get("enviadas", 0),
                           "sin_confirmacion": f3.get("sin_confirmacion", 0)})

        logger.info("=== FIN === %s", estado)
        return estado

    # ------------------------------------------------------------------
    @staticmethod
    def _normalizar_fechas(date_from, date_to, sat) -> tuple[str, str]:
        if not date_from:
            dias = int(sat["filters"].get("dias_atras_default", 7))
            date_from = (date.today() - timedelta(days=dias)).strftime("%d/%m/%Y")
        if not date_to:
            date_to = date.today().strftime("%d/%m/%Y")
        return date_from, date_to

    def _fase_sat(self, sat, rango, dry_run) -> int:
        date_from, date_to = rango
        headless = bool(sat.get("headless", False))
        session = Path.cwd() / sat["dirs"]["session"]
        with BrowserManager(headless=headless, session_path=session) as bm:
            auth = SatAuthentication(self.settings, self.selectors, bm)
            auth.login()

            page = bm.new_page()
            search = InvoiceSearch(page, self.settings, self.selectors)
            url_directa = (sat.get("consulta_dte_url") or "").strip()
            if url_directa:
                page.goto(url_directa, timeout=30000, wait_until="domcontentloaded")
            else:
                search.open_module()
                page.wait_for_timeout(1500)
            search.apply_filters(date_from, date_to,
                                 sat["filters"].get("tipo_operacion", "Recibidos"))
            resultados = search.read_results()

            if dry_run:
                logger.info("Dry-run: listado sin descargar")
                for i, r in enumerate(resultados, 1):
                    logger.info("  [%s] uuid=%s celdas=%s",
                                i, r.get("uuid") or "s/d", r["cells"])
                return 0
            if resultados:
                downloader = Downloader(page, self.settings, self.files.downloads_dir)
                return len(downloader.download_all(resultados))
            return 0

    def _fase_procesamiento(self) -> dict:
        self._repo = Repository(self.db_path)
        processor = InvoiceProcessor(self.settings, self.files, self._repo)
        conteo = processor.procesar_descargas()
        return conteo

    def _fase_destino(self) -> dict:
        """Fase 3: sólo si destination.habilitado == true en settings."""
        dest = self.settings.get("destination") or {}
        if not dest.get("habilitado"):
            logger.info("Fase 3 deshabilitada (destination.habilitado=false): "
                        "no se intentará envíos al destino")
            return {"enviadas": 0}
        if self._repo is None:
            self._repo = Repository(self.db_path)
        # MÃ³dulo genÃ©rico (por configuraciÃ³n). Cuando se conozca la
        # plataforma real, se crea su subclase y se hace plug aquÃ­.
        from src.destination.invoice_form import GenericDestinationModule
        browser_cfg = dest.get("browser") or {}
        module = GenericDestinationModule(self.settings, self.selectors, None)
        uploader = DestinationUploader(self._repo, module,
                                       max_intentos=int(dest.get("max_intentos", 3)))
        session = Path.cwd() / browser_cfg.get("session", "storage/dest_state.json")
        headless = bool(browser_cfg.get("headless", False))
        browser = DestinationBrowser(headless=headless, session_path=session)
        try:
            browser.start()
            module.browser = browser
            module.page = browser.page
            module.auth.page = browser.page
            module.configurado = module._configurado()
            return uploader.run()
        finally:
            browser.close()

    def _repo_resumen(self) -> dict:
        try:
            return self._repo.resumen()
        except Exception:
            return {}
