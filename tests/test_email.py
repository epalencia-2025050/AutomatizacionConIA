"""Pruebas de la Fase 7: notificaciones por correo (SMTP simulado)."""
import pytest
from pathlib import Path

from src.notifications.email import EmailSender


SETTINGS_BASE = {"notifications": {"email": {
    "activar": True, "smtp_host": "smtp.test.com", "smtp_port": 465}}}


@pytest.fixture(name="sender")
def _sender(monkeypatch):
    s = EmailSender(SETTINGS_BASE)
    enviados = []

    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            self.host = host
            self.log = [("login", None)]

        def login(self, user, pw):
            self.log.append(("login", user, pw))
            FakeSMTP.last = self

        def send_message(self, msg):
            FakeSMTP.last_msg = msg
            self.log.append(("send", msg["Subject"], msg["To"]))

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    import src.notifications.email as mod
    monkeypatch.setattr(mod.smtplib, "SMTP_SSL", FakeSMTP)
    monkeypatch.setattr(mod.os, "environ", {
        "MAIL_USER": "yo@test.com", "MAIL_PASS": "app-pass-16-chars",
        "MAIL_TO": "reportes@test.com"})
    monkeypatch.setattr(mod.os, "getenv",
                        lambda k, d="": {"MAIL_USER": "yo@test.com",
                                         "MAIL_PASS": "x",
                                         "MAIL_TO": "reportes@test.com"}.get(k, ""))
    s._FakeSMTP = FakeSMTP   # acceso al último mensaje enviado
    return s


def test_desactivado_no_envia():
    s = EmailSender({"notifications": {"email": {"activar": False}}})
    assert s.disponible() is False
    assert s.enviar("x", "cuerpo") is False


def test_disponible_con_env(sender):
    assert sender.disponible() is True


def test_envio_basico(sender):
    assert sender.enviar("Prueba", "Texto del cuerpo") is True
    msg = sender._FakeSMTP.last_msg
    assert msg["Subject"] == "Prueba"
    assert msg["To"] == "reportes@test.com"
    cuerpo = msg.get_content() if not msg.is_multipart() else \
        next(p.get_content() for p in msg.iter_parts()
             if p.get_content_type() == "text/plain")
    assert "Texto del cuerpo" in cuerpo


def test_envio_con_adjunto_csv(sender, tmp_path):
    csv = tmp_path / "reporte.csv"
    csv.write_text("tipo,uuid\nDETALLE,AAA\n", encoding="utf-8-sig")
    assert sender.enviar("Reporte", "ver adjunto", adjuntos=[csv]) is True
    msg = sender._FakeSMTP.last_msg
    partes = list(msg.iter_parts())
    assert len(partes) == 2, "texto + adjunto"
    adj = partes[1]
    assert adj.get_filename() == "reporte.csv"
    import base64
    assert "DETALLE,AAA" in base64.b64decode(adj.get_payload()).decode()


def test_alerta_2fa_envia_mensaje_especificado(sender):
    assert sender.alerta_2fa() is True
    msg = sender._FakeSMTP.last_msg
    assert "2FA" in msg["Subject"]


def test_smtp_down_falla_silencioso(sender, monkeypatch, tmp_path):
    import src.notifications.email as mod

    class Muerto:
        def __init__(self, *a, **k):
            raise ConnectionError("sin red")

    monkeypatch.setattr(mod.smtplib, "SMTP_SSL", Muerto)
    # el sistema NO se rompe por un correro fallido
    assert sender.enviar("x", "y") is False
