"""Subida de archivos del CFDI al sistema destino."""
import logging
from pathlib import Path

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout

logger = logging.getLogger(__name__)


class Uploader:
    """Registra la factura y sube XML/PDF al sistema destino."""

    def __init__(self, page: Page, form, selectors: dict):
        self.page = page
        self.form = form
        self.selectors = selectors

    def upload(self, data: dict, pdf_path: Path | None = None) -> bool:
        """Completa el flujo: llenar formulario + adjuntar PDF del CFDI."""
        try:
            self.form.fill(data)
            if pdf_path is not None:
                self._attach_file(self.selectors["destination"]["invoice_form"]["upload_input"],
                                  pdf_path)
            return self.form.submit()
        except (PlaywrightTimeout, Exception) as exc:
            logger.error("Fallo la subida (UUID=%s): %s", data.get("uuid"), exc)
            self.page.screenshot(path=f"logs/upload_error_{data.get('uuid', 's/d')}.png")
            return False

    def _attach_file(self, input_selector: str, file_path: Path) -> None:
        logger.info("Adjuntando archivo: %s", file_path.name)
        self.page.set_input_files(input_selector, str(file_path))

    def attach_xml(self, xml_path: Path) -> None:
        self._attach_file(self.selectors["destination"]["invoice_form"]["upload_input"],
                          xml_path)
