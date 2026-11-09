"""Configuración del sistema de logging."""
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_DIR = Path("logs")
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logger(level: str | None = None) -> logging.Logger:
    """Configura logging a consola y archivo rotativo (una sola vez)."""
    root = logging.getLogger()
    if root.handlers:  # ya configurado
        return root

    import os
    level_name = level or os.getenv("LOG_LEVEL", "INFO")
    root.setLevel(getattr(logging, level_name.upper(), logging.INFO))
    formatter = logging.Formatter(LOG_FORMAT, DATE_FORMAT)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    root.addHandler(console)

    LOG_DIR.mkdir(exist_ok=True)
    file_handler = RotatingFileHandler(
        LOG_DIR / "automatizacion.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)
    return root
