"""Validation of the extracted CFDI data."""
import logging
import os
import re

logger = logging.getLogger(__name__)

RFC_PATTERN = re.compile(r"^[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3}$", re.IGNORECASE)
UUID_PATTERN = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


class Validator:
    """Verifica integridad básica de los datos extraídos del XML."""

    def __init__(self, processing_config: dict | None = None):
        config = processing_config or {}
        self.validate_rfc = config.get("validate_rfc", True)
        self.own_rfc = os.getenv("SAT_RFC", "")

    def validate(self, data: dict) -> bool:
        """Retorna True si los datos mínimos están completos."""
        uuid = data.get("uuid", "")
        if not uuid or not UUID_PATTERN.match(str(uuid)):
            logger.warning("UUID inválido o ausente")
            return False

        rfc = data.get("rfc_emisor", "")
        if self.validate_rfc and not RFC_PATTERN.match(str(rfc)):
            logger.warning("RFC emisor inválido: %r", rfc)
            return False

        if data.get("total", 0.0) <= 0:
            logger.warning("Total inválido: %s", data.get("total"))
            return False

        if data.get("fecha_emision", "") == "":
            logger.warning("Fecha de emisión ausente")
            return False

        return True

    def is_from_expected_issuer(self, data: dict, rfc: str | None = None) -> bool:
        """Filtra facturas de un emisor específico (útil cuando se buscan por RFC)."""
        target = rfc or self.own_rfc
        if not target:
            return True
        return str(data.get("rfc_emisor", "")).upper() == target.upper()
