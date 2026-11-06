"""Orquestador principal del flujo: SAT -> procesamiento -> destino."""
import logging
from pathlib import Path

import yaml

from src.processing.xml_reader import XmlReader
from src.processing.validator import Validator
from src.sat.browser import BrowserManager
from src.sat.authentication import SatAuthentication
from src.sat.invoice_search import InvoiceSearch
from src.sat.downloader import Downloader
from src.destination.authentication import DestinationAuthentication
from src.destination.invoice_form import InvoiceForm
from src.destination.uploader import Uploader
from src.database.repository import Repository
from src.utils.file_manager import FileManager
from src.utils.logger import setup_logger

logger = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).resolve().parents[1]


class Orchestrator:
    """Coordina el ciclo completo de la automatización."""

    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.settings = self._load_yaml("config/settings.yaml")
        self.selectors = self._load_yaml("config/selectors.yaml")

        self.downloads_dir = ROOT_DIR / self.settings["sat"]["downloads_dir"]
        self.processed_dir = ROOT_DIR / self.settings["sat"]["processed_dir"]
        self.errors_dir = ROOT_DIR / self.settings["sat"]["errors_dir"]
        self.file_manager = FileManager(
            self.downloads_dir, self.processed_dir, self.errors_dir
        )
        self.reader = XmlReader(self.settings["processing"]["cfdi_namespaces"])
        self.validator = Validator(self.settings["processing"])
        self.repository = Repository(self._database_path())

    # ------------------------------------------------------------------
    def _load_yaml(self, relative: str) -> dict:
        path = ROOT_DIR / relative
        with open(path, "r", encoding="utf-8") as fh:
            return yaml.safe_load(fh)

    def _database_path(self) -> str:
        """Convierte DATABASE_URL a ruta de archivo para SQLite."""
        url = self._database_url()
        prefix = "sqlite:///"
        return url[len(prefix):] if url.startswith(prefix) else url

    # ------------------------------------------------------------------
    def run(self, date_from=None, date_to=None, issuer_rfc=None):
        setup_logger()
        logger.info("Iniciando automatización | dry_run=%s", self.dry_run)
        headless = bool(self.settings["run"].get("headless", True))

        with BrowserManager() as browser:
            # 1) Autenticación en el SAT
            page = browser.new_page()
            sat_auth = SatAuthentication(self.settings, self.selectors["sat"])
            sat_page = sat_auth.login(page)

            # 2) Búsqueda de CFDIs en el portal
            search = InvoiceSearch(sat_page, self.selectors["sat"])
            results = search.search(date_from=date_from, date_to=date_to,
                                    issuer_rfc=issuer_rfc)
            logger.info("Se encontraron %s resultados en el SAT", len(results))

            # 3) Descarga de XML/PDF
            timeout_dl = self.settings["sat"]["timeouts"].get("download", 90)
            downloader = Downloader(sat_page, self.selectors, self.downloads_dir,
                                    timeout_seconds=timeout_dl)
            downloaded_files = downloader.download_all(results)

            # 4) Procesamiento
            processed = []
            for file_path in downloaded_files:
                data = self.reader.extract(file_path)
                if data is None:
                    self.file_manager.move_to_errors(file_path)
                    continue
                if not self.validator.validate(data):
                    logger.warning("Factura inválida: %s", file_path.name)
                    self.file_manager.move_to_errors(file_path)
                    continue
                processed.append(data)

            # 5) Persistencia en BD (histórico / estado por UUID)
            for data in processed:
                self.repository.save_invoice(data)

            # 6) Registro en sistema destino
            if self.dry_run:
                logger.info("Dry-run activo: no se enviará nada al sistema destino")
            else:
                dest_page = browser.new_page()
                dest_auth = DestinationAuthentication(self.settings, self.selectors)
                dest_page = dest_auth.login(dest_page)

                form = InvoiceForm(dest_page,
                                   self.selectors["destination"]["invoice_form"])
                uploader = Uploader(dest_page, form, self.selectors)

                for data in processed:
                    uuid = data.get("uuid")
                    if self.repository.was_uploaded(uuid):
                        logger.info("UUID ya subido previamente, se omite: %s", uuid)
                        continue
                    pdf_path = self.file_manager.find_partner(
                        self.downloads_dir / data["archivo_xml"], ".pdf"
                    )
                    ok = uploader.upload(data, pdf_path)
                    self.repository.mark_uploaded(uuid, success=ok)

            # 7) Accesos al navegador cerrados por el context manager
        self.file_manager.organize()
        logger.info("Automatización finalizada correctamente")

    def quit(self):
        self.repository.close()
