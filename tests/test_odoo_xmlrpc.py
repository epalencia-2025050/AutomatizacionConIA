"""Pruebas del módulo Odoo XML-RPC (Fase 5, sin red real).

Simula el servidor XML-RPC de Odoo para validar el flujo completo:
login -> dedup por UUID -> resolver proveedor -> crear factura ->
adjuntar -> verificar. La regla §8 (SUBIDA sólo con confirmación
verificable) se comprueba con el DestinationUploader real.
"""
import base64
import os

import pytest
import xmlrpc.client as rpc

from src.destination.odoo_xmlrpc import OdooXmlrpcModule
from src.destination.module import NoConfiguradoError, ResultadoEnvio
from src.destination.uploader import DestinationUploader
from src.database.repository import Repository
from src.processing.xml_reader import XmlReader

from tests.fixtures_fel import XML_FEL_CERTIFICADO, make_xml


# --------------------------------------------------------------------
# Servidor Odoo simulado
# --------------------------------------------------------------------
class FakeObject:
    """Emula /xmlrpc/2/object ejecutando search/create sobre memoria."""

    def __init__(self):
        self.moves: dict[int, dict] = {}
        self.partners: dict[int, dict] = {}
        self.attachments: list[dict] = []
        self._seq = {"move": 0, "partner": 0}

    def execute_kw(self, db, uid, password, model, method, args, kwargs=None):
        assert uid == 1 and password == "SCObama"
        args = args or []
        dom = (args[0] if method in ("search", "search_read") else None) or []
        if model == "account.move":
            if method == "search":
                uuid = next(f[2] for f in dom if f[0] == "ref"
                            and f[1] == "=")
                return [k for k, v in self.moves.items() if v["ref"] == uuid]
            if method == "create":
                vals = args[0]
                self._seq["move"] += 1
                new = {**vals, "id": self._seq["move"]}
                new.pop("invoice_line_ids", None)
                self.moves[new["id"]] = new
                return new["id"]
        elif model == "res.partner":
            if method == "search_read":
                hit = []
                for pid, part in list(self.partners.items()):
                    vat = (part.get("vat") or "").replace("-", "")
                    if vat and (vat in str(dom) or vat in str(dom[0])):
                        hit.append(pid)
                if not hit:
                    # si el dominio trae nombre, matchearlo también
                    for pid, part in list(self.partners.items()):
                        if part.get("name") and part["name"] in str(dom):
                            hit.append(pid)
                return [{"id": i, "name": self.partners[i]["name"]}
                        for i in hit]
            if method == "create":
                vals = args[0]
                self._seq["partner"] += 1
                new = {**vals, "id": self._seq["partner"]}
                self.partners[new["id"]] = new
                return new["id"]
        elif model == "ir.attachment":
            if method == "create":
                self.attachments.append(args[0])
                return len(self.attachments)
        raise rpc.Fault(f"no-soportado: {model}.{method}")


class FakeProxy:
    """Emula /xmlrpc/2/common + rutas cuenta/objeto."""

    def __init__(self, object_endpoint):
        self._obj = object_endpoint

    @property
    def common(self):
        return self

    def version_info(self):
        return {"server_serie": "odoo-x", "server_version": "sim-17.0"}

    def authenticate(self, db, user, password, ua):
        if password == "SCObama":
            return 1
        return False

    @property
    def object(self):
        return self._obj

    def execute_kw(self, db, uid, password, model, method, args, kwargs=None):
        return self._obj.execute_kw(db, uid, password, model, method,
                                    args, kwargs)


@pytest.fixture(name="mod")
def _mod(monkeypatch, tmp_path):
    module = OdooXmlrpcModule({
        "destination": {
            "habilitado": True, "url": "https://sim.odoo.com",
            "xmlrpc": {"db": "simdb", "crear_partner": True}}})
    fake_obj = FakeObject()
    fake = FakeProxy(fake_obj)
    monkeypatch.setattr(rpc, "ServerProxy",
                        lambda url, allow_none=None: fake)
    monkeypatch.setenv("DEST_USER", "st@sim.com")
    monkeypatch.setenv("DEST_PASSWORD", "SCObama")
    module.fake_obj = fake_obj
    module.login()
    return module


