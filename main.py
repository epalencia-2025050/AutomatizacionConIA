"""Fases 1 y 2: consulta/descarga y procesamiento de DTE SAT Guatemala.

Uso:
  python main.py                                  # descargar + procesar últimos 7 días
  python main.py --date-from 01/10/2026 --date-to 15/10/2026
  python main.py --dry-run                        # listado sin descargar
  python main.py --solo-procesar                  # procesar XML ya descargados
  python main.py --solo-subir                     # sólo enviar pendientes al destino
  python main.py --gui                            # interfaz gráfica (Fase 4)
"""
import argparse
import sys

from src.orchestrator import Orchestrator


def parse_args(argv):
    p = argparse.ArgumentParser(
        description="DTE recibidos de SAT Guatemala: descarga (F1), "
                    "procesamiento (F2) y transferencia al destino (F3)")
    p.add_argument("--date-from", help="Fecha inicial dd/mm/yyyy")
    p.add_argument("--date-to", help="Fecha final dd/mm/yyyy")
    p.add_argument("--dry-run", action="store_true",
                   help="Sólo listado del SAT, sin descargas ni procesamiento")
    p.add_argument("--solo-procesar", action="store_true",
                   help="Procesa XML de data/downloads sin conectar al SAT")
    p.add_argument("--solo-subir", action="store_true",
                   help="Sólo transfiere facturas VALIDADA/PENDIENTE_SUBIDA "
                        "al destino (Fase 3, si está habilitada)")
    p.add_argument("--gui", action="store_true",
                   help="Abre la interfaz gráfica Tkinter (Fase 4)")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.gui:
        from src.gui.app import main as main_gui
        main_gui()
        return 0
    orchestrator = Orchestrator()
    try:
        estado = orchestrator.run(date_from=args.date_from, date_to=args.date_to,
                                  dry_run=args.dry_run,
                                  solo_procesar=args.solo_procesar,
                                  solo_subir=args.solo_subir)
        print("\nRESUMEN: descargados=%s | validos=%s | duplicados=%s | "
              "errores=%s | enviadas=%s | sin_confirmacion=%s"
              % (estado.get("descargas", 0), estado.get("validos", 0),
                 estado.get("duplicados", 0), estado.get("errores", 0),
                 estado.get("enviadas", 0), estado.get("sin_confirmacion", 0)))
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
