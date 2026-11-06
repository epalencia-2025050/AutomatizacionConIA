"""Tests del módulo de procesamiento XML."""
from pathlib import Path

from src.processing.xml_reader import XmlReader
from src.processing.validator import Validator

SAMPLE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
    Version="4.0" Serie="A" Folio="123" Fecha="2024-01-15T10:00:00"
    SubTotal="100.00" Moneda="MXN" Total="116.00">
  <cfdi:Emisor Rfc="ABC010101AAA" Nombre="Empresa Emisora"/>
  <cfdi:Receptor Rfc="XYZ" Nombre="Cliente"/>
  <cfdi:Complemento>
    <tfd:TimbreFiscalDigital xmlns:tfd="http://www.sat.gob.mx/TimbreFiscalDigital"
        UUID="a1b2c3d4-e5f6-4789-a012-b3c4d5e6f7a8"/>
  </cfdi:Complemento>
</cfdi:Comprobante>
"""


def make_sample(tmp_path: Path) -> Path:
    xml_file = tmp_path / "sample_test.xml"
    xml_file.write_text(SAMPLE_XML, encoding="utf-8")
    return xml_file


def test_extract_fields(tmp_path):
    reader = XmlReader()
    data = reader.extract(make_sample(tmp_path))
    assert data is not None
    assert data["serie"] == "A"
    assert data["folio"] == "123"
    assert data["rfc_emisor"] == "ABC010101AAA"
    assert data["uuid"] == "a1b2c3d4-e5f6-4789-a012-b3c4d5e6f7a8"
    assert data["total"] == 116.0


def test_validate_ok(tmp_path):
    reader = XmlReader()
    validator = Validator({"validate_rfc": True})
    data = reader.extract(make_sample(tmp_path))
    assert validator.validate(data) is True


def test_validate_invalid_total():
    validator = Validator({"validate_rfc": False})
    assert validator.validate({"uuid": "a1b2c3d4-e5f6-4789-a012-b3c4d5e6f7a8",
                              "rfc_emisor": "ABC010101AAA",
                              "total": 0.0, "fecha_emision": "x"}) is False
