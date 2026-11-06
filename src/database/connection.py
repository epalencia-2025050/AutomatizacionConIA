"""Conexión a la base de datos (SQLite por defecto)."""
import logging
import sqlite3
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS facturas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid TEXT UNIQUE NOT NULL,
    rfc_emisor TEXT,
    rfc_receptor TEXT,
    serie TEXT,
    folio TEXT,
    fecha_emision TEXT,
    subtotal REAL,
    total REAL,
    archivo_xml TEXT,
    archivo_pdf TEXT,
    subido INTEGER DEFAULT 0,
    fecha_subida TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


class DatabaseConnection:
    """Administra la conexión SQLite; simple y sin dependencias externas."""

    def __init__(self, database_path: Path):
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None

    def connect(self) -> sqlite3.Connection:
        if self._conn is None or self._conn.closed:
            self._conn = sqlite3.connect(str(self.database_path))
            self._conn.row_factory = sqlite3.Row
            self._conn.executescript(SCHEMA)
            self._conn.commit()
            logger.debug("BD lista en %s", self.database_path)
        return self._conn

    def close(self) -> None:
        if self._conn and not self._conn.closed:
            self._conn.close()
            logger.debug("Conexión BD cerrada")

    def __enter__(self):
        return self.connect()

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
