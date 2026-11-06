"""Conexión y esquema de la base de datos SQLite (Fase 2).

Esquema del diseño (§7): id, uuid, nit_emisor, nombre_emisor,
fecha_emision, numero_documento, total, xml_path, pdf_path, estado,
fecha_carga + máquina de estados y trazabilidad de errores.
"""
import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

ESTADOS = ("DESCARGADA", "VALIDADA", "PENDIENTE_SUBIDA", "SUBIDA", "ERROR")

SCHEMA = """
CREATE TABLE IF NOT EXISTS facturas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid TEXT UNIQUE,
    nit_emisor TEXT NOT NULL,
    nombre_emisor TEXT,
    fecha_emision TEXT,
    fecha_certificacion TEXT,
    numero_documento TEXT,
    serie TEXT,
    tipo_documento TEXT,
    total REAL,
    moneda TEXT DEFAULT 'GTQ',
    xml_path TEXT,
    pdf_path TEXT,
    estado TEXT NOT NULL DEFAULT 'DESCARGADA',
    intentos INTEGER DEFAULT 0,
    mensaje_error TEXT,
    fecha_carga TEXT,
    fecha_procesado TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_facturas_estado ON facturas(estado);
CREATE INDEX IF NOT EXISTS idx_facturas_nit ON facturas(nit_emisor);
"""


class DatabaseConnection:
    """Administra la conexión SQLite única del proceso."""

    def __init__(self, database_path: Path):
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None

    def connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.database_path),
                                         isolation_level=None)   # autocommit
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            legacy = self._DetectaLegacy()
            if legacy:
                self._archiva_legacy()
            # ejecutar SCHEMA (multi-statements)
            for stmt in filter(None, (s.strip() for s in SCHEMA.split(";"))):
                self._conn.execute(stmt)
            logger.info("BD lista en %s", self.database_path)
        return self._conn

    # ------------------------------------------------------------------
    def _DetectaLegacy(self) -> bool:
        """True si una factura tiene el esquema viejo (sin columna estado)."""
        row = self._conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='facturas'"
        ).fetchone()
        return bool(row and "estado" not in (row["sql"] or ""))

    def _archiva_legacy(self) -> None:
        """Esquema anterior ( Craig mexicano de Fase previa): rename y no tocar."""
        try:
            self._conn.execute("ALTER TABLE facturas RENAME TO facturas_legacy_v0")
            logger.warning("Tabla antigua archivada como facturas_legacy_v0")
        except sqlite3.Error as exc:
            logger.error("No se pudo archivar el esquema viejo: %s", exc)

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            finally:
                self._conn = None

    def __enter__(self):
        return self.connect()

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
