"""Trabajo con PDFs y su correspondencia con los XML (Fase 2)."""
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class PdfHandler:
    """Asocia, valida y gestiona PDFs del DTE."""

    @staticmethod
    def is_valid(pdf_path: Path | None) -> bool:
        """Verificación básica: existe y su cabecera es %PDF."""
        if not pdf_path or not pdf_path.exists() or pdf_path.stat().st_size == 0:
            return False
        try:
            with open(pdf_path, "rb") as fh:
                return fh.read(5) == b"%PDF-"
        except OSError as exc:
            logger.error("No se puede leer el PDF %s: %s", pdf_path, exc)
            return False

    @staticmethod
    def pdf_de(xml_path: Path, directorios: list[Path]) -> Path | None:
        """Busca el PDF del mismo nombre base (stem) que el XML."""
        stem = xml_path.stem
        for d in directorios:
            candidato = d / f"{stem}.pdf"
            if candidato.exists():
                return candidato
        return None
