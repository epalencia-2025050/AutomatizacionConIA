"""Fixtures XML FEL (esquema real SAT Guatemala, versions 0.2).

BLOQUES copian la estructura oficial:
  GTDocumento > SAT > DTE > DatosEmision > (DatosGenerales, Emisor,
  Receptor, Items, Totales) + certificación (SelloRecepcion,
  NumeroAutorizacion con el UUID de 32 hex).
"""
from pathlib import Path

# NIT con checksum válido: 5640773-4 (certificador INNOVA real)
NIT = "56407734"

XML_FEL_CERTIFICADO = """<?xml version="1.0" encoding="UTF-8"?>
<dte:GTDocumento xmlns:dte="http://www.sat.gob.gt/dte/fel/0.2.0"
    xmlns:ds="http://www.w3.org/2000/09/xmldsig#" Version="0.1">
  <dte:SAT ClaseDocumento="dte">
    <dte:DTE ID="DatosCertificados">
      <dte:DatosEmision ID="DatosEmision">
        <dte:DatosGenerales CodigoMoneda="GTQ"
            FechaHoraEmision="2026-03-15T09:40:00.000-06:00" Tipo="FACT"/>
        <dte:Emisor AfiliacionIVA="GEN" CodigoEstablecimiento="1"
            CorreoEmisor="cobros@proveedor.com.gt" NITEmisor="56407734"
            NombreComercial="PROVEEDOR GT" NombreEmisor="PROVEEDOR, SOCIEDAD ANONIMA">
          <dte:DireccionEmisor>
            <dte:Direccion>3 CALLE 6-11 ZONA 9</dte:Direccion>
            <dte:Pais>GT</dte:Pais>
          </dte:DireccionEmisor>
        </dte:Emisor>
        <dte:Receptor CorreoReceptor="compras@comprador.gt"
            IDReceptor="7378106" NombreReceptor="COMPRADOR, SA"/>
        <dte:Items>
          <dte:Item BienOServicio="B" NumeroLinea="1">
            <dte:Cantidad>2.00</dte:Cantidad>
            <dte:Descripcion>SERVICIO A</dte:Descripcion>
            <dte:PrecioUnitario>1000.00</dte:PrecioUnitario>
            <dte:Precio>2000.00</dte:Precio>
            <dte:Total>2000.00</dte:Total>
          </dte:Item>
        </dte:Items>
        <dte:Totales>
          <dte:TotalImpuestos>
            <dte:TotalImpuesto NombreCorto="IVA" TotalMontoImpuesto="214.29"/>
          </dte:TotalImpuestos>
          <dte:GranTotal>2000.00</dte:GranTotal>
        </dte:Totales>
      </dte:DatosEmision>
      <dte:Certificacion>
        <dte:SelloRecepcion
            Fecha="2026-03-15T09:40:26.000-06:00"
            UUID="9A61EB38120F3450A7BF3E3001B91102">
            sello de recepción del certificador
        </dte:SelloRecepcion>
        <dte:NumeroAutorizacion Serie="A">
          9A61EB38120F3450A7BF3E3001B91102
        </dte:NumeroAutorizacion>
      </dte:Certificacion>
    </dte:DTE>
  </dte:SAT>
</dte:GTDocumento>
"""

XML_FEL_CON_UUID_GUIONES = XML_FEL_CERTIFICADO.replace(
    "9A61EB38120F3450A7BF3E3001B91102",
    "9A61EB38-120F-3450-A7BF-3E3001B91102")
# mismo UUID con guiones; el reader debe normalizar al mismo valor

XML_SIN_UUID = XML_FEL_CERTIFICADO.replace(
    ' UUID="9A61EB38120F3450A7BF3E3001B91102"', "").replace(
    """<dte:NumeroAutorizacion Serie="A">
          9A61EB38120F3450A7BF3E3001B91102
        </dte:NumeroAutorizacion>""", "")

XML_MALFORMADO = "<?xml version='1.0'?><dte:GTDocumento> bloque sin cerrar"

XML_NO_FEL = """<?xml version="1.0"?>
<Comprobante xmlns="http://www.sat.gob.mx/cfd/4" Total="116.00"/>"""


def make_xml(tmp_path: Path, contenido: str, nombre: str = "test.xml") -> Path:
    path = tmp_path / nombre
    path.write_text(contenido, encoding="utf-8")
    return path


UUID_ESPERADO = "9A61EB38-120F-3450-A7BF-3E3001B91102"
