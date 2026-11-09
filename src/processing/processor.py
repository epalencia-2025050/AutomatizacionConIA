"""Procesador de DTE descargados: XML → validación → SQLite → archivos.

Pipeline por archivo XML en data/downloads:
 1. lectura con XmlReader (lxml)
 2. validación (NIT módulo 11, UUID, total, fecha, PDF correspondiente)
 3. detección de duplicados por UUID (SQL UNIQUE + consulta)
 4. inserción en SQLite con estado VALIDADA, o ERROR con motivo
 5. archivo: XML+PDF → data/processed (o data/errors si falló)
"""
import logging
from pathlib import Path

from src.processing.models import FacturaDTE
from src.processing.xml_reader import XmlReader
from src.processing.validator import Validator
from src.processing.pdf_handler import PdfHandler
from src.database.repository import Repository
from src.utils.file_manager import FileManager

logger = logging.getLogger(__name__)


class InvoiceProcessor:
    def __init__(self, settings: dict, files: FileManager, repository: Repository):
        self.files = files
        self.repo = repository
        self.reader = XmlReader()
        self.validator = Validator()
        self.validar_nit = bool(settings.get("processing", {}).get("validar_nit", True))

    # ------------------------------------------------------------------
    def procesar_descargas(self) -> dict:
        """Procesa todos los XML de data/downloads; devuelve conteos."""
        xmls = [f for f in self.files.list_files(extensiones=(".xml",))]
        conteo = {"validos": 0, "duplicados": 0, "errores": 0}
        for xml in xmls:
            try:
                estado = self._procesar_xml(xml)
                conteo[estado] += 1
            except Exception:            # pylint: disable=broad-except
                logger.exception("Fallo inesperado procesando %s", xml.name)
                conteo["errores"] += 1
                self._archivar_mal(xml, "fallo inesperado en el procesador")
        logger.info("Procesamiento: %s", conteo)
        return conteo

    # ------------------------------------------------------------------
    def _procesar_xml(self, xml: Path) -> str:
        pdf = PdfHandler.pdf_de(xml, [self.files.downloads_dir])

        data = self.reader.parse(xml)
        problemas = self.validator.validate(data, validar_nit=self.validar_nit,
                                            pdf_correspondente=pdf)

        if problemas:
            motivo = "; ".join(problemas)
            self._registrar_error(data, motivo)
            self._archivar_mal(xml, motivo, pdf)
            return "errores"

        uuid = data.uuid
        if self.repo.existe_uuid(uuid):
            logger.info("Duplicado (ya en BD): %s", uuid)
            self._archivar_bien(xml, pdf, ya_registrado=True)
            return "duplicados"

        self.repo.insertar(data, estado="VALIDADA",
                           pdf_path=str(pdf) if pdf else None)
        self._archivar_bien(xml, pdf, ya_registrado=False, uuid=uuid)
        logger.info("DTE VALIDADA %s | %s %s %s | %s %s",
                    uuid[:13], data.tipo_documento,
                    data.serie, data.numero_documento,
                    data.nit_emisor, data.total)
        return "validos"

    # ------------------------------------------------------------------
    def _registrar_error(self, data, motivo: str) -> None:
        """Registra el problema en la BD cuando hay datos mínimos de clave."""
        if isinstance(data, FacturaDTE):
            try:
                self.repo.insertar(data, estado="ERROR")
                self.repo.marcar_estado(data.uuid, "ERROR", mensaje_error=motivo)
            except Exception:    # UUID ausente/inválido no entra a BD
                logger.debug("No se registró en BD: %s", motivo)
        else:
            logger.error("XML inutilizable -> %s", motivo)

    def _archivar_bien(self, xml: Path, pdf: Path | None,
                       ya_registrado: bool, uuid: str = "") -> None:
        destino_xml = self.files.move_to_processed(xml)
        destino_pdf = self.files.move_to_processed(pdf) if pdf and pdf.exists() else None
        if not ya_registrado and uuid:
            self.repo.actualizar_rutas(uuid, str(destino_xml),
                                       str(destino_pdf) if destino_pdf else None)

    def _archivar_mal(self, xml: Path, motivo: str, pdf: Path | None = None) -> None:
        self.files.move_to_errors(xml)
        if pdf and pdf.exists():
            self.files.move_to_errors(pdf)
        logger.warning("Archivado en errors (motivo: %s): %s", motivo, xml.name)
