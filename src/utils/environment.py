"""Carga variables locales de entorno para la aplicación."""
from pathlib import Path

from dotenv import load_dotenv


def load_environment(root_dir: Path | None = None) -> None:
    """Carga primero .env de la raíz y luego src/.env como alternativa."""
    root = root_dir or Path(__file__).resolve().parents[2]
    load_dotenv(root / ".env")
    load_dotenv(root / "src" / ".env")
