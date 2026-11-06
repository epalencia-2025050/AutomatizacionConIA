"""Extracción de datos del XML del CFDI."""
import logging
import xml.etree.ElementTree as ET

logger = logging.getLogger(__name__)


class XmlReader:
    """Lee los archivos XML de la versión 4.x del CFDI y extrae campos clave."""

    def __init__(self, namespaces: dict | None = None):
        ns = namespaces or {}
        self.ns_cfdi = ns.get("cfdi", "http://www.sat.gob.mx/cfd/4")
        self.ns_tfd = ns.get("tfd", "http://www.sat.gob.mx/TimbreFiscalDigital")

    # ------------------------------------------------------------------
    def extract(self, xml_path) -> dict | None:
        """Devuelve un diccionario con los datos del CFDI, o None si falla."""
        try:
            tree = ET.parse(str(xml_path))
            root = tree.getroot()
        except ET.ParseError as exc:
            logger.error("XML inválido %s: %s", xml_path, exc)
            return None

        try:
            data = {
                "archivo_xml": xml_path.name,
                "serie": root.attrib.get("Serie", ""),
                "folio": root.attrib.get("Folio", ""),
                "fecha_emision": root.attrib.get("Fecha", ""),
                "subtotal": self._to_float(root.attrib.get("SubTotal")),
                "total": self._to_float(root.attrib.get("Total")),
                "moneda": root.attrib.get("Moneda", "MXN"),
            }
        except Exception as exc:
            logger.error("Error extrayendo comprobante de %s: %s", xml_path, exc)
            return None

        data.update(self._extract_parties(root))
        data.update(self._extract_uuid(root))
        return data

    # ------------------------------------------------------------------
    def _extract_parties(self, root) -> dict:
        emisor = root.find(f"{{{self.ns_cfdi}}}Emisor")
        receptor = root.find(f"{{{self.ns_cfdi}}}Receptor")
        return {
            "rfc_emisor": emisor.attrib.get("Rfc", "") if emisor is not None else "",
            "nombre_emisor": emisor.attrib.get("Nombre", "") if emisor is not None else "",
            "rfc_receptor": receptor.attrib.get("Rfc", "") if receptor is not None else "",
            "nombre_receptor": receptor.attrib.get("Nombre", "") if receptor is not None else "",
        }

    def _extract_uuid(self, root) -> dict:
        """Busca el UUID dentro del complemento TimbreFiscalDigital."""
        tfd = root.find(
            f".//{{{self.ns_cfdi}}}Complemento/{{{self.ns_tfd}}}TimbreFiscalDigital"
        )
        return {"uuid": tfd.attrib.get("UUID", "") if tfd is not None else ""}

    @staticmethod
    def _to_float(value) -> float:
        try:
            return float(value) if value else 0.0
        except (TypeError, ValueError):
            return 0.0
