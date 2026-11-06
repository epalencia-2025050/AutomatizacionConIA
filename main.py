"""Fases 1 y 2: consulta/descarga y procesamiento de DTE SAT Guatemala.

Uso:
  python main.py                                  # descargar + procesar últimos 7 días
  python main.py --date-from 01/10/2026 --date-to 15/10/2026
  python main.py --dry-run                        # listado sin descargar
  python main.py --solo-procesar                  # procesar XML ya descargados
"""
import argparse
import sys

from src.orchestrator import Orchestrator


def parse_args(argv):
    p = argparse.ArgumentParser(
        description="DTE recibidos de SAT Guatemala: descarga (Fase 1) y "
                    "procesamiento/BD (Fase 2)")
    p.add_argument("--date-from", help="Fecha inicial dd/mm/yyyy")
    p.add_argument("--date-to", help="Fecha final dd/mm/yyyy")
    p.add_argument("--dry-run", action="store_true",
                   help="Sólo listado del SAT, sin descargas ni procesamiento")
    p.add_argument("--solo-procesar", action="store_true",
                   help="Procesa XML de data/downloads sin conectar al SAT")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    orchestrator = Orchestrator()
    try:
        estado = orchestrator.run(date_from=args.date_from, date_to=args.date_to,
                                  dry_run=args.dry_run,
                                  solo_procesar=args.solo_procesar)
        print("\nRESUMEN: descargados=%s | validos=%s | duplicados=%s | errores=%s"
              % (estado.get("descargas", 0), estado.get("validos", 0),
                 estado.get("duplicados", 0), estado.get("errores", 0)))
        return 0
    except KeyboardInterrupt:
        print("\nEjecución interrumpida por el usuario")
        return 130
    except Exception:
        import logging
        logging.getLogger(__name__).exception("Fallo no controlado")
        return 1


if __name__ == "__main__":
    sys.exit(main())
