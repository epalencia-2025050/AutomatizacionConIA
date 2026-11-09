"""Notificaciones por correo (Fase 7).

SMTP genérico (Gmail, Outlook o el de la empresa). Sin API Keys de pago:
Gmail usa la "contraseña de aplicación" (se genera gratis en la cuenta
de Google y NO es la contraseña personal).

Configuración en settings.yaml -> notifications.email + .env:
  MAIL_USER / MAIL_PASS / MAIL_TO

El sistema NUNCA se interrumpe si el correo falla: sólo se registra.
"""
import logging
import os
import smtplib
from email.message import EmailMessage
from email.utils import formatdate
from pathlib import Path

logger = logging.getLogger(__name__)


class EmailSender:
    def __init__(self, settings: dict):
        self.cfg = ((settings.get("notifications") or {}).get("email") or {})
        self.activar = bool(self.cfg.get("activar"))

    # ------------------------------------------------------------------
    def disponible(self) -> bool:
        """True si hay credenciales en .env y el módulo está activado."""
        if not self.activar:
            return False
        return (bool(os.getenv("MAIL_USER", ""))
                and bool(os.getenv("MAIL_PASS", ""))
                and bool(os.getenv("MAIL_TO", "")))

    # ------------------------------------------------------------------
    def enviar(self, asunto: str, cuerpo: str,
               adjuntos: list[Path] | None = None) -> bool:
        """Envía un correo (aprobando fallos silenciosamente: warning)."""
        if not self.disponible():
            logger.info("Correo desactivado o sin credenciales: se omite")
            return False
        host = self.cfg.get("smtp_host", "smtp.gmail.com")
        puerto = int(self.cfg.get("smtp_port", 465))

        msg = EmailMessage()
        msg["From"] = os.environ["MAIL_USER"]
        msg["To"] = os.environ["MAIL_TO"]
        msg["Date"] = formatdate()
        msg["Subject"] = asunto
        msg.set_content(cuerpo)

        for archivo in (adjuntos or []):
            data = Path(archivo).read_bytes()
            mtype = Path(archivo).suffix.lower().lstrip(".")
            maintype = {"csv": "text", "pdf": "application"}.get(mtype,
                                                                 "application")
            subtype = "csv" if mtype == "csv" else mtype \
                if mtype != "pdf" else "pdf"
            msg.add_attachment(data, maintype=maintype, subtype=subtype,
                               filename=Path(archivo).name)

        try:
            if self.cfg.get("usar_tls", True):
                with smtplib.SMTP_SSL(host, puerto, timeout=20) as smtp:
                    smtp.login(os.environ["MAIL_USER"],
                               os.environ["MAIL_PASS"])
                    smtp.send_message(msg)
            else:
                with smtplib.SMTP(host, puerto, timeout=20) as smtp:
                    smtp.starttls()
                    smtp.login(os.environ["MAIL_USER"],
                               os.environ["MAIL_PASS"])
                    smtp.send_message(msg)
            logger.info("Correo enviado a %s: %s", msg["To"], asunto)
            return True
        except Exception as exc:   # no romper nada por el correo
            logger.warning("No se pudo enviar el correo (%s): %s", asunto, exc)
            return False

    # ------------------------------------------------------------------
    def enviar_reporte(self, reporte_csv: Path, resumen_flujo: dict) -> bool:
        """Correo con el CSV de la corrida adjunto."""
        lineas = "; ".join(f"{k}={v}" for k, v in
                           (resumen_flujo or {}).items())
        return self.enviar(
            asunto=f"Automatización DTE — reporte {reporte_csv.stem}",
            cuerpo=(f"Resumen de la corrida:\n{lineas}\n\n"
                    f"Detalle completo en el CSV adjunto.\n"),
            adjuntos=[reporte_csv])

    def alerta_2fa(self) -> bool:
        """Aviso: el portal del SAT está pidiendo el código de 2FA."""
        return self.enviar(
            asunto="⚠ SAT requiere tu 2FA ahora",
            cuerpo=("La automatización inició sesión en Agencia Virtual y el "
                    "portal pide el código de 6 dígitos de Microsoft "
                    "Authenticator. Si la tarea corre en tu PC abre la ventana "
                    "del navegador; si corre programada, la corrida "
                    "terminará en error sin tu código.\n"))
