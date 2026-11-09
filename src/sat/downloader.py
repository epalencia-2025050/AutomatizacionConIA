"""Descarga de XML y PDF de cada DTE listado en la consulta.

Estrategias, en orden:
 1. Clic en el enlace -> Playwright captura la descarga (expect_download).
 2. Si el portal abre el PDF en ventana nueva, la captura la descarga
    vía HTTP con las cookies activas (fallback del BrowserManager).
El archivo se renombra con el UUID del DTE cuando se puede detectar.
"""
import logging
import re
import time
from pathlib import Path

from playwright.sync_api import Download, ElementHandle
from playwright.sync_api import TimeoutError as PWTimeout

from src.sat.invoice_search import UUID_RE

logger = logging.getLogger(__name__)

EXT_SANEADO = re.compile(r"[^A-Za-z0-9._-]")


class Downloader:
    def __init__(self, page, settings: dict, downloads_dir: Path):
        self.page = page
        self.dir = Path(downloads_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.timeout_ms = int(settings["sat"]["timeouts"]["download_ms"])
        self.downloaded: dict[str, dict[str, Path]] = {}

    # ------------------------------------------------------------------
    def download_all(self, results: list[dict]) -> list[Path]:
        archivos: list[Path] = []
        for i, item in enumerate(results, start=1):
            uuid = item.get("uuid") or f"DTE_{i:03d}"
            try:
                paths = self._download_pair(uuid, item)
                archivos.extend(paths)
                self.downloaded[uuid] = paths
            except Exception as exc:
                logger.error("Fallo descarga DTE %s: %s", uuid, exc)
        return archivos

    def _download_pair(self, uuid: str, item: dict) -> list[Path]:
        paths: list[Path] = []
        xml_path = self._download_link(uuid, item, "xml")
        if xml_path:
            paths.append(xml_path)
            pdf_path = self._download_link(uuid, item, "pdf")
            if pdf_path:
                paths.append(pdf_path)
        return paths

    # ------------------------------------------------------------------
    def _download_link(self, uuid: str, item: dict, tipo: str):
        enlace: ElementHandle | None = (item.get("links") or {}).get(tipo)
        if enlace is None:
            logger.debug("DTE %s sin enlace %s", uuid, tipo.upper())
            return None

        try:
            download = self._click_and_capture(enlace)
            return self._save(download, uuid, tipo)
        except PWTimeout:
            logger.warning("Timeout de descarga %s %s; verificando ventana nueva",
                           tipo.upper(), uuid)
            return self._download_via_popup(uuid, item.get("links") or {}, tipo)

    def _click_and_capture(self, enlace) -> Download:
        with self.page.expect_download(timeout=self.timeout_ms) as info:
            enlace.click()
        return info.value

    def _save(self, download: Download, uuid: str, tipo: str) -> Path:
        sugerido = download.suggested_filename or f"{uuid}.{tipo}"
        destino = self._filename(destino_uuid=uuid, base=sugerido, tipo=tipo)
        download.save_as(str(destino))
        logger.info("Descargado %s -> %s (%s KB)", tipo.upper(), destino.name,
                    round(destino.stat().st_size / 1024))
        return destino

    # ------------------------------------------------------------------
    def _filename(self, destino_uuid: str, base: str, tipo: str) -> Path:
        """Nombre final: <UUID>.<ext>. Si no hay UUID, usa el sugerido saneado."""
        ext = tipo.lower()
        match = UUID_RE.search(base) or (UUID_RE.search(destino_uuid) if destino_uuid else None)
        nombre = f"{match.group(0).upper()}.{ext}" if match else \
                 (EXT_SANEADO.sub("_", base) or f"{destino_uuid}.{ext}")
        destino = self.dir / nombre
        contador = 1
        while destino.exists():
            destino = self.dir / f"{destino.stem}_{contador}{destino.suffix}"
            contador += 1
        return destino

    def _download_via_popup(self, uuid: str, links: dict, tipo: str) -> Path | None:
        """Corrección: si el portal abre el documento en nueva pestaña (PDF)."""
        enlace = links.get(tipo)
        if enlace is None:
            return None
        context = self.page.context
        try:
            with context.expect_page(timeout=15000) as popup_info:
                enlace.click()
            popup = popup_info.value
            url = popup.url
            popup.close()
        except (PWTimeout, Exception) as exc:
            logger.warning("Sin ventana nueva ni descarga para %s %s: %s",
                           tipo.upper(), uuid, exc)
            return None
        if not re.match(r"^https?", url, re.I):
            logger.warning("URL no HTTP en ventana nueva: %s", url)
            return None
        bytes_pdf = self.page.context.request.get(url).body()
        destino = self._filename(uuid, f"{uuid}.{tipo}", tipo)
        destino.write_bytes(bytes_pdf)
        logger.info("Descargado %s vía ventana nueva -> %s", tipo.upper(), destino.name)
        return destino
