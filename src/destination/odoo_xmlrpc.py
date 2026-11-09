"""Módulo destino Odoo vía API XML-RPC (Fase 5, mejora #1).

Odoo incluye en TODAS las versiones una API XML-RPC:
  <instancia>/xmlrpc/2/common  -> versión + authenticate(db, user, password)
  <instancia>/xmlrpc/2/object  -> create/search/print sobre los modelos

Ventajas sobre el módulo por navegador (src/destination/odoo.py):
 - No depende de la UI: no se rompe al cambiar de versión Odoo (16/17/18)
 - Confirmación 100% verificable: el registro existe con ref=UUID
 - Anti-duplicados real: busca ref=UUID ANTES de crear
 - Una factura se procesa en <1 s sin render de pantallas

Credenciales: .env con DEST_USER, DEST_PASSWORD y (self-hosted) DEST_DB.
Sin API Key de pago: la contraseña del usuario sirve directamente.
"""
import base64
import logging
import os
import xmlrpc.client as rpc
from pathlib import Path

from src.destination.module import (DestinationModule, NoConfiguradoError,
                                    ResultadoEnvio)

logger = logging.getLogger(__name__)

MIMETYPES = {".xml": "application/xml", ".pdf": "application/pdf"}


class OdooXmlrpcModule(DestinationModule):
    """Plug-in de destino que registra facturas de proveedor en Odoo."""

    name = "odoo-xmlrpc"

    def __init__(self, settings: dict):
        self.dest = settings.get("destination") or {}
        self.cfg = (self.dest.get("xmlrpc") or {})
        self.url = (self.dest.get("url") or "").strip().rstrip("/")
        self.db = (self.cfg.get("db") or os.getenv("DEST_DB", "")).strip()
        self.uid: int | None = None
        self._password = ""
        self.common: rpc.ServerProxy | None = None
        self.models: rpc.ServerProxy | None = None

    # ------------------------------------------------------------------
    def configurado(self) -> bool:
        return bool(self.url) and bool(self.db)

    # ------------------------------------------------------------------
    def login(self) -> None:
        """Autentica con email+password del usuario (sin API Key)."""
        user = os.getenv("DEST_USER", "")
        password = os.getenv("DEST_PASSWORD", "")
        if not self.url or not self.db:
            raise NoConfiguradoError(
                "Odoo XML-RPC sin configurar: llenar settings.yaml "
                "(destination.url + destination.xmlrpc.db) ")
        if not user or not password:
            raise ValueError("DEST_USER y DEST_PASSWORD deben ir en .env")

        self.common = rpc.ServerProxy(f"{self.url}/xmlrpc/2/common",
                                      allow_none=True)
        try:
            version = self.common.version_info()
            logger.info("Odoo %s detectado en %s",
                        version.get("server_serie", "?"), self.url)
        except Exception as exc:
            raise ConnectionError(f"No se alcanzó {self.url}: {exc}") from exc

        uid = self.common.authenticate(self.db, user, password, {})
        if not uid:
            raise PermissionError(
                "Login Odoo XML-RPC rechazado (usuario/contraseña/BD)")
        self.uid = int(uid)
        self._password = password
        self.models = rpc.ServerProxy(f"{self.url}/xmlrpc/2/object",
                                      allow_none=True)
        logger.info("Autenticado en Odoo (uid=%s, bd=%s)", uid, self.db)

    # ------------------------------------------------------------------
    def _kw(self, model: str, method: str, args: list,
            kwargs: dict | None = None):
        return self.models.execute_kw(self.db, self.uid, self._password,
                                      model, method, args, kwargs or {})

    def _resolver_partner(self, factura: dict) -> int:
        """Busca el proveedor por NIT (con y sin guión) o nombre; lo crea si falta."""
        nit = (factura.get("nit_emisor") or "").strip()
        nombre = (factura.get("nombre_emisor") or "").strip()
        if not nit and not nombre:
            raise ValueError("La factura no trae emisor (NIT ni nombre)")

        dominio = ["|", ["|", ["vat", "=", nit],
                    ["vat", "=", nit.replace("-", "")]],
                    ["name", "=", nombre]]
        filas = self._kw("res.partner", "search_read", [dominio],
                         {"fields": ["id", "name"], "limit": 1})
        if filas:
            return int(filas[0]["id"])

        if not self.cfg.get("crear_partner", True):
            raise ValueError(f"Proveedor no encontrado en Odoo (NIT={nit})")
        nuevo = self._kw("res.partner", "create",
                         [{"name": nombre or f"Proveedor FEL {nit}",
                           "vat": nit}])
        logger.info("Proveedor creado en Odoo: %s (id=%s)", nombre, nuevo)
        return int(nuevo) if nuevo and not isinstance(nuevo, list) else int(nuevo[0])

    # ------------------------------------------------------------------
    def enviar(self, factura: dict, xml_path=None, pdf_path=None) -> ResultadoEnvio:
        """Crea una factura de proveedor DRAFT con ref=UUID y adjunta XML/PDF.

        Deduplicación: si ya existe account.move con ref=UUID, no se crea
        nada y se confirma (SUBIDA) — nunca hay duplicados.
        """
        if not self.configurado():
            raise NoConfiguradoError("Odoo XML-RPC sin url/db configuradas")
        if self.uid is None:
            self.login()

        uuid = (factura.get("uuid") or "").strip()
        if not uuid:
            return ResultadoEnvio.ERROR

        try:
            # --- anti-duplicados: buscar antes de crear ---
            existentes = self._kw("account.move", "search",
                                  [[["ref", "=", uuid]]], {"limit": 1})
            if existentes:
                logger.info("UUID=%s ya está registrado (id=%s): no duplica",
                            uuid, existentes[0])
                return ResultadoEnvio.SUBIDA

            partner_id = self._resolver_partner(factura)
            vals = {
                "move_type": "in_invoice",
                "ref": uuid,                     # referencia = FEL UUID
                "partner_id": partner_id,
                "invoice_date": str(factura.get("fecha_emision") or "") or None,
                "invoice_line_ids": [(0, 0, {
                    "name": (f"FEL {factura.get('numero_documento')}"
                             f" / {uuid[:8]}"),
                    "quantity": 1.0,
                    "price_unit": float(factura.get("total") or 0.0),
                })],
            }
            if vals["invoice_date"] in ("", "None"):
                vals.pop("invoice_date")

            if self.cfg.get("publicar", False):
                vals["state"] = "posted"   # opcional: contabilizada directa

            move_id = self._kw("account.move", "create", [vals])
            move_id = int(move_id[0] if isinstance(move_id, list) else move_id)
            logger.info("Factura creada en Odoo: account.move id=%s (UUID=%s)",
                        move_id, uuid)

            # --- adjuntos XML + PDF ---
            for archivo in (xml_path, pdf_path):
                if archivo and Path(str(archivo)).exists():
                    self._adjuntar(move_id, Path(archivo))

            return self.verificar(uuid) and ResultadoEnvio.SUBIDA \
                or ResultadoEnvio.SIN_CONFIRMACION

        except rpc.Fault as exc:
            logger.error("Odoo rechazó la factura (UUID=%s): %s", uuid, exc)
            return ResultadoEnvio.ERROR
        except Exception as exc:   # pylint: disable=broad-except
            logger.exception("Fallo de envío XML-RPC (UUID=%s): %s", uuid, exc)
            return ResultadoEnvio.ERROR

    def _adjuntar(self, move_id: int, archivo: Path) -> None:
        self._kw("ir.attachment", "create", [{
            "name": archivo.name,
            "datas": base64.b64encode(archivo.read_bytes()).decode("ascii"),
            "mimetype": MIMETYPES.get(archivo.suffix.lower(),
                                      "application/octet-stream"),
            "res_model": "account.move",
            "res_id": move_id,
        }])

    # ------------------------------------------------------------------
    def verificar(self, uuid: str) -> bool:
        """Confirmación verificable: el registro existe con ref = UUID."""
        if not uuid or self.uid is None:
            return False
        try:
            ids = self._kw("account.move", "search",
                           [[["ref", "=", uuid]]], {"limit": 1})
            return bool(ids)
        except Exception as exc:   # pylint: disable=broad-except
            logger.error("No se pudo verificar UUID=%s en Odoo: %s", uuid, exc)
            return False
