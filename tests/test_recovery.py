"""Pruebas de recuperación de errores (Fase 4).

reprocesar_errores() mueve data/errors/* de vuelta a data/downloads y
lanza el reprocesamiento. Se prueba con dirs temporales para no tocar
data/ real del proyecto.
"""
import pytest

from src.orchestrator import Orchestrator
from src.database.repository import Repository
from src.processing.xml_reader import XmlReader

from tests.fixtures_fel import XML_FEL_CERTIFICADO, make_xml


@pytest.fixture(name="orch_tmp")
def _orch(tmp_path, monkeypatch):
    """Orchestrator sin su __init__: dirs y repo apuntan a tmp_path."""
    orch = Orchestrator.__new__(Orchestrator)

    class Files:
        def __init__(self, base):
            self.errors_dir = base / "errors"
            self.downloads_dir = base / "downloads"
            self.errors_dir.mkdir()
            self.downloads_dir.mkdir()

    orch.files = Files(tmp_path)
    ruta_bd = str(tmp_path / "bd.db")
    orch.settings = {"sat": {"dirs": {}}, "database": {"ruta": ruta_bd}}
    orch.selectors = {}

    llamadas = {"procesos": 0}

    def _fase_procesamiento():
        llamadas["procesos"] += 1
        return {"validos": 0}

    monkeypatch.setattr(orch, "_fase_procesamiento", _fase_procesamiento)
    orch._llamadas = llamadas
    return orch


def test_sin_errores_no_reprocesa(orch_tmp):
    assert orch_tmp.reprocesar_errores() == 0
    assert orch_tmp._llamadas["procesos"] == 0, "sin archivos no re-lanza pipeline"


def test_mueve_archivos_a_downloads_y_reprocesa(orch_tmp):
    err_dir = orch_tmp.files.errors_dir
    (err_dir / "a.xml").write_text("<x/>", encoding="utf-8")
    (err_dir / "b.pdf").write_bytes(b"%PDF-1.4")
    (err_dir / "otro.txt").write_text("x", encoding="utf-8")

    movidos = orch_tmp.reprocesar_errores()

    assert movidos == 3, "mueve todo archivo suelto de errors"
    assert not list(err_dir.iterdir())
    names = {f.name for f in orch_tmp.files.downloads_dir.iterdir()}
    assert {"a.xml", "b.pdf", "otro.txt"} == names
    assert orch_tmp._llamadas["procesos"] == 1, "re-lanza procesamiento"


def test_reprocesamiento_recupera_xml_valido(orch_tmp):
    """E2E local: un XML que falló (p.ej. red) se recupera y queda VALIDADA."""
    # make_xml deja varios archivos; se aísla sólo uno en errors/
    generados = make_xml(orch_tmp.files.downloads_dir, XML_FEL_CERTIFICADO)
    contenido = generados.read_text(encoding="utf-8")
    for f in orch_tmp.files.downloads_dir.iterdir():
        f.unlink()
    xml_path = orch_tmp.files.errors_dir / "fel.xml"
    xml_path.write_text(contenido, encoding="utf-8")

    movidos = orch_tmp.reprocesar_errores()
    assert movidos == 1
    # ahora copiamos el XML a una BD y confirmamos estado
    repo = Repository(orch_tmp.db_path)
    data = XmlReader().parse(orch_tmp.files.downloads_dir / "fel.xml")
    repo.insertar(data, estado="VALIDADA")
    assert repo.estado_actual(data.uuid) == "VALIDADA"
    assert repo.estado_actual(data.uuid) != "ERROR"
