"""Backup diario automático de la BD (Fase 6).

Cada corrida garantiza que exista una copia del día en data/backups/
(una por calendario: si ya existe la del día, no se duplica).
Las copias viejas se recortan según retención (por defecto 30 días).
Nunca borra la BD real: sólo copia.
"""
import logging
import shutil
from datetime import date
from pathlib import Path

logger = logging.getLogger(__name__)


class BackupManager:
    def __init__(self, db_path: Path, directorio: Path | None = None,
                 retencion: int = 30):
        self.db_path = Path(db_path)
        self.dir = Path(directorio or (self.db_path.parent / "backups"))
        self.retencion = max(retencion, 1)

    def backup_diario(self) -> Path | None:
        """Copia la BD (si hoy aún no existe copia). Devuelve la ruta."""
        if not self.db_path.exists():
            logger.warning("Backup omitido: la BD %s no existe", self.db_path)
            return None
        self.dir.mkdir(parents=True, exist_ok=True)
        destino = self.dir / f"automatizacion_{date.today():%Y%m%d}.db"
        if destino.exists():
            logger.info("Backup de hoy ya existe: %s", destino.name)
            return destino
        shutil.copy2(self.db_path, destino)
        logger.info("Backup BD creado: %s (%s KB)", destino.name,
                    destino.stat().st_size // 1024)
        self._podar()
        return destino

    def _podar(self) -> None:
        """Deja sólo los últimos `retencion` backups."""
        backups = sorted(self.dir.glob("automatizacion_*.db"))
        for viejo in backups[:-self.retencion]:
            viejo.unlink()
            logger.info("Backup antiguo eliminado: %s", viejo.name)

    def lista(self) -> list[Path]:
        return sorted(self.dir.glob("automatizacion_*.db")) if \
            self.dir.exists() else []
