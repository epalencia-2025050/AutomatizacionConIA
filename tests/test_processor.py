"""Pruebas del procesador completo: XML -> BD -> archivos (Fase 2)."""
import shutil
from pathlib import Path

import pytest
import yaml

from tests.fixtures_fel import UUID_ESPERADO, XML_FEL_CERTIFICADO, make_xml, NIT

from src.processing.processor import InvoiceProcessor
from src.database.repository import Repository
from src.database.connection import DatabaseConnection


def _tmp_app(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Estructura temporales data/downloads | processed | errors."""
    cfg_base = tmp_path / "app"
    (cfg_base / "downloads").mkdir(parents=True)
    (cfg_base / "processed").mkdir(parents=True)
    (cfg_base / "errors").mkdir(parents=True)
    return cfg_base / "downloads", cfg_base / "processed", cfg_base / "errors"


def _app(tmp_path: Path, settings: dict) -> tuple:
    settings["sat"]["dirs"] = {"downloads": str(tmp_path / "app" / "downloads"),
                               "processed": str(tmp_path / "app" / "processed"),
                               "errors": str(tmp_path / "app" / "errors")}
    hmm_path = tmp_path / "data" / "test.db"
    files = FakeFileManager(settings, tmp_path)
    repo = Repository(hmm_path)
    return files, repo


class FakeFileManager:
    """Sustitución mínima de FileManager apuntando a tmp_path."""

    def __init__(self, settings, tmp_path):
        d = Path(settings["sat"]["dirs"]["downloads"])
        self.downloads_dir = d
        self.processed_dir = d.parent / "processed"
        self.errors_dir = d.parent / "errors"

    def list_files(self, extensiones=(".xml", ".pdf")):
        return sorted(f for f in self.downloads_dir.iterdir()
                      if f.is_file() and f.suffix.lower() in extensiones)

    def move_to_processed(self, file):
        return _mover(file, self.processed_dir)

    def move_to_errors(self, file):
        return _mover(file, self.errors_dir)


def _mover(source: Path, target_dir: Path) -> Path:
    destino = target_dir / source.name
    shutil.move(str(source), str(destino))
    return destino


@pytest.fixture(name="app")
def _app_fixture(tmp_path):
    downloads, processed, errors = _tmp_app(tmp_path)
    settings = {"processing": {"validar_nit": True}}
    # file_manager de verdad usando dirs absolutos (sin depender de cwd)
    fm = FakeFileManager({"sat": {"dirs": {"downloads": str(downloads)}}}, tmp_path)
    repo = Repository(tmp_path / "data" / "test.db")
    processor = InvoiceProcessor(settings, fm, repo)
    return {"downloads": downloads, "processed": processed, "errors": errors,
            "processor": processor, "repo": repo}


def test_procesa_xml_valido(app):
    make_xml(app["downloads"], XML_FEL_CERTIFICADO)
    conteo = app["processor"].procesar_descargas()
    assert conteo == {"validos": 1, "duplicados": 0, "errores": 0}
    row = app["repo"].fila_por_uuid(UUID_ESPERADO)
    assert row and row["estado"] == "VALIDADA"
    assert row["nit_emisor"] == NIT
    assert (app["processed"] / "test.xml").exists()


def test_duplicado_no_vuelve_a_insertar(app):
    make_xml(app["downloads"], XML_FEL_CERTIFICADO)
    app["processor"].procesar_descargas()
    # Re-copiamos el MISMO DTE (viene de nuevo del SAT re-ejecutado)
    make_xml(app["downloads"], XML_FEL_CERTIFICADO, nombre="test_2.xml")
    conteo = app["processor"].procesar_descargas()
    assert conteo["duplicados"] == 1
    total = app["repo"].conn.execute(
        "SELECT COUNT(*) AS n FROM facturas").fetchone()
    assert int(total["n"]) == 1


def test_xml_sin_uuid_va_a_errores(app):
    from tests.fixtures_fel import XML_SIN_UUID
    make_xml(app["downloads"], XML_SIN_UUID)
    conteo = app["processor"].procesar_descargas()
    assert conteo["errores"] == 1
    assert list(app["errors"].iterdir())


def test_nit_invalido_va_a_errores(app):
    from tests.fixtures_fel import XML_FEL_CERTIFICADO as XMLv
    make_xml(app["downloads"],
             XMLv.replace('NITEmisor="56407734"', 'NITEmisor="56407735"'))
    conteo = app["processor"].procesar_descargas()
    assert conteo["errores"] == 1
