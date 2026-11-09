"""GUI Tkinter del sistema (Fase 4).

Ventana con:
 - rango de fechas dd/mm/yyyy y opción headless
 - botones: ejecutar todo, solo procesar, solo subir, reprocesar
   errores, generar reporte
 - log en vivo: logging -> queue -> Text (hilo seguro con after())
Los procesos corren en un hilo aparte; la GUI nunca se congela y los
botones se deshabilitan mientras hay una tarea activa.
"""
import logging
import queue
import threading
import tkinter as tk
from tkinter import scrolledtext, messagebox, ttk

from src.orchestrator import Orchestrator

TITULO = "Automatización DTE — SAT Guatemala → Odoo"
FIN = object()  # centinela de fin de hilo


class GuiLogHandler(logging.Handler):
    """Envía cada línea de log a la cola que la GUI consume con after()."""

    def __init__(self, cola: queue.Queue):
        super().__init__(logging.INFO)
        self.cola = cola

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.cola.put_nowait(self.format(record))
        except Exception:   # nunca romper la app por logging
            pass


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.cola: queue.Queue = queue.Queue()
        self.hilo: threading.Thread | None = None
        self._attach_log_handler()

        root.title(TITULO)
        root.geometry("880x600")
        root.minsize(720, 480)
        self._construir_controles()
        self._construir_log()
        self._construir_visor_bd()
        self._construir_barra_estado()
        root.after(150, self._drenar_cola)

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _construir_controles(self) -> None:
        topo = ttk.Frame(self.root, padding=10)
        topo.pack(fill="x")

        ttk.Label(topo, text="Desde (dd/mm/yyyy):").grid(row=0, column=0,
                                                         sticky="w")
        self.fecha_desde = ttk.Entry(topo, width=12)
        self.fecha_desde.grid(row=0, column=1, padx=(4, 12))

        ttk.Label(topo, text="Hasta (dd/mm/yyyy):").grid(row=0, column=2,
                                                         sticky="w")
        self.fecha_hasta = ttk.Entry(topo, width=12)
        self.fecha_hasta.grid(row=0, column=3, padx=(4, 12))

        self.headless_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(topo, text="Ejecutar navegador sin ventana (headless)",
                        variable=self.headless_var).grid(row=0, column=4,
                                                         padx=8, sticky="w")

        botones = ttk.Frame(self.root, padding=(10, 0, 10, 6))
        botones.pack(fill="x")
        self.botones = {}
        acciones = (
            ("ejecutar", "▶ Ejecutar todo (SAT → procesar → subir)",
             self.ejecutar_todo),
            ("procesar", "⚙ Solo procesar XML", self.solo_procesar),
            ("subir", "⇪ Solo subir a destino (Odoo)", self.solo_subir),
            ("reprocesar", "↻ Reprocesar errores", self.reprocesar_errores),
            ("reporte", "📄 Generar reporte", self.generar_reporte),
        )
        for i, (clave, texto, fn) in enumerate(acciones):
            btn = ttk.Button(botones, text=texto, command=fn)
            btn.grid(row=0, column=i, padx=3, sticky="w")
            self.botones[clave] = btn

    def _construir_log(self) -> None:
        marco = ttk.LabelFrame(self.root, text=" Registro en vivo ",
                               padding=8)
        marco.pack(fill="both", expand=True, padx=10, pady=6)
        self.txt = scrolledtext.ScrolledText(marco, wrap="word", height=20,
                                             font=("Consolas", 9))
        self.txt.pack(fill="both", expand=True)
        self.txt.tag_config("ERROR", foreground="#b91c1c")
        self.txt.tag_config("WARNING", foreground="#b45309")
        self.txt.tag_config("INFO", foreground="#1f2937")

    def _construir_barra_estado(self) -> None:
        barra = ttk.Frame(self.root, padding=(10, 4))
        barra.pack(fill="x")
        self.estado = tk.StringVar(value="En espera")
        ttk.Label(barra, textvariable=self.estado,
                  font=("Segoe UI", 9, "bold")).pack(side="left")

    def _construir_visor_bd(self) -> None:
        """Fase 7: consulta rápida de la BD sin abrir DB Browser."""
        marco = ttk.LabelFrame(self.root, text=" Facturas en la base de datos ",
                               padding=8)
        marco.pack(fill="x", padx=10, pady=6)

        filtros = ttk.Frame(marco); filtros.pack(fill="x")
        ttk.Label(filtros, text="Buscar:").pack(side="left")
        self.filtro_texto = ttk.Entry(filtros, width=22)
        self.filtro_texto.pack(side="left", padx=(4, 10))
        ttk.Label(filtros, text="Estado:").pack(side="left")
        self.filtro_estado = ttk.Combobox(
            filtros, width=18, values=("Todos", "DESCARGADA", "VALIDADA",
                                       "PENDIENTE_SUBIDA", "SUBIDA", "ERROR"),
            state="readonly")
        self.filtro_estado.current(0)
        self.filtro_estado.pack(side="left", padx=(4, 10))
        ttk.Button(filtros, text="🔍 Consultar",
                   command=self.consultar_bd).pack(side="left")
        self.resumen_bd = tk.StringVar(value="")
        ttk.Label(filtros, textvariable=self.resumen_bd).pack(side="left",
                                                              padx=12)

        columnas = ("fecha", "nit", "emisor", "total", "estado", "uuid")
        self.tabla = ttk.Treeview(marco, columns=columnas, show="headings",
                                  height=7)
        anchos = {"fecha": 110, "nit": 100, "emisor": 200, "total": 90,
                  "estado": 130, "uuid": 290}
        for c, texto in zip(columnas, ("Emisión", "NIT", "Emisor",
                                       "Total", "Estado", "UUID")):
            self.tabla.heading(c, text=texto)
            self.tabla.column(c, width=anchos[c], anchor="w")
        self.tabla.pack(fill="x")
        self.consultar_bd()

    def consultar_bd(self) -> None:
        """Lista facturas con el filtro actual (lectura, nunca modifica)."""
        try:
            orch = self._nuevo_orchestrator()
            from src.database.repository import Repository
            repo = Repository(orch.db_path)
        except Exception as exc:   # pylint: disable=broad-except
            messagebox.showerror("BD", f"No se pudo abrir la BD: {exc}")
            return
        texto = self.filtro_texto.get().strip().lower()
        est = self.filtro_estado.get()
        estado_sql = None if est == "Todos" else est

        for fila in self.tabla.get_children():
            self.tabla.delete(fila)
        sql = ("SELECT fecha_emision, nit_emisor, nombre_emisor, total, "
               "estado, uuid FROM facturas ORDER BY id DESC")
        filas = repo.conn.execute(sql).fetchall()
        total = 0
        for f in filas:
            d = dict(f)
            if estado_sql and d.get("estado") != estado_sql:
                continue
            combinado = " ".join(str(d.get(k) or "") for k in
                                 ("uuid", "nombre_emisor", "nit_emisor",
                                  "fecha_emision")).lower()
            if texto and texto not in combinado:
                continue
            self.tabla.insert("", "end", values=(
                d.get("fecha_emision") or "", d.get("nit_emisor") or "",
                d.get("nombre_emisor") or "", d.get("total") or "",
                d.get("estado") or "", d.get("uuid") or ""))
            if d.get("estado") == "SUBIDA":
                total += 1
        self.resumen_bd.set(f"{len(self.tabla.get_children())} facturas "
                            f"({total} subidas)")

    # ------------------------------------------------------------------
    # Log en vivo
    # ------------------------------------------------------------------
    def _attach_log_handler(self) -> None:
        handler = GuiLogHandler(self.cola)
        handler.setFormatter(logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(message)s", "%H:%M:%S"))
        logging.getLogger().addHandler(handler)

    def _drenar_cola(self) -> None:
        try:
            while True:
                item = self.cola.get_nowait()
                if item is FIN:
                    self._fin_tarea()
                    continue
                nivel = item.split("|", 2)[1].strip() if item.count("|") >= 2 else "INFO"
                tag = nivel if nivel in ("ERROR", "WARNING") else "INFO"
                self.txt.insert(tk.END, item.rstrip() + "\n", tag)
                self.txt.see(tk.END)
                # Fase 7: el SAT pidió 2FA -> avisar con campana y banner
                if "ALERTA_SAT_PIDE_2FA" in item:
                    self.txt.tag_config("ALERTA2FA", foreground="#7c2d12",
                                        background="#fde68a")
                    self.root.bell()
                    self.estado.set(f"⚠ {self.estado.get()} | SAT pide 2FA: "
                                    "revisa el navegador y tu teléfono")
        except queue.Empty:
            pass
        self.root.after(200, self._drenar_cola)

    # ------------------------------------------------------------------
    # Ejecución en hilo
    # ------------------------------------------------------------------
    def _en_hilo(self, fn, *args) -> None:
        if self.hilo is not None and self.hilo.is_alive():
            messagebox.showwarning("Ocupado", "Hay una tarea en ejecución.")
            return
        self._inicio_tarea()
        self.hilo = threading.Thread(target=self._worker, args=(fn, *args),
                                     daemon=True)
        self.hilo.start()

    def _worker(self, fn, *args) -> None:
        try:
            resultado = fn(*args)
            self.cola.put(f"-- TAREA FINALIZADA -> {resultado}")
        except Exception as exc:   # pylint: disable=broad-except
            logging.getLogger(__name__).exception("Fallo en la tarea de la GUI")
            self.cola.put(f"ERROR | gui | La tarea terminó con error: {exc}")
        finally:
            self.cola.put(FIN)

    def _inicio_tarea(self) -> None:
        for b in self.botones.values():
            b.state(["disabled"])
        self.estado.set("Ejecutando... el navegador abrirá si la tarea lo requiere")

    def _fin_tarea(self) -> None:
        for b in self.botones.values():
            b.state(["!disabled"])
        self.estado.set("En espera")
        self.txt.insert(tk.END, "-" * 70 + "\n", "INFO")
        self.txt.see(tk.END)

    # ------------------------------------------------------------------
    # Orquestador (se construye en el hilo; la GUI se queda libre)
    # ------------------------------------------------------------------
    def _nuevo_orchestrator(self) -> Orchestrator:
        orch = Orchestrator()
        headless = bool(self.headless_var.get())
        orch.settings.setdefault("sat", {})["headless"] = headless
        dest = orch.settings.setdefault("destination", {})
        dest.setdefault("browser", {})["headless"] = headless
        return orch

    def _validar_fechas(self) -> tuple[str | None, str | None]:
        desde = self.fecha_desde.get().strip() or None
        hasta = self.fecha_hasta.get().strip() or None
        for valor in (desde, hasta):
            if valor and len(valor) != 10:
                messagebox.showerror("Fecha inválida",
                                     "Formato esperado: dd/mm/yyyy")
                return "INVAL", None
        return desde, hasta

    # ------------------------- acciones -------------------------------
    def ejecutar_todo(self) -> None:
        desde, hasta = self._validar_fechas()
        if desde == "INVAL":
            return
        orch = self._nuevo_orchestrator()
        self._en_hilo(orch.run, desde, hasta)

    def solo_procesar(self) -> None:
        orch = self._nuevo_orchestrator()
        self._en_hilo(orch.run, None, None, False, True, False)

    def solo_subir(self) -> None:
        orch = self._nuevo_orchestrator()
        self._en_hilo(orch.run, None, None, False, False, True)

    def reprocesar_errores(self) -> None:
        orch = self._nuevo_orchestrator()
        self._en_hilo(orch.reprocesar_errores)

    def generar_reporte(self) -> None:
        orch = self._nuevo_orchestrator()
        self._en_hilo(orch.generar_reporte)


def main() -> None:
    root = tk.Tk()
    App(root)
    root.mainloop()
