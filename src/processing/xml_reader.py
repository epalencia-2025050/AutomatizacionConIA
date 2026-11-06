"""Lector de XML del DTE (FEL Guatemala) basado en lxml.

Estructura real del esquema FEL (0.1 / 0.2, namespace dte):
  GTDocumento
    └ SAT ClaseDocumento="dte"
        └ DTE ID="DatosCertificados"
            └ DatosEmision
                ├ DatosGenerales  @Tipo @FechaHoraEmision @CodigoMoneda [@Numero]
                ├ Emisor          @NITEmisor @NombreEmisor @NombreComercial
                ├ Receptor        @IDReceptor @NombreReceptor
                ├ Items/Item
                └ Totales         GranTotal
            └ Certificación:
                ├ SelloRecepcion
                └ NumeroAutorizacion       (texto = UUID, @Serie)

Uso búsqueda por *local-name* para soportar variantes 0.1/0.2/0.3 del
namespace, y respaldo por patrón UUID si el certificador cambió nombres.
"""
import logging
import re
from pathlib import Path

from lxml import etree

from src.processing.models import FacturaDTE

logger = logging.getLogger(__name__)

UUID_RE = re.compile(r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-"
                     r"[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}|[0-9A-Fa-f]{32}")


def local_tag(el) -> str:
    """Nombre local de un elemento (sin namespace)."""
    tag = el.tag
    if not isinstance(tag, str):
        return ""
    return tag.rpartition("}")[2]


def find_local(root, nombre: str):
    """Primera aparición (orden de documento) con local-name coincidente.

    lxml no soporta el predicado local-name() en ElementPath, por lo que
    el recorrido se hace manualmente (compatible 0.1/0.2/0.3 de namespace).
    """
    for el in iter_local(root, nombre):
        return el
    return None


def find_all_local(root, nombre: str) -> list:
    return list(iter_local(root, nombre))


def iter_local(root, nombre: str):
    if root is None:
        return
    pila = [root]
    while pila:
        el = pila.pop(0)
        tag = el.tag
        if isinstance(tag, str) and tag.rpartition("}")[2] == nombre:
            yield el
        pila.extend(list(el))


def parse_decimal(texto: str | None) -> float | None:
    if texto is None:
        return None
    t = (texto or "").strip().replace(",", "")
    contiene_letras = re.search(r"[A-Za-z]", t)
    if contiene_letras is None:
        return float(t) if t else None
    # format "Gravadas Q 84.00, Total Q 110.29" -> numero final
    numeros = re.findall(r"-?\d+(?:\.\d+)?", t)
    return float(numeros[-1]) if numeros else None


class XmlReader:
    """Extrae FacturaDTE desde un XML FEL certificado."""

    def parse(self, xml_path: Path) -> FacturaDTE | dict:
        """Devuelve FacturaDTE o dict con clave 'error' si el XML no sirve."""
        xml_path = Path(xml_path)
        try:
            tree = etree.parse(str(xml_path),          # noqa: S320 (datos confiables de SAT)
                               parser=etree.XMLParser(resolve_entities=False,
                                                      no_network=True,
                                                      huge_tree=True))
            root = tree.getroot()
        except (etree.XMLSyntaxError, OSError) as exc:
            return {"error": f"XML inválido o ilegible: {type(exc).__name__}"}

        if find_local(root, "GTDocumento") is None and local_tag(root) != "GTDocumento":
            return {"error": "No es un DTE FEL (falta nodo GTDocumento)"}

        try:
            return self._extract(xml_path, root)
        except Exception as exc:   # pylint: disable=broad-except
            logger.exception("Error extrayendo %s", xml_path.name)
            return {"error": f"Error extrayendo datos: {exc}"}

    # ------------------------------------------------------------------
    def _extract(self, xml_path: Path, root) -> dict | FacturaDTE:
        datos_generales = find_local(root, "DatosGenerales")
        emisor = find_local(root, "Emisor")
        receptor = find_local(root, "Receptor")
        total_nodo = find_local(root, "GranTotal")

        if emisor is None or datos_generales is None:
            return {"error": "XML sin bloques Emisor/DatosGenerales"}

        raw = {"nit_emisor": emisor.get("NITEmisor") or "",
               "nombre_emisor": (emisor.get("NombreEmisor") or
                                 emisor.get("NombreComercial") or "").strip(),
               "nit_receptor": receptor.get("IDReceptor") if receptor is not None else "",
               "nombre_receptor": receptor.get("NombreReceptor") if receptor is not None else "",
               "tipo_documento": datos_generales.get("Tipo") or "",
               "serie": datos_generales.get("Serie") or "",
               "numero_documento": datos_generales.get("Numero") or "",
               "fecha_emision": datos_generales.get("FechaHoraEmision") or "",
               "moneda": datos_generales.get("CodigoMoneda") or "GTQ",
               "xml_path": str(Path(xml_path.resolve()).as_posix()),
               "num_items": len(find_all_local(root, "Item"))}
        total = parse_decimal(total_nodo.text if total_nodo is not None else None)
        raw["total"] = total if total is not None else 0.0

        # Impuesto total registrado (IVA, si existe)
        for ti in find_all_local(root, "TotalImpuesto"):
            nombre = (ti.get("NombreCorto") or "").upper()
            if nombre in ("IVA", "VCOR", "IVA-12"):
                if (v := parse_decimal(ti.get("TotalMontoImpuesto"))) is not None:
                    raw["iva"] = v
                break

        uuid, serie_autorizacion, fecha_cert = self._localiza_uuid(root)
        raw["uuid"] = uuid
        if serie_autorizacion and not raw["serie"]:
            raw["serie"] = serie_autorizacion
        raw["fecha_certificacion"] = fecha_cert

        if not raw["uuid"]:
            return {"error": "XML sin número de autorización (UUID)",
                    "parcial": True}

        try:
            return FacturaDTE(**raw)
        except Exception as exc:
            return {"error": f"Datos inválidos: {exc}"}

    # ------------------------------------------------------------------
    def _localiza_uuid(self, root) -> tuple[str, str, str]:
        """Ubica UUID + serie + fecha de certificación del XML certificado.

        Rutas del esquema FEL:
          - <NumeroAutorizacion Serie="...">UUID</NumeroAutorizacion>
          - <SelloRecepcion Fecha="..." UUID="...">sello</SelloRecepcion>
          - sin coincidir: primer UUID válido en todo el documento.
        """
        fecha_cert = ""
        sello = find_local(root, "SelloRecepcion")
        if sello is not None:
            fecha_cert = sello.get("Fecha") or ""
            for candidato in (sello.get("UUID") or "", sello.text or ""):
                uuid = _normaliza_uuid(candidato)
                if uuid:
                    return uuid, "", fecha_cert

        autorizacion = find_local(root, "NumeroAutorizacion")
        if autorizacion is not None:
            uuid = _normaliza_uuid(autorizacion.text or "")
            if uuid:
                return uuid, autorizacion.get("Serie") or "", fecha_cert

        # Respaldo: cualquier texto del documento que contenga un UUID
        raw = etree.tostring(root, encoding="unicode")
        for texto in UUID_RE.findall(raw):
            uuid = _normaliza_uuid(texto)
            if uuid:
                return uuid, "", fecha_cert
        return "", "", fecha_cert


def _normaliza_uuid(texto: str) -> str | None:
    """Forma canónica del UUID: 8-4-4-4-12 en mayúsculas."""
    h = re.sub(r"[-\s]", "", texto or "").upper()
    if re.fullmatch(r"[0-9A-F]{32}", h):
        return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"
    return None
