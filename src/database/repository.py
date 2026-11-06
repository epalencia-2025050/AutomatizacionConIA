"""Capa de acceso a datos: facturas, estados y duplicados (Fase 2)."""
import logging
import sqlite3
from datetime import datetime

from src.database.connection import DatabaseConnection

logger = logging.getLogger(__name__)


class Repository:
    """Operaciones CRUD con la máquina de estados del diseño."""

    def __init__(self, db_path):
        self.conn = DatabaseConnection(db_path).connect()

    # ------------------------------------------------------------------
    def existe_uuid(self, uuid: str) -> bool:
        """True si el UUID ya está registrado (detección de duplicados)."""
        row = self.conn.execute(
            "SELECT 1 FROM facturas WHERE uuid = ?", (uuid,)).fetchone()
        return row is not None

    def fila_por_uuid(self, uuid: str) -> dict:
        row = self.conn.execute(
            "SELECT * FROM facturas WHERE uuid = ?", (uuid,)).fetchone()
        return dict(row) if row else {}

    def estado_actual(self, uuid: str) -> str | None:
        fila = self.fila_por_uuid(uuid)
        return fila.get("estado")

    # ------------------------------------------------------------------
    def insertar(self, data, estado: str = "VALIDADA",
                 pdf_path: str | None = None) -> int:
        """Inserta la factura; si el UUID ya existe devuelve su id (sin duplicar)."""
        existente = self.conn.execute(
            "SELECT id FROM facturas WHERE uuid = ?", (data.uuid,)).fetchone()
        if existente:
            return int(existente["id"])
        cursor = self.conn.execute(
            """
            INSERT INTO facturas
                (uuid, nit_emisor, nombre_emisor, fecha_emision,
                 fecha_certificacion, numero_documento, serie, tipo_documento,
                 total, moneda, xml_path, pdf_path, estado)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (data.uuid, data.nit_emisor, data.nombre_emisor, data.fecha_emision,
             data.fecha_certificacion, data.numero_documento, data.serie,
             data.tipo_documento, data.total, data.moneda,
             data.xml_path, pdf_path, estado))
        return int(cursor.lastrowid)

    # ------------------------------------------------------------------
    def marcar_estado(self, uuid: str, estado: str,
                      mensaje_error: str | None = None) -> None:
        """Transición de estado; los errores incrementan intentos y mensaje."""
        fecha = datetime.now().isoformat(timespec="seconds")
        if estado == "SUBIDA":
            self.conn.execute(
                "UPDATE facturas SET estado=?, fecha_carga=? WHERE uuid=?",
                (estado, fecha, uuid))
        elif estado == "ERROR":
            self.conn.execute(
                """
                UPDATE facturas
                   SET estado='ERROR',
                       mensaje_error=COALESCE(?, mensaje_error),
                       intentos=intentos+1
                 WHERE uuid=?
                """,
                (mensaje_error, uuid))
        else:
            self.conn.execute(
                "UPDATE facturas SET estado=? WHERE uuid=?", (estado, uuid))

    def actualizar_rutas(self, uuid: str, xml_path: str | None = None,
                         pdf_path: str | None = None) -> None:
        """Guarda rutas finales de los XML y PDF en disco."""
        sets, vals = [], []
        if xml_path:
            sets.append("xml_path=?"); vals.append(xml_path)
        if pdf_path:
            sets.append("pdf_path=?"); vals.append(pdf_path)
        if not sets:
            return
        vals.append(uuid)
        self.conn.execute(f"UPDATE facturas SET {', '.join(sets)} WHERE uuid=?", vals)

    # ------------------------------------------------------------------
    def listar_por_estado(self, estados: tuple[str, ...]) -> list[dict]:
        marks = ", ".join("?" * len(estados))
        return [dict(r) for r in self.conn.execute(
            f"SELECT * FROM facturas WHERE estado IN ({marks}) ORDER BY id",
            estados).fetchall()]

    def errores(self) -> list[dict]:
        return self.listar_por_estado(("ERROR",))

    def contar_pendientes_subida(self) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM facturas WHERE estado IN "
            "('VALIDADA','PENDIENTE_SUBIDA')").fetchone()
        return int(row["n"])

    def resumen(self) -> dict[str:int]:
        rows = self.conn.execute(
            "SELECT estado, COUNT(*) AS n FROM facturas GROUP BY estado").fetchall()
        return {r["estado"]: int(r["n"]) for r in rows}

    def close(self) -> None:
        self.conn.close()
