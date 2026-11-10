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
import zipfile
from pathlib import Path

from playwright.sync_api import Download, ElementHandle
from playwright.sync_api import TimeoutError as PWTimeout

from src.sat.invoice_search import UUID_RE

logger = logging.getLogger(__name__)

EXT_SANEADO = re.compile(r"[^A-Za-z0-9._-]")


class Downloader:
    def __init__(self, page, settings: dict, downloads_dir: Path, frame=None):
        self.page = page
        self.frame = frame or page
        self.dir = Path(downloads_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.timeout_ms = int(settings["sat"]["timeouts"]["download_ms"])
        self.downloaded: dict[str, dict[str, Path]] = {}

    # ------------------------------------------------------------------
    def download_all(self, results: list[dict]) -> list[Path]:
        """Descarga los archivos XML y PDF de los resultados.

        En la app Angular del SAT (felcons), la descarga se realiza
        marcando los resultados con la columna 'MARCA' y haciendo clic
        en los iconos superiores de exportación (Archivo XML y Archivo PDF),
        los cuales devuelven un archivo ZIP con los XML o PDF correspondientes.
        Si la descarga masiva está disponible, se descarga y descomprime.
        En caso contrario, se realiza la descarga por fila como respaldo.
        """
        dom = self.frame
        archivos_masivos = self._try_batch_download(dom)
        if archivos_masivos:
            return archivos_masivos

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

    def _try_batch_download(self, dom) -> list[Path]:
        """Intenta marcar todos los DTE y descargar vía iconos superiores XML y PDF."""
        try:
            xml_btn = dom.locator(".iconDownload fa.xml, .iconDownload i.fa-file-code-o").first
            pdf_btn = dom.locator(".iconDownload fa.pdf, .iconDownload i.fa-file-pdf-o").first
            header_cb = dom.locator("mat-header-cell.marca mat-checkbox, th.marca input[type='checkbox']").first

            if xml_btn.count() == 0 or not xml_btn.is_visible():
                return []

            # 1. Asegurar que estén marcadas todas las filas
            if header_cb.count() > 0 and header_cb.is_visible():
                first_cb = dom.locator("mat-cell.marca mat-checkbox input, td.marca input").first
                is_checked = False
                try:
                    is_checked = first_cb.is_checked()
                except Exception:
                    pass
                if not is_checked:
                    logger.info("Marcando todos los DTE con la casilla de encabezado...")
                    header_cb.click(timeout=5000)
                    try:
                        self.page.wait_for_timeout(300)
                    except Exception:
                        pass

            archivos_extraidos: list[Path] = []

            # 2. Descargar XML (ZIP o XML directo)
            logger.info("Solicitando descarga de XML masivo...")
            try:
                with self.page.expect_download(timeout=self.timeout_ms) as dl_info:
                    xml_btn.click(timeout=5000)
                dl = dl_info.value
                dest = self.dir / (dl.suggested_filename or "dte_xml.zip")
                dl.save_as(str(dest))
                logger.info("Descarga XML completada: %s (%s KB)", dest.name, round(dest.stat().st_size / 1024))
                archivos_extraidos.extend(self._descomprimir_o_guardar(dest, "xml"))
            except Exception as exc:
                logger.warning("No se pudo completar la descarga masiva de XML: %s", exc)

            # 3. Descargar PDF (ZIP o PDF directo)
            if pdf_btn.count() > 0 and pdf_btn.is_visible():
                logger.info("Solicitando descarga de PDF masivo...")
                try:
                    with self.page.expect_download(timeout=self.timeout_ms) as dl_info_pdf:
                        pdf_btn.click(timeout=5000)
                    dl_pdf = dl_info_pdf.value
                    dest_pdf = self.dir / (dl_pdf.suggested_filename or "dte_pdf.zip")
                    dl_pdf.save_as(str(dest_pdf))
                    logger.info("Descarga PDF completada: %s (%s KB)", dest_pdf.name, round(dest_pdf.stat().st_size / 1024))
                    archivos_extraidos.extend(self._descomprimir_o_guardar(dest_pdf, "pdf"))
                except Exception as exc:
                    logger.warning("No se pudo completar la descarga masiva de PDF: %s", exc)

            return archivos_extraidos
        except Exception as exc:
            logger.debug("Error en intento de descarga masiva: %s", exc)
            return []

    def _descomprimir_o_guardar(self, archivo: Path, tipo: str) -> list[Path]:
        """Si es ZIP lo descomprime en downloads_dir; si no, devuelve el archivo."""
        if archivo.suffix.lower() == ".zip":
            extraidos = []
            try:
                with zipfile.ZipFile(archivo, 'r') as zf:
                    for name in zf.namelist():
                        if name.endswith("/") or name.startswith("__MACOSX"):
                            continue
                        target_name = Path(name).name
                        # Renombrar con UUID si está presente en el nombre
                        match = UUID_RE.search(target_name)
                        if match:
                            target_name = f"{match.group(0).upper()}.{tipo.lower()}"
                        target_path = self.dir / target_name
                        with zf.open(name) as src, open(target_path, "wb") as dst:
                            dst.write(src.read())
                        extraidos.append(target_path)
                logger.info("ZIP %s descomprimido: %s archivos %s generados", archivo.name, len(extraidos), tipo.upper())
                try:
                    archivo.unlink()  # Limpiar el ZIP temporal
                except Exception:
                    pass
                return extraidos
            except Exception as exc:
                logger.error("Error al descomprimir %s: %s", archivo.name, exc)
                return [archivo]
        return [archivo]

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
