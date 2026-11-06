"""Pruebas del validador (NIT módulo 11, DTE) - Fase 2."""
from tests.fixtures_fel import NIT, UUID_ESPERADO, make_xml, XML_FEL_CERTIFICADO

from src.processing.validator import Validator
from src.processing.xml_reader import XmlReader


def test_nit_checksum_validez():
    v = Validator()
    # NIT real verificado del registro de certificadores SAT: 5640773-4
    assert v.validar_nit(NIT) is True

    assert v.validar_nit("98978802") is True     # Corposistemas certificador
    assert v.validar_nit(NIT[:-1] + "5") is False    # dígito errado
    assert v.validar_nit("") is False
    assert v.validar_nit("1234K2") is False      # demasiado corto, formato raro


def test_nit_legado_con_letras_no_valida():
    # NIT antiguos con letras no validables por checksum
    assert Validator().validar_nit("FINANZ4-X") is False


def test_validacion_dte_completo(tmp_path):
    data = XmlReader().parse(make_xml(tmp_path, XML_FEL_CERTIFICADO))
    problemas = Validator().validate(data)
    assert problemas == []


def test_validacion_pdf_ausente(tmp_path):
    data = XmlReader().parse(make_xml(tmp_path, XML_FEL_CERTIFICADO))
    pdf_inexistente = tmp_path / "noexiste.pdf"
    problemas = Validator().validate(data, pdf_correspondente=pdf_inexistente)
    assert any("PDF correspondiente ausente" in p for p in problemas)
