"""Organización de los archivos descargados (Fase 1).

Los XML/PDF llegan a data/downloads; al finalizar el ciclo se
archivan en data/processed (processados bien) o data/errors
(archivos vacíos / inválidos). Fase 2 los interpretará.
"""
import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)


class FileManager:
    def __init__(self, settings: dict):
        cfg = settings["sat"]["dirs"]
        self.downloads_dir = Path.cwd() / cfg["downloads"]
        self.processed_dir = Path.cwd() / cfg["processed"]
        self.errors_dir = Path.cwd() / cfg["errors"]
        for d in (self.downloads_dir, self.processed_dir, self.errors_dir):
            d.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    def list_files(self, extensiones: tuple[str, ...] = (".xml", ".pdf")) -> list[Path]:
        return sorted(
            f for f in self.downloads_dir.iterdir()
            if f.is_file() and f.suffix.lower() in extensiones
        )

    def move_to_processed(self, file: Path) -> Path:
        return self._move(file, self.processed_dir)

    def move_to_errors(self, file: Path) -> Path:
        return self._move(file, self.errors_dir)

    def archive_downloads(self) -> dict[str, int]:
        """Al finalizar: mover XML/PDF válidos a processed; vacíos a errors.
        Mantiene los pares: si el XML es válido, su PDF hermano va con él."""
        conteo = {"processed": 0, "errors": 0}
        archivos = self.list_files()
        xmls = [f for f in archivos if f.suffix.lower() == ".xml"]
        pdfs_tomados = set()

        for xml in xmls:
            valido = xml.exists() and xml.stat().st_size > 0
            self.move_to_processed(xml) if valido else self.move_to_errors(xml)
            conteo["processed" if valido else "errors"] += 1

            pdf = self.downloads_dir / f"{xml.stem}.pdf"
            if pdf.exists():
                self.move_to_processed(pdf) if valido else self.move_to_errors(pdf)
                conteo["processed" if valido else "errors"] += 1
                pdfs_tomados.add(pdf.name)

        # PDFs huérfanos (sin XML hermano)
        for pdf in [f for f in self.list_files()
                    if f.suffix.lower() == ".pdf" and f.name not in pdfs_tomados]:
            self.move_to_processed(pdf)
            conteo["processed"] += 1

        logger.info("Archivo organizado: %s procesados / %s errores",
                    conteo["processed"], conteo["errors"])
        return conteo
