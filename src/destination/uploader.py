"""Orquestador de transferencias al destino (Fase 3).

Reglas del diseño respetadas:
 - sólo sube lo VALIDADA / PENDIENTE_SUBIDA propio
 - marca PENDIENTE_SUBIDA antes de iniciar el primer intento
 - NO marca SUBIDA sin confirmación verificable del módulo
 - ERROR aumenta intentos y guarda el motivo; reintentos configurables
"""
import logging
from pathlib import Path

from src.destination.module import DestinationModule, ResultadoEnvio
from src.database.repository import Repository
from src.utils.logger import setup_logger

logger = logging.getLogger(__name__)


class DestinationUploader:
    """Itera facturas VALIDADAS y las transfiere vía un módulo destino."""

    def __init__(self, repo: Repository, module: DestinationModule,
                 max_intentos: int = 3):
        self.repo = repo
        self.module = module
        self.max_intentos = max(max_intentos, 1)

    # ------------------------------------------------------------------
    def run(self) -> dict:
        setup_logger()
        conteo = {"enviadas": 0, "sin_confirmacion": 0, "errores": 0,
                  "omitidas_max_intentos": 0}
        if not getattr(self.module, "configurado", True):
            msg = ("Destino no configurado: no se enviará nada hasta "
                   "definir la página real (Fase 3 pendiente de integración)")
            logger.info(msg)
            return {**conteo, "mensaje": msg}

        self.module.login()
        pendientes = self.repo.listar_por_estado(("VALIDADA", "PENDIENTE_SUBIDA", "ERROR"))
        logger.info("Facturas destinadas a enviar: %s", len(pendientes))

        for fila in pendientes:
            uuid = fila.get("uuid") or ""
            intentos = int(fila.get("intentos") or 0) + 1
            if intentos > self.max_intentos:
                logger.warning("UUID=%s superó %s intentos; se omite",
                               uuid, self.max_intentos)
                conteo["omitidas_max_intentos"] += 1
                continue

            self.repo.marcar_estado(uuid, "PENDIENTE_SUBIDA")
            xml_path = fila.get("xml_path") or None
            pdf_path = fila.get("pdf_path") or None
            resultado = self.module.enviar(fila, xml_path, pdf_path)

            if resultado == ResultadoEnvio.SUBIDA:
                self.repo.marcar_estado(uuid, "SUBIDA")
                conteo["enviadas"] += 1
            elif resultado == ResultadoEnvio.SIN_CONFIRMACION:
                # truncar intentos: sigue pendiente, NO SUBIDA
                logger.info("UUID=%s enviado sin confirmación verificable",
                            uuid)
                conteo["sin_confirmacion"] += 1
            else:   # ERROR
                self.repo.marcar_estado(uuid, "ERROR",
                                        mensaje_error="Destino rechazó/no envió")
                conteo["errores"] += 1
        logger.info("Envíos al destino: %s", conteo)
        return conteo
