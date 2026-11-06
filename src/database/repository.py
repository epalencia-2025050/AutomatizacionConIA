"""Operaciones CRUD sobre la tabla `facturas`."""
import logging
from datetime import date

from src.database.connection import DatabaseConnection

logger = logging.getLogger(__name__)

ROOT_DIR = __import__("pathlib").Path(__file__).resolve().parents[2]


class Repository:
    """Capa de acceso a datos para el histórico de facturas procesadas."""

    def __init__(self, database_path=None):
        from pathlib import Path
        path = Path(database_path or (ROOT_DIR / "data" / "automatizacion.db"))
        self.conn = DatabaseConnection(path).connect()

    # ------------------------------------------------------------------
    def save_invoice(self, data: dict) -> int | None:
        """Inserta o actualiza la factura según el UUID. Devuelve id o None."""
        try:
            cursor = self.conn.execute(
                """
                INSERT INTO facturas
                    (uuid, rfc_emisor, rfc_receptor, serie, folio,
                     fecha_emision, total, archivo_xml)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(uuid) DO UPDATE SET
                    total = excluded.total,
                    archivo_xml = excluded.archivo_xml
                """,
                (
                    data.get("uuid"),
                    data.get("rfc_emisor"),
                    data.get("rfc_receptor"),
                    data.get("serie"),
                    data.get("folio"),
                    data.get("fecha_emision"),
                    data.get("total"),
                    data.get("archivo_xml"),
                ),
            )
            self.conn.commit()
            return cursor.lastrowid
        except Exception as exc:
            logger.error("No se pudo guardar la factura %s: %s", data.get("uuid"), exc)
            return None

    def was_uploaded(self, uuid: str) -> bool:
        row = self.conn.execute(
            "SELECT subido FROM facturas WHERE uuid = ?", (uuid,)
        ).fetchone()
        return bool(row and row["subido"])

    def mark_uploaded(self, uuid: str, success: bool = True) -> None:
        if not success:
            logger.info("UUID=%s no se marca como subido", uuid)
            return
        self.conn.execute(
            "UPDATE facturas SET subido = 1, fecha_subida = ? WHERE uuid = ?",
            (date.today().isoformat(), uuid),
        )
        self.conn.commit()

    def count_pending(self) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM facturas WHERE subido = 0"
        ).fetchone()
        return int(row["n"]) if row else 0

    def close(self) -> None:
        if self.conn:
            self.conn.close()
