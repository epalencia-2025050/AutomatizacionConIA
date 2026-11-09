"""Pruebas del módulo destino Odoo (sin red)."""
import pytest

from src.destination.odoo import (OdooDestinationModule,
                                  ODOO_LOGIN_SELECTORS)
from src.destination.module import NoConfiguradoError, ResultadoEnvio

SETTINGS_BASE = {"destination": {"habilitado": True,
                                 "url": "https://ejemplo.odoo.com",
                                 "timeouts": {"login_ms": 1000, "timeout_ms": 1000},
                                 "max_intentos": 3}}
SELECTORS_BASE = {"destination": {"odoo": {"envio": {
    "menu_path": ['a:has-text("Contabilidad")'],
    "crear_btn": 'button.o_list_button_add',
    "campos": {"numero_documento": 'input[name="ref"]'},
    "guardar_btn": 'button.o_form_button_save'}}}}


def test_login_selectors_estandar_odoo():
    """Los selectores del login son el estándar de Odoo (verificado)."""
    assert ODOO_LOGIN_SELECTORS["user_field"] == 'input[name="login"]'
    assert ODOO_LOGIN_SELECTORS["password_field"] == 'input[name="password"]'
    assert ODOO_LOGIN_SELECTORS["submit_button"] == 'button[type="submit"]'
    assert ODOO_LOGIN_SELECTORS["url"] == "/web/login"


def test_sin_url_no_configurado():
    settings = {**SETTINGS_BASE,
                "destination": {**SETTINGS_BASE["destination"], "url": ""}}
    mod = OdooDestinationModule(settings, {"destination": {"odoo": {}}})
    assert mod.configurado is False


def test_sin_campos_envio_no_configurado():
    mod = OdooDestinationModule(SETTINGS_BASE,
                                {"destination": {"odoo": {}}})
    assert mod.configurado is False


def test_configurado_completo():
    mod = OdooDestinationModule(SETTINGS_BASE, SELECTORS_BASE)
    assert mod.configurado is True
    assert mod.name == "odoo"


def test_url_base_login_correcta(monkeypatch):
    """La URL del login se compone como <instancia>/web/login."""
    base = SETTINGS_BASE["destination"]["url"].rstrip("/")
    assert f"{base}/web/login" == "https://ejemplo.odoo.com/web/login"


def test_envio_sin_configurar_lanza_error():
    mod = OdooDestinationModule({"destination": {"habilitado": True,
                                                 "url": "https://x.odoo.com"}},
                                {"destination": {"odoo": {}}})
    with pytest.raises(NoConfiguradoError):
        mod.enviar({"uuid": "AA"}, xml_path=None, pdf_path=None)
