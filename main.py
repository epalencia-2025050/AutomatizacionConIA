"""Punto de entrada de la automatización de facturas SAT -> Sistema destino."""
import argparse
import logging
import sys
from pathlib import Path

from src.orchestrator import Orchestrator
from src.utils.logger import setup_logger

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Descarga facturas del SAT y las registra en el sistema destino."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Ejecuta el flujo sin subir nada al sistema destino.",
    )
    parser.add_argument(
        "--date-from",
        type=str,
        default=None,
        help="Fecha de inicio del rango de búsqueda (dd/mm/yyyy).",
    )
    parser.add_argument(
        "--date-to",
        type=str,
        default=None,
        help="Fecha de fin del rango de búsqueda (dd/mm/yyyy).",
    )
    parser.add_argument(
        "--rfc",
        type=str,
        default=None,
        help="RFC emisor para filtrar la búsqueda",
    )
    return parser.parse_args()


def main() -> int:
    setup_logger()
    args = parse_args()

    try:
        orchestrator = Orchestrator(dry_run=args.dry_run)
        orchestrator.run(
            date_from=args.date_from,
            date_to=args.date_to,
            issuer_rfc=args.rfc,
        )
        return 0
    except Exception:
        logger.exception("Fallo inesperado en la ejecución")
        return 1


if __name__ == "__main__":
    sys.exit(main())
