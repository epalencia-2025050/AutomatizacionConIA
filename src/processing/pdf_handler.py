"""Trabajo con archivos PDF de los CFDI."""
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class PdfHandler:
    """Asocia, valida y gestiona PDFs generados por el SAT."""

    @staticmethod
    def is_valid(pdf_path: Path) -> bool:
        """Verificación básica: archivo existente + cabecera %PDF."""
        if not pdf_path or not pdf_path.exists() or pdf_path.stat().st_size == 0:
            return False
        try:
            with open(pdf_path, "rb") as fh:
                return fh.read(4) == b"%PDF"
        except OSError as exc:
            logger.error("No se puede leer el PDF %s: %s", pdf_path, exc)
            return False

    @staticmethod
    def match_pdf(xml_path: Path, directory: Path) -> Path | None:
        """Busca el PDF con el mismo nombre base que el XML."""
        if not xml_path.exists():
            return None
        candidate = directory / f"{xml_path.stem}.pdf"
        return candidate if candidate.exists() else None

    @staticmethod
    def size_kb(pdf_path: Path) -> int:
        return round(pdf_path.stat().st_size / 1024) if pdf_path.exists() else 0
