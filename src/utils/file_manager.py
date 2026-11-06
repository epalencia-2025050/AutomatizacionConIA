"""Gestión y organización de archivos descargados."""
import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)


class FileManager:
    def __init__(self, downloads_dir: Path, processed_dir: Path, errors_dir: Path):
        self.downloads_dir = Path(downloads_dir)
        self.processed_dir = Path(processed_dir)
        self.errors_dir = Path(errors_dir)
        for d in (self.downloads_dir, self.processed_dir, self.errors_dir):
            d.mkdir(parents=True, exist_ok=True)

    def list_files(self, extensions: tuple[str, ...] = (".xml", ".pdf")) -> list[Path]:
        """Los archivos XML primero (prioridad para extracción de datos)."""
        files = [
            f for f in sorted(self.downloads_dir.iterdir())
            if f.is_file() and f.suffix.lower() in extensions
        ]
        files.sort(key=lambda f: f.suffix.lower() != ".xml")
        return files

    def move_to_processed(self, file_path: Path) -> Path:
        return self._move(file_path, self.processed_dir)

    def move_to_errors(self, file_path: Path) -> Path:
        return self._move(file_path, self.errors_dir)

    def _move(self, file_path: Path, target_dir: Path) -> Path:
        target = target_dir / file_path.name
        counter = 1
        while target.exists():
            target = target_dir / f"{file_path.stem}_{counter}{file_path.suffix}"
            counter += 1
        shutil.move(str(file_path), str(target))
        logger.debug("Movido -> %s", target)
        return target

    def organize(self):
        """Ordena lo que quede en downloads: XML va a processed, resto a errors."""
        for f in self.list_files():
            self.move_to_processed(f)

    def find_partner(self, xml_path: Path, extension: str = ".pdf") -> Path | None:
        """Busca el PDF correspondiente al XML (mismo nombre base)."""
        for f in self.downloads_dir.iterdir():
            if f.is_file() and f.stem == xml_path.stem and f.suffix.lower() == extension:
                return f
        return None

    def cleanup_downloads(self):
        for f in self.list_files((".pdf", ".xml")):
            f.unlink(missing_ok=True)
