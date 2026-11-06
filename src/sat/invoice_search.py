"""Búsqueda de CFDIs en el portal del SAT."""
import datetime
import logging

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout

logger = logging.getLogger(__name__)


class InvoiceSearch:
    """Realiza búsquedas de facturas (recibidas/emitidas) en el portal."""

    def __init__(self, page: Page, selectors: dict):
        self.page = page
        self.selectors = selectors
        self.retries = 3
        self.results: list[dict] = []

    def search(self, date_from=None, date_to=None, issuer_rfc=None) -> list[dict]:
        """Regresa una lista de resultados: {row_index, uuid?, folio?, element}."""
        s = self.selectors
        timeout_default = 15_000

        self._open_module(s["menu"]["received_tab"].replace('a:has-text("', "").replace('")' , ""),
                          timeout_default)
        self._fill_dates(date_from, date_to, timeout_default)
        if issuer_rfc:
            try:
                self.page.fill(s["search"]["rfc_emitter_input"], issuer_rfc, timeout=3000)
            except PlaywrightTimeout:
                logger.debug("No existe campo de RFC emisor; se omite el filtro")

        self.page.click(s["search"]["search_button"], timeout=timeout_default)
        self.page.wait_for_load_state("domcontentloaded", timeout=timeout_default)

        return self._read_results()

    def _open_module(self, module_name: str, timeout: int) -> None:
        """Navega al módulo de facturas (Recibidos/Emitidos)."""
        if "Lista" in self.page.url:
            return
        try:
            self.page.click(f'a:has-text("{module_name}")', timeout=timeout)
            self.page.wait_for_load_state("domcontentloaded", timeout=timeout)
        except PlaywrightTimeout:
            logger.warning("No se pudo abrir el módulo %s directamente", module_name)

    def _fill_dates(self, date_from, date_to, timeout: int) -> None:
        today = datetime.date.today()
        date_from = date_from or today.strftime("%d/%m/%Y")
        date_to = date_to or today.strftime("%d/%m/%Y")
        s = self.selectors["search"]
        self.page.fill(s["date_from_input"], date_from, timeout=timeout)
        self.page.fill(s["date_to_input"], date_to, timeout=timeout)
        # Cierra el calendario para que el campo tome el valor
        self.page.keyboard.press("Escape")

    def _read_results(self) -> list[dict]:
        s = self.selectors
        if self.page.query_selector(s["search"]["no_results_message"]):
            logger.info("El SAT no devolvió resultados")
            return []

        rows = self.page.query_selector_all(s["search"]["result_row"])
        results = []
        for index, row in enumerate(rows):
            try:
                fields = [cell.inner_text().strip() for cell in row.query_selector_all("td")]
                if not fields:
                    continue
                results.append(
                    {
                        "row_index": index,
                        "folio": fields[2] if len(fields) > 2 else "",
                        "rfc_emisor": fields[1] if len(fields) > 1 else "",
                        "fecha": fields[3] if len(fields) > 3 else "",
                        "element": row,
                    }
                )
            except Exception as exc:
                logger.debug("Fila %s ignorada: %s", index, exc)
        self.results = results
        logger.info("%s filas CFDI analizadas", len(results))
        return results

    def has_results(self) -> bool:
        s = self.selectors
        return self.page.query_selector(s["search"]["result_row"]) is not None or bool(self.results)
