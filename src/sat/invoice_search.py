"""Consulta de DTE recibidos en la Agencia Virtual de SAT Guatemala.

Detecta la tabla de resultados y los botones de descarga XML/PDF
mediante análisis de texto (cabeceras, contenido de celdas y
textos "XML"/"PDF"), lo que reduce dependencia de selectores exactos.
"""
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path

from playwright.sync_api import Page, TimeoutError as PWTimeout

logger = logging.getLogger(__name__)

UUID_RE = re.compile(r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-"
                     r"[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}")


class SatNavigationError(RuntimeError):
    """La pantalla del SAT no coincide con los selectores configurados."""


class InvoiceSearch:
    # Defaults de clase: los tests instancian con __new__ (sin __init__)
    auth = None
    frame = None
    interno_vencido = False

    def __init__(self, page: Page, settings: dict, selectors: dict,
                 auth=None):
        self.page = page
        self.sat = settings["sat"]
        self.sel = selectors["consulta"]
        self.results: list[dict] = []
        self.frame = None   # iframe que contiene el formulario (si existe)
        self.auth = auth    # SatAuthentication para re-login automático
        self.interno_vencido = False   # app DTE del iframe rechazó la sesión

    # ------------------------------------------------------------------
    def _frame_activo(self):
        """Frame DOM donde vive el formulario; None => página principal.

        Los portlets de la Agencia Virtual cargan la CONSULTA DE DTE en
        un iframe interno: los selectores sólo funcionan buscos en el
        frame correcto.
        """
        if self.frame is not None:
            frames = getattr(self.page, "frames", None) or []
            if self.frame in frames:
                return self.frame
        return self._detectar_frame()

    def _detectar_frame(self):
        """Localiza el iframe del formulario Angular (DTE/FEL).

        Un frame candidato por nombre/URL sólo se acepta si contiene
        los marcadores reales del formulario (mat-select o campos de
        fecha): el portal puede reutilizar el iframe con contenido
        'Acceso no autorizado' cuando vence la sesión de la app interna.
        """
        frames = getattr(self.page, "frames", None) or []

        def _marcadores(fr):
            try:
                return (fr.locator('mat-select[name="tipoOperacion"]').count() > 0
                        or fr.locator('input[name="fechaEmisionIni"]').count() > 0
                        or fr.locator('text=CONSULTA DE DTE').count() > 0)
            except Exception:
                return False

        # Espera razonable al boot de Angular: el iframe puede existir
        # unos segundos antes de renderizar el formulario real.
        for _ in range(8):
            frames = getattr(self.page, "frames", None) or []
            candidatos = []
            for fr in frames:
                if fr is self.page.main_frame:
                    continue
                url = (fr.url or "").lower()
                if (fr.name == "iframeContent" or "dte" in url
                        or "felcons" in url):
                    candidatos.append(fr)
            if not candidatos:
                break   # aún no existe el iframe del DTE: nada que esperar
            for fr in candidatos:
                if _marcadores(fr):
                    self.frame = fr
                    logger.info("Frame del formulario: name=%r url=%s",
                                fr.name, fr.url)
                    return fr
            # ¿app interna vencida? (mensaje Angular dentro del frame)
            for fr in candidatos:
                try:
                    if fr.locator('text=Acceso no autorizado')\
                            .first.is_visible():
                        logger.warning("El iframe %r muestra 'Acceso no "
                                       "autorizado' (app interna del DTE "
                                       "vencida)", fr.name)
                        self.interno_vencido = True
                        self.frame = None
                        return None
                except Exception:
                    continue
            try:
                self.page.wait_for_timeout(250)
            except Exception:
                break
        logger.debug("Sin frame con formulario tras la espera de boot Angular")
        for fr in frames:
            if fr is self.page.main_frame:
                continue
            try:
                if fr.locator('text=Tipo de Operación').count() > 0:
                    self.frame = fr
                    logger.info("Formulario localizado en el iframe: %s (url=%s)",
                                fr.name or "(sin nombre)", fr.url)
                    return fr
            except Exception:
                continue
        self.frame = None
        return None

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
        """Abre 'Consultar DTE' por URL directa o navegando el menú solo."""
        url = (self.sat.get("consulta_dte_url") or "").strip()
        timeout = self.sat["timeouts"]["default_ms"]
        if url:
            logger.info("Abriendo módulo Consultar DTE: %s", url)
            self.page.goto(url, timeout=timeout, wait_until="domcontentloaded")

        if self._form_visible():
            logger.info("Formulario Consultar DTE ya visible; no navega el menú")
            return
        self._checar_sesion()
        if self._recuperar_sesion_interna():
            # tras el re-login la portada regeneró el iframe; se re-detecta
            self.interno_vencido = False
            self.frame = None
            if self._form_visible():
                logger.info("Formulario Consultar DTE visible tras el "
                            "re-login automático")
                return
        self._navegar_menu_automatico()

    def _recuperar_sesion_interna(self) -> bool:
        """Re-login automático forzado cuando la app interna del DTE venció.

        Las cookies TTL del portal pueden seguir vigentes mientras la app
        Angular del iframe (felcons) rechaza con 'Acceso no autorizado':
        se fuerza el re-login borrando la sesión previa para regenerar
        la autorización interna y el parámetro Clave del iframe.
        """
        if not self.interno_vencido or self.auth is None:
            return False
        logger.warning("App interna del DTE vencida: re-login completo "
                       "automático (sin intervención si el portal no pide "
                       "2FA)")
        try:
            self.auth._reiniciar_sesion()
            self.auth.login()
            logger.info("Re-login automático completado")
            return True
        except Exception as exc:
            logger.error("Re-login automático falló: %s", exc)
            raise

    # ------------------------------------------------------------------
    def _form_visible(self) -> bool:
        """True si ya estamos en la pantalla CONSULTA DE DTE (en el frame correcto)."""
        if self._detectar_frame() is not None:
            logger.info("Formulario Consultar DTE visible (en iframe)")
            return True
        dom = self._frame_activo() or self.page
        for señal in ('text=Tipo de Operación', 'text=CONSULTA DE DTE',
                      'text=Consulta de DTE'):
            if dom.locator(señal).count() > 0:
                return True
        return False

    def _checar_sesion(self) -> None:
        """Sesión muerta real: login.jsf con 'Acceso no autorizado'.

        En la portada el mensaje puede vivir en el portlet central aunque
        la sesión siga viva (el menú lateral funciona); en ese caso no
        se interrumpe nada.
        """
        try:
            if not self._acceso_denegado():
                return
            if "login.jsf" in self.page.url:
                raise SatNavigationError(
                    "El portal devolvió 'Acceso no autorizado' en la vista "
                    "de login: la sesión del SAT expiró o el estado de la "
                    "vista quedó inválido.")
            logger.info("'Acceso no autorizado' en el portlet central de "
                        "la portada; la sesión sigue activa (encabezado "
                        "de usuario presente)")
        except SatNavigationError:
            raise
        except Exception:
            pass

    def _dump_diagnostico(self, dom, nombre: str) -> None:
        """Guarda el HTML del frame en logs/<nombre>.html para calibrar."""
        try:
            Path("logs").mkdir(exist_ok=True)
            Path(f"logs/{nombre}.html").write_text(dom.content() or "",
                                                   encoding="utf-8")
            logger.info("DOM de diagnóstico guardado en logs/%s.html", nombre)
        except Exception as exc:
            logger.debug("No se pudo guardar el DOM de diagnóstico: %s", exc)

    def _acceso_denegado(self) -> bool:
        try:
            return self.page.locator(
                'text=Acceso no autorizado').first.is_visible()
        except Exception:
            return False

    def _menu_abierto(self) -> bool:
        """True sólo si los ítems del panel están VISIBLES en pantalla.

        PrimeFaces mantiene el menú en el DOM aunque el panel esté
        cerrado (display:none): count()>0 no sirve, hay visibility.
        """
        for sel in ('text=Agendar Cita', 'text=Servicios Tributarios'):
            try:
                if self.page.locator(sel).first.is_visible():
                    return True
            except Exception:
                continue
        return False

    def _abrir_menu_lateral(self) -> None:
        """Abre el panel lateral (☰/✕). Es el botón PrimeFaces
        #btnContraerMenu (CONFIRMADO con el DOM real)."""
        if self._menu_abierto():
            return   # ya abierto en pantalla
        for sel in ('#btnContraerMenu',
                    'button[name="btnContraerMenu"]',
                    'button[id*="ContraerMenu"]',
                    'span.pi-bars',
                    'button[aria-label*="menu" i]',
                    '.navbar-toggler, .o-menu-button, button.menutoggle'):
            try:
                btn = self.page.locator(sel).first
                if btn.count() > 0 and btn.is_visible():
                    btn.click(timeout=3000)
                    self.page.wait_for_timeout(300)
                    if self._menu_abierto():
                        logger.info("Menú lateral abierto vía %r", sel)
                        return
            except Exception:
                continue
        # Último recurso por JS: el onclick del botón llama a toggleMenu
        try:
            self.page.evaluate(
                "() => { if (typeof toggleMenu === 'function') "
                "toggleMenu(new Event('click')); }")
            self.page.wait_for_timeout(1000)
            if self._menu_abierto():
                logger.info("Menú lateral abierto vía toggleMenu JS")
                return
        except Exception as exc:
            logger.debug("toggleMenu JS no disponible: %s", exc)
        # El toggle vive en la esquina superior izquierda del encabezado:
        # se clican los elementos clicables de esa esquina ordenados por
        # cercanía, verificando tras cada uno.
        logger.info("Hamburguesa sin selector efectivo; se buscan "
                    "clicables en la esquina superior izquierda")
        try:
            candidatos = []
            for el in self.page.locator(
                    'a, button, span, i, img, md-icon, mat-icon, '
                    '[role="button"], [onclick]').all():
                try:
                    box = el.bounding_box()
                except Exception:
                    continue
                if not box:
                    continue
                x, y = box.get("x", -1), box.get("y", -1)
                if 0 <= x <= 70 and 0 <= y <= 200 \
                        and box.get("width", 0) <= 60 \
                        and box.get("height", 0) <= 60:
                    candidatos.append((x * x + y * y, x, y))
            for _, x, y in sorted(candidatos):
                try:
                    self.page.mouse.click(x + 12, y + 12)
                    self.page.wait_for_timeout(800)
                    if self._menu_abierto():
                        logger.info("Menú lateral abierto con clic en "
                                    "(%s, %s)", x + 12, y + 12)
                        return
                except Exception:
                    continue
        except Exception as exc:
            logger.debug("Búsqueda de esquina falló: %s", exc)
        # Respaldo posicional clásico (coincide con la pantalla real)
        for (x, y) in ((25, 123), (28, 106), (30, 125), (20, 120)):
            try:
                self.page.mouse.click(x, y)
                self.page.wait_for_timeout(800)
                if self._menu_abierto():
                    logger.info("Menú lateral abierto con clic en (%s, %s)",
                                x, y)
                    return
            except Exception:
                continue

    def _clic_opcion_menu(self, patrones: tuple[str, ...],
                          timeout: int) -> bool:
        """Clic (o hover como respaldo) sobre la opción de menú visible.

        Recorre los elementos que coinciden con cada patrón, salta los
        invisibles y devuelve True al primer clic exitoso.
        """
        for patron in patrones:
            try:
                loc = self.page.locator(patron)
                n = min(loc.count(), 6)
            except Exception:
                continue
            for i in range(n):
                item = loc.nth(i)
                try:
                    if not item.is_visible():
                        continue
                except Exception:
                    continue
                try:
                    item.click(timeout=3000)
                    return True
                except Exception:
                    try:
                        item.hover(timeout=3000)
                        return True
                    except Exception:
                        continue
        return False

    def _desplegar_submenu(self, patron_item: str, patron_senal: str,
                           timeout: int) -> bool:
        """Clic sobre un ítem del menú hasta que su submenú sea visible.

        PrimeFaces a veces consume el primer clic (sólo resalta el ítem)
        y exige un segundo clic (incluso doble clic) para desplegar la
        columna siguiente: se reintenta y se VERIFICA con la señal del
        nivel siguiente antes de continuar.
        """
        intentos = ("click", "click", "dblclick", "hover")
        for modo in intentos:
            try:
                if self.page.locator(patron_senal).first.is_visible():
                    return True   # el nivel ya se desplegó
            except Exception:
                pass
            try:
                item = self.page.locator(patron_item).first
                if not item.is_visible():
                    continue
                if modo == "click":
                    item.click(timeout=timeout)
                elif modo == "dblclick":
                    item.dblclick(timeout=timeout)
                else:
                    item.hover(timeout=timeout)
                try:
                    self.page.wait_for_timeout(300)
                except Exception:
                    pass
            except Exception:
                continue
        try:
            return self.page.locator(patron_senal).first.is_visible()
        except Exception:
            return False

    def _navegar_menu_automatico(self) -> None:
        """Navega el menú lateral real de 3 columnas (captura nov 2026):

        ☰ -> 'Servicios Tributarios >' (columna 2)
           -> 'Factura Electrónica en Línea (FEL) >' (columna 3)
              -> 'Consultar DTE'   (carga el iframe con la app del DTE)
        Si falta algún paso queda la navegación manual como respaldo.
        """
        timeout = self.sat["timeouts"]["default_ms"]

        self._abrir_menu_lateral()

        # 1) Columna 2: desplegar con 'Servicios Tributarios' (la señal
        #    es que 'Factura Electrónica...' se haga visible)
        if not self._desplegar_submenu(
                'text=Servicios Tributarios',
                'text=Factura Electrónica en Línea', timeout):
            self._manual_navigation(
                "La columna 2 del menú no se desplegó tras 'Servicios "
                "Tributarios' (primer y segundo clic).")
            return

        # 2) Columna 3: desplegar con 'Factura Electrónica en Línea (FEL)'.
        #    TEXTO ESPECÍFICO: el genérico has-text("Factura") también
        #    caería en 'Factura y Declaración Única Centroamericana'.
        if not self._desplegar_submenu(
                'text=Factura Electrónica en Línea',
                'text=Consultar DTE', timeout):
            self._manual_navigation(
                "No se encontró 'Factura Electrónica en Línea (FEL)' en el "
                "submenú de Servicios Tributarios.")
            return

        # 3) Clic final: 'Consultar DTE'
        if not self._clic_opcion_menu(
                ('text=Consultar DTE', 'text=Consulta de DTE'), timeout):
            self._manual_navigation(
                "No se pudo hacer clic en 'Consultar DTE'.")
            return
        if self._form_visible():
            logger.info("Formulario Consultar DTE alcanzado")
            return
        self._manual_navigation(
            "No se alcanzó el formulario de Consulta DTE por el menú.")

    @staticmethod
    def _respetar_rango_sat(date_from: str, date_to: str) -> tuple[str, str]:
        """El SAT rechaza rangos mayores a 3 meses ('Periodo demasiado
        extendido'). Si el rango excede el límite se recorta date_from
        a 3 meses antes de date_to, dejándolo registrado en el log."""
        try:
            f = datetime.strptime(date_from, "%d/%m/%Y")
            t = datetime.strptime(date_to, "%d/%m/%Y")
        except Exception:
            return date_from, date_to   # formato inesperado: Portal validará
        limite = 92   # ~3 meses
        if (t - f).days <= limite:
            return date_from, date_to
        nuevo = t - timedelta(days=limite)
        date_from = nuevo.strftime("%d/%m/%Y")
        logger.warning("Rango mayor a 3 meses (límite del SAT): se recorta "
                       "date_from a %s", date_from)
        return date_from, date_to

    @staticmethod
    def _a_formato_sat(fecha: str) -> str:
        """Convierte dd/MM/yyyy -> MM/dd/yyyy.

        EVIDENCIA (DOM nov 2026): el app del DTE parsea '02/11/2026'
        como 11 de FEBRERO (Hasta recibió min='2026-02-11' y Desde
        max='2026-09-11' tras escribir '09/11/2026'). Es decir, el
        componente Angular usa formato M/d (en-US): el rango del
        usuario en dd/MM se invierte antes de escribir.
        """
        try:
            d, m, a = fecha.split("/")
            return f"{m}/{d}/{a}"
        except Exception:
            return fecha

    def apply_filters(self, date_from: str, date_to: str,
                      tipo_operacion: str = "Recibidos") -> None:
        """Fechas (dd/MM/yyyy) y tipo de operación 'Recibidos'."""
        timeout = self.sat["timeouts"]["default_ms"]
        date_from, date_to = self._respetar_rango_sat(date_from, date_to)
        facs = self.sel["filtros"]
        dom = self._frame_activo() or self.page
        logger.info("Operando en %s",
                    f"iframe: {self.frame.url}" if self.frame
                    else "documento principal")

        # =========== CAMINO CONFIRMADO: Angular Material (frame) ===========
        # 1) Tipo de Operación: mat-select -> clic -> esperar overlay -> clic opción
        try:
            mat = dom.locator(facs.get("tipo_operacion_mat")
                              or 'mat-select[name="tipoOperacion"]').first
            if mat.count() > 0:
                mat.click(timeout=timeout)
                # Esperar a que el panel de opciones de Angular Material esté visible en el DOM
                opt_locator = dom.locator("mat-option:has-text('Recibidos')").first
                try:
                    opt_locator.wait_for(state="visible", timeout=3000)
                    opt_locator.click(timeout=3000)
                except Exception:
                    # Si no estuvo en el frame, buscar en la página principal
                    opt_page = self.page.locator("mat-option:has-text('Recibidos')").first
                    opt_page.wait_for(state="visible", timeout=3000)
                    opt_page.click(timeout=3000)
                
                # Cerrar cualquier overlay o backdrop residual si quedara abierto
                try:
                    if dom.locator(".cdk-overlay-backdrop").first.is_visible():
                        dom.keyboard.press("Escape")
                except Exception:
                    pass

                texto_op = (mat.inner_text() or "").strip()
                logger.info("Tipo de operación quedó: %r", texto_op)
                if "recibido" not in texto_op.lower():
                    raise SatNavigationError(f"No se pudo seleccionar 'Recibidos', quedó: {texto_op}")
        except Exception as exc:
            logger.debug("mat-select no aplicado (%s); se prueba <select>", exc)
            # ---- respaldo: <select> clásico ----
            try:
                sel_op = dom.locator(facs["tipo_operacion"]).first
                if sel_op.count() > 0:
                    sel_op.select_option(label=tipo_operacion)
                    aplicado = self._texto_opcion(sel_op)
                    if tipo_operacion.lower() not in aplicado.lower():
                        for s in dom.locator(
                                facs.get("tipo_candidatos") or "form select").all():
                            opciones = [o.strip() for o in s.evaluate(
                                "e => [...e.options].map(o => o.text)") if o]
                            if any(tipo_operacion.lower() in o.lower()
                                   for o in opciones):
                                s.select_option(label=tipo_operacion)
                                break
            except Exception as exc2:
                logger.debug("Filtro tipo_operación no aplicado: %s", exc2)

        # 2) Fechas: inputs con name confirmado (fechaEmisionIni/Final)
        f_ini = dom.locator(facs.get("fecha_ini_mat")
                            or 'input[name="fechaEmisionIni"]')
        f_fin = dom.locator(facs.get("fecha_fin_mat")
                            or 'input[name="fechaEmisionFinal"]')
        if f_ini.count() and f_fin.count():
            campos = [("desde", f_ini, date_from), ("hasta", f_fin, date_to)]
        else:
            # ---- respaldo genérico: dos inputs 'fecha' ----
            inputs = dom.locator(facs["fecha_desde"])
            if inputs.count() < 2:
                self._dump_diagnostico(dom, "frame_fail")
                raise SatNavigationError(
                    "No se encontraron los campos de fecha de Consultar DTE "
                    "(ni los confirmados ni los genéricos). DOM guardado en "
                    "logs/frame_fail.html para calibrar selectores.")
            campos = [("desde", inputs.nth(0), date_from),
                      ("hasta", inputs.nth(1), date_to)]
        # El app interpreta M/d/yyyy: se invierte día/mes del rango del
        # usuario (definido en dd/MM/yyyy) antes de escribir.
        campos = [(n, c, self._a_formato_sat(v)) for n, c, v in campos]
        logger.info("Fechas en formato del portal (M/d): desde=%s hasta=%s",
                    campos[0][2], campos[1][2])
        for nombre, campo, valor in campos:
            self._completar_fecha(nombre, campo, dom, valor, timeout)

        # 3) Buscar: button submit Angular con texto 'Buscar'
        buscar = dom.locator(facs.get("buscar_btn_mat")
                             or "button:has-text('Buscar')").first
        if buscar.count() == 0:
            buscar = dom.locator(facs["buscar_btn"]).first
        if buscar.count() == 0:
            raise SatNavigationError(
                "No se encontró el botón Buscar de Consultar DTE. "
                "Verifica su selector con "
                "'python tools/discover_dte_selectors.py'."
            )
        try:
            buscar.click(timeout=timeout)
        except PWTimeout as exc:
            logger.error("No se pudo ejecutar la búsqueda: %s", exc)
            raise SatNavigationError(
                "No se pudo ejecutar la búsqueda en Consultar DTE; revisa "
                "el selector del botón Buscar."
            ) from exc

        # El portal responde validaciones con un diálogo modal Angular (mat-dialog-container)
        # 'Favor de llenar los campos obligatorios', 'Periodo demasiado extendido...', etc.
        try:
            dialogo = dom.locator("mat-dialog-container").first
            if dialogo.count() > 0 and dialogo.is_visible():
                texto = (dialogo.inner_text() or "").strip()
                if texto:
                    logger.error("Diálogo de error del SAT tras Buscar: %s",
                                 texto.replace("\n", " | ")[:300])
                    try:
                        dom.locator('button:has-text("Cerrar")').first\
                            .click(timeout=3000)
                    except Exception:
                        pass
                    self._dump_diagnostico(dom, "buscar_error")
                    raise SatNavigationError(
                        f"El formulario rechazó la búsqueda: {texto[:200]}")
        except SatNavigationError:
            raise
        except Exception:
            pass

    def _completar_fecha(self, nombre: str, campo, dom, valor: str,
                          timeout: int) -> None:
        """Escribe una fecha (dd/MM/yyyy) en el input y VERIFICA.

        El campo es de Angular Material con datepicker (aria-haspopup):
        el componente limpia el valor si no lo reconoce, así que se
        intenta por estrategias hasta que input_value() confirme:

        1) fill directo (a veces funciona, ideal)
        2) teclado humano: click -> Escape (cierra el calendario que
           suele abrirse al enfocar) -> Ctrl+A -> sólo dígitos
           ('09112026'; la máscara dd/MM/yyyy los formatea sola)
        3) eventos JS input/change/blur (validado en
           tools/test_full_flow.py)
        4) si nada dejó el valor: dump de DOM y error con detalle
        """

        def _valor_actual() -> str:
            try:
                return (campo.input_value() or "").strip()
            except Exception:
                return ""

        def _bien(actual: str) -> bool:
            # acepta dd/MM/yyyy completo o recortado ('02/11' visible)
            return valor in actual

        # --- 1) fill directo ---
        try:
            campo.fill(valor, timeout=timeout)
        except Exception as exc:
            logger.debug("fill directo falló en fecha %s: %s", nombre, exc)
        actual = _valor_actual()
        if _bien(actual):
            logger.info("Fecha %s escrita (fill directo): %r", nombre, actual)
            return

        # --- 2) teclado humano con la máscara ---
        try:
            campo.click(timeout=timeout)
            self.page.wait_for_timeout(200)
            # el datepicker puede abrir su overlay al enfocar: cerrarlo
            self.page.keyboard.press("Escape")
            self.page.wait_for_timeout(250)
            try:
                if dom.locator(".cdk-overlay-pane").first.is_visible():
                    self.page.keyboard.press("Escape")
                    self.page.wait_for_timeout(200)
            except Exception:
                pass
            self.page.keyboard.press("Control+a")
            self.page.keyboard.type(re.sub(r"\D", "", valor), delay=90)
            self.page.keyboard.press("Tab")
            self.page.wait_for_timeout(400)
        except Exception as exc:
            logger.debug("teclado falló en fecha %s: %s", nombre, exc)
        actual = _valor_actual()
        if _bien(actual):
            logger.info("Fecha %s escrita (teclado/máscara): %r",
                        nombre, actual)
            return
        # reintento con la fecha formateada COMPLETA por si la máscara
        # exige los separadores
        try:
            campo.click(timeout=timeout)
            self.page.keyboard.press("Escape")
            self.page.wait_for_timeout(200)
            self.page.keyboard.press("Control+a")
            self.page.keyboard.type(valor, delay=60)
            self.page.keyboard.press("Tab")
            self.page.wait_for_timeout(400)
        except Exception as exc:
            logger.debug("teclado completo falló en fecha %s: %s",
                         nombre, exc)
        actual = _valor_actual()
        if _bien(actual):
            logger.info("Fecha %s escrita (teclado dd/MM/yyyy): %r",
                        nombre, actual)
            return

        # --- 3) eventos JS ---
        try:
            campo.evaluate(
                "(el, v) => { el.value = v;"
                " el.dispatchEvent(new Event('input', {bubbles:true}));"
                " el.dispatchEvent(new Event('change', {bubbles:true}));"
                " el.dispatchEvent(new Event('blur', {bubbles:true}));"
                " }", valor)
            self.page.wait_for_timeout(300)
        except Exception as exc:
            logger.debug("eventos JS fallaron en fecha %s: %s", nombre, exc)
        actual = _valor_actual()
        if _bien(actual):
            logger.info("Fecha %s escrita (eventos JS): %r", nombre, actual)
            return

        # --- 4) diagnóstico ---
        self._dump_diagnostico(dom, "frame_fail")
        raise SatNavigationError(
            f"El campo de fecha {nombre!r} no aceptó el valor {valor!r} "
            f"(quedó {actual!r} tras fill/teclado/JS). DOM guardado en "
            "logs/frame_fail.html.")

    @staticmethod
    def _texto_opcion(select_locator) -> str:
        """Texto de la opción actualmente seleccionada de un <select>."""
        try:
            return select_locator.evaluate(
                "e => { const o = e.options[e.selectedIndex];"
                " return o ? o.text : '' }")
        except Exception:
            return ""

    # ------------------------------------------------------------------
    def read_results(self) -> list[dict]:
        """Lee la tabla de resultados de DTE (recibe: filas multidentificación)."""
        self.results = []
        timeout = self.sat["timeouts"]["default_ms"]
        dom = self._frame_activo() or self.page
        try:
            # rangos amplios pueden tardar más del default en rendir la tabla
            dom.wait_for_selector(self.sel["resultados"]["filas"],
                                  timeout=timeout * 2)
        except PWTimeout:
            logger.info("La consulta no devolvió filas visibles (se esperaron "
                        "%s s para la tabla)", timeout * 2 / 1000)
            try:   # diagnóstico: ¿la tabla existe sin filas? dump DOM
                Path("logs").mkdir(exist_ok=True)
                Path("logs/results_dom.html").write_text(
                    dom.content() or "", encoding="utf-8")
                logger.info("DOM del área de resultados guardado en "
                            "logs/results_dom.html")
            except Exception:
                pass
            return []

        candidatos = sorted(
            dom.query_selector_all(self.sel["resultados"]["tabla"]),
            key=lambda t: len(t.query_selector_all("mat-row, .mat-row, tbody tr")),
            reverse=True,
        )
        if not candidatos:
            return []

        tabla = candidatos[0]
        headers = self._headers(tabla)

        for fila in tabla.query_selector_all(self.sel["resultados"]["filas"]):
            celdas = [c.inner_text().strip() for c in fila.query_selector_all("mat-cell, .mat-cell, td")]
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
        if self.results:
            try:   # volcado de apoyo para calibrar botones de descarga
                Path("logs/results_dom.html").parent.mkdir(exist_ok=True)
                Path("logs/results_dom.html").write_text(dom.content() or "",
                                                         encoding="utf-8")
                logger.info("DOM de resultados guardado en logs/results_dom.html")
            except Exception:
                pass
        return self.results

    # ------------------------------------------------------------------
    @staticmethod
    def _headers(tabla) -> dict:
        """Mapea nombre de cabecera -> índice de columna."""
        headers = {}
        primera = tabla.query_selector_all("mat-header-row, thead tr, tr")
        if not primera:
            return headers
        celdas = primera[0].query_selector_all("mat-header-cell, th, td")
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
