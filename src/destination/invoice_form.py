"""Llenado del formulario de factura en el sistema destino."""
import logging

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout

logger = logging.getLogger(__name__)


class InvoiceForm:
    """Abre el formulario de nueva factura e ingresa los datos del CFDI."""

    def __init__(self, page: Page, selectors: dict):
        self.page = page
        self.selectors = selectors  # clave invoice_form
        self.timeout = 15_000

    def open_new_invoice(self) -> None:
        s = self.selectors
        try:
            self.page.click(s["new_invoice_button"], timeout=self.timeout)
            self.page.wait_for_load_state("domcontentloaded")
        except PlaywrightTimeout:
            logger.error("No se pudo abrir el formulario de nueva factura")
            raise

    def fill(self, data: dict) -> None:
        """Llena el formulario con los metadatos del CFDI extraídos."""
        s = self.selectors
        self.open_new_invoice()
        self.page.fill(s["rfc_input"], data.get("rfc_emisor", ""), timeout=3000)
        self.page.fill(s["uuid_input"], data.get("uuid", ""), timeout=3000)
        self.page.fill(s["total_input"], str(data.get("total", "")), timeout=3000)

    def submit(self) -> bool:
        s = self.selectors
        self.page.click(s["save_button"], timeout=self.timeout)
        try:
            self.page.wait_for_selector(s["success_toast"], timeout=self.timeout)
            logger.info("Factura registrada en el destino (UUID=%s)", self.uuid_value)
            return True
        except PlaywrightTimeout:
            logger.warning("No se detectó confirmación del guardado")
            return False

    # propiedad usada por el Uploader para logging
    @property
    def uuid_value(self) -> str:
        try:
            return self.page.input_value(self.selectors["uuid_input"], timeout=2000)
        except Exception:
            return ""
