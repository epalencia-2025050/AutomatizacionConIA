"""Reportes de ejecución (Fase 4).

Genera un CSV por corrida en data/reports con:
 - línea EJECUCION: fecha, fechas consultadas, conteos del flujo
 - líneas ESTADO_BD: resumen de la máquina de estados
 - líneas DETALLE: una por factura con su estado y errores
"""
import csv
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).resolve().parents[2]

ENCABEZADOS = ["tipo", "uuid", "nit_emisor", "nombre_emisor", "total",
               "estado", "mensaje", "ruta_xml", "ruta_pdf", "fecha_carga"]


class Reporter:
    def __init__(self, directorio: Path | None = None):
        self.dir = Path(directorio or (ROOT_DIR / "data" / "reports"))
        self.dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    def reporte_ejecucion(self, fechas: str, estado_flujo: dict,
                          repo=None) -> Path:
        """Construye el CSV del ciclo y devuelve su ruta."""
        ahora = datetime.now()
        path = self.dir / f"reporte_{ahora:%Y%m%d_%H%M}.csv"

        with open(path, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow(ENCABEZADOS)

            resumen_flujo = "; ".join(f"{k}={v}" for k, v in estado_flujo.items())
            w.writerow(["EJECUCION", ahora.isoformat(timespec="seconds"),
                        "", "", "", "", f"rango={fechas} | {resumen_flujo}",
                        "", "", ""])

            if repo is None:
                logger.info("Reporte sin BD: sólo resumen de flujo")
                return path

            for estado, n in (repo.resumen() or {}).items():
                w.writerow(["ESTADO_BD", "", "", "", "", estado,
                            f"conteo={n}", "", "", ""])

            for fila in repo.conn.execute(
                    "SELECT * FROM facturas ORDER BY id").fetchall():
                w.writerow(["DETALLE", fila["uuid"], fila["nit_emisor"],
                            fila["nombre_emisor"], fila["total"],
                            fila["estado"], fila["mensaje_error"] or "",
                            fila["xml_path"] or "", fila["pdf_path"] or "",
                            fila["fecha_carga"] or ""])

        logger.info("Reporte generado: %s", path.name)
        return path

    def ultimo_reporte(self) -> Path | None:
        if not self.dir.exists():
            return None
        reportes = sorted(self.dir.glob("reporte_*.csv"))
        return reportes[-1] if reportes else None
