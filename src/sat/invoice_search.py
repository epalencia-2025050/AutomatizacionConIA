"""Consulta de DTE recibidos en la Agencia Virtual de SAT Guatemala.

Detecta la tabla de resultados y los botones de descarga XML/PDF
mediante análisis de texto (cabeceras, contenido de celdas y
textos "XML"/"PDF"), lo que reduce dependencia de selectores exactos.
"""
import logging
import re

from playwright.sync_api import Page, TimeoutError as PWTimeout

logger = logging.getLogger(__name__)

UUID_RE = re.compile(r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-"
                     r"[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}")


class SatNavigationError(RuntimeError):
    """La pantalla del SAT no coincide con los selectores configurados."""


class InvoiceSearch:
    def __init__(self, page: Page, settings: dict, selectors: dict):
        self.page = page
        self.sat = settings["sat"]
        self.sel = selectors["consulta"]
        self.results: list[dict] = []

    def _manual_navigation(self, reason: str) -> None:
        message = (
            f"{reason}\n"
            "Navega manualmente en el navegador abierto hasta "
            "'Consultar DTE'. Cuando veas el formulario de consulta, vuelve "
            "a esta consola y presiona Enter."
        )
        if self.sat.get("headless", False):
            raise SatNavigationError(
                f"{reason} El modo headless no permite navegación manual. "
                "Verifica los selectores con "
                "'python tools/discover_dte_selectors.py' o configura "
                "sat.consulta_dte_url."
            )
        print(f"\n{message}\n")
        try:
            input()
        except EOFError:
            raise SatNavigationError(
                f"{reason} No hay consola interactiva para continuar."
            ) from None
        if self.page.is_closed() or "login.jsf" in self.page.url:
            raise SatNavigationError(
                "La página del SAT se cerró o volvió al login; inicia sesión "
                "y vuelve a intentar."
            )
        logger.info("Continuando con la navegación manual: %s", self.page.url)

    # ------------------------------------------------------------------
    def open_module(self) -> None:
        """Abre el módulo 'Consultar DTE' por URL directa o vía menú."""
        url = (self.sat.get("consulta_dte_url") or "").strip()
        timeout = self.sat["timeouts"]["default_ms"]
        if url:
            logger.info("Abriendo módulo Consultar DTE: %s", url)
            self.page.goto(url, timeout=timeout, wait_until="domcontentloaded")
            return
        logger.info("Sin URL directa; navegando por menú (selectores genéricos)")
        for paso in self.sel.get("menu_path", []):
            locator = self.page.locator(paso).first
            if locator.count() == 0:
                self._manual_navigation(
                    f"No se encontró el selector de menú {paso!r}; "
                    "los selectores actuales son genéricos."
                )
                return
            try:
                locator.click(timeout=timeout)
                self.page.wait_for_load_state("domcontentloaded")
            except PWTimeout:
                self._manual_navigation(
                    f"El selector de menú {paso!r} no se pudo abrir."
                )
                return

    def apply_filters(self, date_from: str, date_to: str,
                      tipo_operacion: str = "Recibidos") -> None:
        """Fechas (dd/MM/yyyy) y tipo de operación 'Recibidos'."""
        timeout = self.sat["timeouts"]["default_ms"]
        facs = self.sel["filtros"]

        # Tipo de operación (select, si existe) — POR CONFIRMAR
        try:
            sel_op = self.page.locator(facs["tipo_operacion"]).first
            if sel_op.count() > 0:
                sel_op.select_option(label=tipo_operacion)
        except Exception as exc:
            logger.debug("Filtro tipo_operación no aplicado: %s", exc)

        # Fechas por confirmar; son inputs genéricos con id conteniendo 'fecha'
        inputs = self.page.locator(facs["fecha_desde"])
        if inputs.count() < 2:
            raise SatNavigationError(
                "No se encontraron los dos campos de fecha de Consultar DTE. "
                "Verifica los selectores reales con "
                "'python tools/discover_dte_selectors.py'."
            )
        nombres = ["desde", "hasta"]
        for i, valor in enumerate([date_from, date_to]):
            try:
                objetivo = inputs.nth(i)
                objetivo.fill(valor, timeout=timeout)
            except Exception as exc:
                raise SatNavigationError(
                    f"No se pudo completar el campo de fecha {nombres[i]!r}. "
                    "Revisa los selectores reales en config/selectors.yaml."
                ) from exc

        buscar = self.page.locator(facs["buscar_btn"]).first
        if buscar.count() == 0:
            raise SatNavigationError(
                "No se encontró el botón Buscar de Consultar DTE. "
                "Verifica su selector con "
                "'python tools/discover_dte_selectors.py'."
            )
        try:
            buscar.click(timeout=timeout)
            self.page.wait_for_load_state("domcontentloaded")
            self.page.wait_for_timeout(2000)   # redes JSF/PrimeFaces
        except PWTimeout as exc:
            logger.error("No se pudo ejecutar la búsqueda: %s", exc)
            raise SatNavigationError(
                "No se pudo ejecutar la búsqueda en Consultar DTE; revisa "
                "el selector del botón Buscar."
            ) from exc

    # ------------------------------------------------------------------
    def read_results(self) -> list[dict]:
        """Lee la tabla de resultados de DTE (recibe: filas multidentificación)."""
        self.results = []
        timeout = self.sat["timeouts"]["default_ms"]
        try:
            self.page.wait_for_selector(self.sel["resultados"]["filas"],
                                        timeout=timeout)
        except PWTimeout:
            logger.info("La consulta no devolvió filas visibles")
            return []

        candidatos = sorted(
            self.page.query_selector_all(self.sel["resultados"]["tabla"]),
            key=lambda t: len(t.query_selector_all("tbody tr")),
            reverse=True,
        )
        if not candidatos:
            return []

        tabla = candidatos[0]
        headers = self._headers(tabla)

        for fila in tabla.query_selector_all(self.sel["resultados"]["filas"]):
            celdas = [c.inner_text().strip() for c in fila.query_selector_all("td")]
            if not any(celdas) or len(celdas) < 2:
                continue
            uuid = self._find_uuid(celdas)
            enlaces = self._download_buttons(fila)
            self.results.append({
                "uuid": uuid,
                "cells": celdas,
                "headers": headers,
                "links": enlaces,          # {"xml": handle|None, "pdf": handle|None}
            })

        logger.info("DTE leídos de la consulta: %s", len(self.results))
        return self.results

    # ------------------------------------------------------------------
    @staticmethod
    def _headers(tabla) -> dict:
        """Mapea nombre de cabecera -> índice de columna."""
        headers = {}
        primera = tabla.query_selector_all("thead tr, tr")
        if not primera:
            return headers
        celdas = primera[0].query_selector_all("th, td")
        for i, c in enumerate(celdas):
            texto = c.inner_text().strip().lower()
            if texto:
                headers[texto] = i
        return headers

    @staticmethod
    def _find_uuid(celdas: list[str]) -> str:
        for celda in celdas:
            match = UUID_RE.search(celda)
            if match:
                return match.group(0).upper()
        return ""

    @staticmethod
    def _download_buttons(fila) -> dict:
        """Detecta botones/links de descarga por su texto (XML/PDF)."""
        links = {"xml": None, "pdf": None}
        for a in fila.query_selector_all("a, button, input, span"):
            texto = ""
            try:
                texto = (a.inner_text() or a.get_attribute("title") or
                         a.get_attribute("value") or "").strip().upper()
            except Exception:
                continue
            if not texto:
                continue
            if "XML" in texto and links["xml"] is None:
                links["xml"] = a
            elif "PDF" in texto and links["pdf"] is None:
                links["pdf"] = a
        return links
