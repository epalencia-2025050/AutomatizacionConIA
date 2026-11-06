"""Descarga de XML y PDF desde el portal del SAT."""
import logging
import re
import time
from pathlib import Path

from playwright.sync_api import Download, Page

logger = logging.getLogger(__name__)


class Downloader:
    """Descarga cada CFDI listado en la búsqueda previa."""

    def __init__(self, page: Page, selectors: dict, download_dir: Path,
                 timeout_seconds: int = 90):
        self.page = page
        self.selectors = selectors
        self.download_dir = Path(download_dir)
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.timeout_ms = timeout_seconds * 1000
        self.downloaded: dict[str, list[Path]] = {}

    def download_all(self, results: list[dict]) -> list[Path]:
        """Itera todas las filas descargando XML; agrega PDF cuando exista."""
        all_files: list[Path] = []
        for result in results:
            row = result.get("element")
            try:
                files = self._download_row(row, result)
                all_files.extend(files)
            except Exception as exc:
                logger.error("Error descargando fila %s: %s", result.get("row_index"), exc)
        return all_files

    # ------------------------------------------------------------------
    def _download_row(self, row, result: dict) -> list[Path]:
        files: list[Path] = []
        xml_path = self._download_link(row, self.selectors["sat"]["search"],
                                       "download_xml_link", "xml")
        if xml_path:
            files.append(xml_path)
            pdf_path = self._download_link(row, self.selectors["sat"]["search"],
                                           "download_pdf_link", "pdf")
            if pdf_path:
                files.append(pdf_path)
        result.pop("element", None)
        return files

    def _download_link(self, row, selectors: dict, link_key: str, ext: str):
        link = row.query_selector(selectors[link_key])
        if link is None:
            logger.debug("Sin enlace de descarga %s en la fila", ext.upper())
            return None

        with self.page.expect_download(timeout=self.timeout_ms) as download_info:
            link.click()

        download: Download = download_info.value
        path = self._persist(download, ext)
        logger.info("Descargado %s -> %s", ext.upper(), path.name)
        return path

    def _persist(self, download: Download, ext: str) -> Path:
        """Renombra y descarga el archivo; recupera UUID de la URL."""
        suggested = download.suggested_filename or f"cfdi_{int(time.time())}.{ext}"
        source = self.download_dir / suggested
        download.save_as(str(source))
        target = self._rename(source, suggested, ext)
        return target

    def _rename(self, source: Path, suggested: str, ext: str) -> Path:
        """Convierte 'Foo-UUID.xml' a 'UUID.xml' cuando corresponde."""
        match = re.search(r"([0-9a-fA-F-]{36})", suggested)
        suffix = f".{ext}"
        if match:
            target = self.download_dir / f"{match.group(1)}{suffix}"
            if target != source:
                source.rename(target)
            return target
        return source

    def list_downloads(self) -> list[Path]:
        return [f for f in sorted(self.download_dir.iterdir()) if f.is_file()]
