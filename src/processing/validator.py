"""Validación de un DTE extraído (Fase 2).

Verifica:
 - estructura completa (UUID, NIT, fecha, total),
 - dígito verificador del NIT de Guatemala (módulo 11, factores 2..9),
 - correspondencia XML <-> PDF en disco.
"""
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

UUID_RE = re.compile(r"^[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}$")

TIPOS_DTE_VALIDOS = {"FACT", "FCAM", "FESP", "NCRE", "NDEB", "NABN", "RDON",
                     "RECI", "FAAU", "FCAP", "FPEQ", "FDON", "CIVA"}


class Validator:
    """Validador de datos fiscales del DTE."""

    def validar_nit(self, nit: str) -> bool:
        """Valida el dígito verificador del NIT (módulo 11, factores 2..9).

        Ejemplos reales verificados: 5640773-4 y 98978802 (sin guión).
        Los NIT legados con letras en el cuerpo no son validables: la
        validación regresará False sólo por checksum (el processor decide).
        """
        nit = (nit or "").strip().upper().replace("-", "")
        # En Guatemala existen NITs históricos cortos (ej. de 2 a 6 dígitos + verificador)
        if len(nit) < 2:
            return False
        cuerpo, verificador = nit[:-1], nit[-1]
        esperado = 10 if verificador == "K" else \
                   int(verificador) if verificador.isdigit() else -1

        suma, factores = 0, list(range(2, 10))
        for i, d in enumerate(reversed(cuerpo)):
            if not d.isdigit():
                return False
            suma += int(d) * factores[i % len(factores)]
        resto = suma % 11
        digito = 0 if resto == 0 else 11 - resto
        return digito == esperado

    # ------------------------------------------------------------------
    def validate(self, data, validar_nit: bool = True,
                 pdf_correspondente: Path | None = None) -> list[str]:
        """Lista de problemas del DTE (vacía = válido).

        data puede ser FacturaDTE o dict con 'error' (XML ilegible).
        """
        if isinstance(data, dict):
            return [data["error"]] if data.get("error") else []

        problemas: list[str] = []

        if not data.nit_emisor:
            problemas.append("NIT emisor vacío")
        elif validar_nit and not self.validar_nit(data.nit_emisor):
            problemas.append(f"NIT emisor inválido (checksum): {data.nit_emisor}")

        if not UUID_RE.match(data.uuid or ""):
            problemas.append(f"UUID con formato inválido: {data.uuid}")

        if not data.fecha_emision:
            problemas.append("Sin fecha de emisión")
        try:
            from datetime import date
            date.fromisoformat(data.fecha_emision[:10])
        except ValueError:
            problemas.append(f"Fecha no interpretable: {data.fecha_emision}")

        if data.total is None or data.total < 0:
            problemas.append(f"Total negativo o ausente: {data.total}")
        if data.tipo_documento and data.tipo_documento.upper() not in TIPOS_DTE_VALIDOS:
            problemas.append(f"Tipo de DTE no reconocido: {data.tipo_documento}")

        if pdf_correspondente is not None:
            if not pdf_correspondente.exists():
                problemas.append(f"PDF correspondiente ausente: {pdf_correspondente.name}")
            elif not str(pdf_correspondente).lower().endswith(".pdf"):
                problemas.append("El PDF correspondiente no tiene extensión .pdf")

        return problemas
