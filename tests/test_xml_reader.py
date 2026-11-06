"""Pruebas del lector de XML FEL (Fase 2)."""
from tests.fixtures_fel import (XML_FEL_CERTIFICADO, XML_FEL_CON_UUID_GUIONES,
                                XML_MALFORMADO, XML_NO_FEL, XML_SIN_UUID,
                                UUID_ESPERADO, make_xml, NIT)

from src.processing.xml_reader import XmlReader
from src.processing.models import FacturaDTE


def test_extrae_campos_clave(tmp_path):
    data = XmlReader().parse(make_xml(tmp_path, XML_FEL_CERTIFICADO))
    assert isinstance(data, FacturaDTE)
    # UUID de 32 hex en el XML -> normalizado a la forma con guiones
    assert data.uuid == UUID_ESPERADO
    assert data.nit_emisor == NIT
    assert data.tipo_documento == "FACT"
    assert data.total == 2000.0
    assert data.iva == 214.29
    assert data.num_items == 1
    assert data.moneda == "GTQ"
    assert data.fecha_emision.startswith("2026-03-15")
    assert data.fecha_certificacion.startswith("2026-03-15")


def test_normaliza_uuid_con_guiones(tmp_path):
    data = XmlReader().parse(make_xml(tmp_path, XML_FEL_CON_UUID_GUIONES))
    # mismo UUID con guiones -> mismo valor normalizado
    assert data.uuid == UUID_ESPERADO


def test_xml_sin_uuid_reporta_error(tmp_path):
    data = XmlReader().parse(make_xml(tmp_path, XML_SIN_UUID))
    assert isinstance(data, dict) and "error" in data


def test_xml_malformado(tmp_path):
    data = XmlReader().parse(make_xml(tmp_path, XML_MALFORMADO))
    assert isinstance(data, dict) and "error" in data


def test_xml_no_fel(tmp_path):
    data = XmlReader().parse(make_xml(tmp_path, XML_NO_FEL))
    assert isinstance(data, dict) and "GTDocumento" in data["error"]