def _insertar_validada(repo: Repository, tmp_path):
    data = XmlReader().parse(make_xml(tmp_path, XML_FEL_CERTIFICADO))
    xml = tmp_path / "f.xml"
    xml.write_bytes(b"<x/>")
    pdf = tmp_path / "f.pdf"
    pdf.write_bytes(b"%PDF")
    repo.insertar(data, estado="VALIDADA")
    return data, xml, pdf


def test_configuracion_incompleta_levanta(monkeypatch):
    mod = OdooXmlrpcModule({"destination": {"habilitado": True, "url": ""}})
    with pytest.raises(NoConfiguradoError):
        mod.login()


def test_credenciales_erradas_rechazan(monkeypatch):
    mod = OdooXmlrpcModule({"destination": {
        "habilitado": True, "url": "https://sim.odoo.com",
        "xmlrpc": {"db": "simdb"}}})
    fake = FakeProxy(FakeObject())
    monkeypatch.setattr(rpc, "ServerProxy", lambda url, allow_none=None: fake)
    monkeypatch.setenv("DEST_USER", "st@sim.com")
    monkeypatch.setenv("DEST_PASSWORD", "badpass")
    with pytest.raises(PermissionError):
        mod.login()


def test_envio_exito_y_duplicado_no_recrea(mod, tmp_path):
    data, xml, pdf = _insertar_validada(
        Repository(tmp_path / "b.db"), tmp_path)
    # primera pasada: crea registro y termina SUBIDA
    res1 = mod.enviar({"uuid": data.uuid, "nit_emisor": "5640773-4",
                       "nombre_emisor": "ACME SA", "total": "100",
                       "numero_documento": "11"}, xml_path=xml, pdf_path=pdf)
    assert res1 == ResultadoEnvio.SUBIDA
    # segunda pasada con misma refernecia: NO crea una segunda factura
    antes = len(mod.fake_obj.moves)
    res2 = mod.enviar({"uuid": data.uuid, "nit_emisor": "5640773-4"})
    assert res2 == ResultadoEnvio.SUBIDA
    assert len(mod.fake_obj.moves) == antes, "no debe duplicar (dédup UUID)"
    # los attachments llegaron al registro
    assert len(mod.fake_obj.attachments) == 2, "XML y PDF adjuntados"


def test_verificacion_por_uuid(mod):
    assert mod.verificar("NO-EXISTE") is False


def test_regla_8_con_uploader_sin_duplicados(mod, tmp_path):
    """SUBIDA requiere confirmación verificable del registro en Odoo."""
    repo = Repository(tmp_path / "b2.db")
    data, xml, pdf = _insertar_validada(repo, tmp_path)
    up = DestinationUploader(repo, mod, max_intentos=2)
    stats = up.run()
    assert stats["enviadas"] == 1
    assert repo.estado_actual(data.uuid) == "SUBIDA"
    # el registro verificable existe en Odoo con ref=UUID
    assert mod.verificar(data.uuid) is True
    # correo simulado: adjunto con base64 decodifica igual al original
    # los adjuntos en Odoo decodifican al contenido exacto del XML de origen
    from pathlib import Path as _Path
    datas = {base64.b64decode(a["datas"]) for a in mod.fake_obj.attachments}
    assert len(datas) >= 1
    assert _Path(data.xml_path).read_bytes() in datas, \
        "el XML de la factura quedó adjuntado íntegro"


def test_fault_rpc_marca_error(mod, tmp_path):
    # pedir un método que no existe es Fault para Odoo
    mod.models.execute_kw = lambda *a, **k: (_ for _ in ()).throw(
        rpc.Fault("x"))  # rompe -> se maneja como ERROR
    res = mod.enviar({"uuid": "ZZZ", "nit_emisor": "1-K"})
    assert res == ResultadoEnvio.ERROR
