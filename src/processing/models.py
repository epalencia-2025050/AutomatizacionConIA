"""Modelo de datos de un DTE (FEL Guatemala) y sus estados (Fase 2).

Estados del diseño del proyecto:
  DESCARGADA | VALIDADA | PENDIENTE_SUBIDA | SUBIDA | ERROR
"""
from datetime import date

from pydantic import BaseModel, Field, field_validator

UUID_RE = (r"^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-"
           r"[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$")

ESTADOS = ("DESCARGADA", "VALIDADA", "PENDIENTE_SUBIDA", "SUBIDA", "ERROR")

TIPOS_DTE = {"FACT", "FCAM", "FESP", "NCRE", "NDEB", "NABN", "RDON", "RECI",
             "FAAU", "FCAP", "FPEQ"}

class FacturaDTE(BaseModel):
    """DTE certificado por un certificador FEL (Infile, Digifact, ...).

    UUID = número de autorización SAT: 32 hexadecimales, normalmente sin
    guiones en el XML (se normaliza a la forma textual con guiones).
    """

    xml_path: str
    pdf_path: str | None = None

    uuid: str = Field(description="Número de autorización SAT (UUID)")
    tipo_documento: str = Field(default="", description="FACT, FCAM, FESP, NCRE...")
    serie: str = ""
    numero_documento: str = ""
    fecha_emision: str = Field(default="", description="ISO del XML")
    fecha_certificacion: str = ""
    moneda: str = "GTQ"

    nit_emisor: str = Field(description="NIT emisor, sin guión")
    nombre_emisor: str = ""
    nit_receptor: str = ""
    nombre_receptor: str = ""

    total: float = 0.0
    iva: float = 0.0
    num_items: int = 0

    # ------------------------------------------------------------------
    @field_validator("uuid")
    @classmethod
    def uuid_valido(cls, v: str) -> str:
        import re
        hexa = re.sub(r"[-\s]", "", v or "").upper()
        if len(hexa) == 32 and re.fullmatch(r"[0-9A-F]{32}", hexa):
            return ("{}-{}-{}-{}-{}").format(
                hexa[:8], hexa[8:12], hexa[12:16], hexa[16:20], hexa[20:32])
        raise ValueError(f"UUID no es 32 hexadecimales: {v!r}")

    @field_validator("nit_emisor")
    @classmethod
    def nit_presente(cls, v: str) -> str:
        if not (v or "").strip():
            raise ValueError("NIT del emisor vacío")
        return v.strip()

    @field_validator("fecha_emision")
    @classmethod
    def fecha_parseable(cls, v: str) -> str:
        if (v or "").strip():
            date.fromisoformat(v[:10])   # valida 'yyyy-MM-dd...'
        return v

    def fecha_corta(self) -> str:
        return (self.fecha_emision or "")[:10]
