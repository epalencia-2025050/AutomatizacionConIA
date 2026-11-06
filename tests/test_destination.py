"""Pruebas de la Fase 3: máquina de estados del destino.

Regla clave del diseño (§8): NO marcar SUBIDA sin confirmación
verificable. Esto se valida con un módulo simulado (no se toca red).
"""
import pytest

from src.destination.module import (DestinationModule, ResultadoEnvio,
                                    NoConfiguradoError)
from src.destination.uploader import DestinationUploader
from src.destination.authentication import DestinationAuthentication
from src.database.repository import Repository
from src.processing.xml_reader import XmlReader

from tests.fixtures_fel import XML_FEL_CERTIFICADO, make_xml


class FakeModule(DestinationModule):
    """Destino simulado configurable por escenario."""

    def __init__(self, escenario="ok", verificado=True):
        self.escenario = escenario
        self.verificador = verificado
        self.configurado = escenario != "no_configurado"
        self.envs: list[str] = []

    def login(self):
        assert self.configurado, "No debe invocarse login sin configuración"

    def enviar(self, factura, xml_path=None, pdf_path=None):
        self.envs.append(factura.get("uuid"))
        if self.escenario == "ok":
            return (ResultadoEnvio.SUBIDA if self.verificador
                    else ResultadoEnvio.SIN_CONFIRMACION)
        if self.escenario == "timeout":
            return ResultadoEnvio.SIN_CONFIRMACION
        return ResultadoEnvio.ERROR

    def verificar(self, uuid):
        return bool(self.verificador and uuid)


@pytest.fixture(name="repo_tmp")
def _repo(tmp_path):
    return Repository(tmp_path / "t.db")


def _insertar_validada(repo: Repository):
    """Inserta en la BD una factura VALIDADA (desde XML real de fixture)."""
    import tempfile
    from pathlib import Path
    tmp = Path(tempfile.mkdtemp())
    data = XmlReader().parse(make_xml(tmp, XML_FEL_CERTIFICADO))
    repo.insertar(data, estado="VALIDADA")
    return data


def test_no_configurado_no_envia(repo_tmp):
    data = _insertar_validada(repo_tmp)
    modulo = FakeModule(escenario="no_configurado")
    res = DestinationUploader(repo_tmp, modulo).run()
    assert not modulo.envs, "no debe invocar enviar() sin configuración"
    assert repo_tmp.estado_actual(data.uuid) == "VALIDADA"


def test_exito_verificado_marca_SUBIDA(repo_tmp):
    data = _insertar_validada(repo_tmp)
    modulo = FakeModule(escenario="ok", verificado=True)
    res = DestinationUploader(repo_tmp, modulo, max_intentos=1).run()
    assert res["enviadas"] == 1
    assert repo_tmp.estado_actual(data.uuid) == "SUBIDA"
    fila = repo_tmp.fila_por_uuid(data.uuid)
    assert fila["fecha_carga"], "debe registrar fecha_carga"


def test_sin_confirmacion_NO_marca_SUBIDA(repo_tmp):
    data = _insertar_validada(repo_tmp)
    modulo = FakeModule(escenario="timeout", verificado=False)
    res = DestinationUploader(repo_tmp, modulo, max_intentos=1).run()
    assert res["sin_confirmacion"] == 1
    assert repo_tmp.estado_actual(data.uuid) != "SUBIDA", \
        "regla §8: sin confirmación verificable no puede ser SUBIDA"


def test_error_incrementa_intentos(repo_tmp):
    data = _insertar_validada(repo_tmp)
    modulo = FakeModule(escenario="error")
    DestinationUploader(repo_tmp, modulo, max_intentos=2).run()
    fila = repo_tmp.fila_por_uuid(data.uuid)
    assert fila["estado"] == "ERROR"
    assert int(fila["intentos"]) == 1
    DestinationUploader(repo_tmp, modulo, max_intentos=2).run()
    fila = repo_tmp.fila_por_uuid(data.uuid)
    assert int(fila["intentos"]) == 2


def test_max_intentos_omite(repo_tmp):
    data = _insertar_validada(repo_tmp)
    modulo = FakeModule(escenario="error")
    DestinationUploader(repo_tmp, modulo, max_intentos=1).run()
    res2 = DestinationUploader(repo_tmp, modulo, max_intentos=1).run()
    assert res2["omitidas_max_intentos"] == 1


def test_auth_sin_config_lanza_error():
    auth = DestinationAuthentication({}, {})
    assert auth.configurado() is False
    with pytest.raises(NoConfiguradoError):
        auth.login()
