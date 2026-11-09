"""Contrato que TODO módulo de destino debe cumplir (Fase 3).

La plataforma destino es desconocida: este contrato permite integrar
cualquier página al llenar config/settings.yaml y config/selectors.yaml,
sin modificar código del resto del sistema.
"""
from abc import ABC, abstractmethod
from enum import Enum
from pathlib import Path


class ResultadoEnvio(str, Enum):
    """Resultados posibles de un envío al destino.

    SUBIDA: enviado Y confirmado verificablemente (único estado que
            autoriza marcar SUBIDA en la BD).
    SIN_CONFIRMACION: el envío se realizó pero la confirmación no fue
            verificable -> queda PENDIENTE_SUBIDA (regla §8 del diseño).
    ERROR: no se envió o el destino rechazó -> estado ERROR con motivo.
    """
    SUBIDA = "SUBIDA"
    SIN_CONFIRMACION = "SIN_CONFIRMACION"
    ERROR = "ERROR"


class DestinationModule(ABC):
    """Interface para una plataforma de destino concreta.

    Un integrador nuevo hereda esta clase, implementa el portal real y
    se registra en src/destination/__init__.py (__generadores_).
    """

    name: str = "sin-nombre"
    configurado: bool = False   # False mientras falten selectores reales

    @abstractmethod
    def login(self) -> None:
        """Inicia sesión en el destino (credenciales desde .env)."""

    @abstractmethod
    def enviar(self, factura: dict, xml_path: Path | None = None,
               pdf_path: Path | None = None) -> ResultadoEnvio:
        """Transfiere la factura al destino y su confirmación."""

    @abstractmethod
    def verificar(self, uuid: str) -> bool:
        """Confirma de forma verificable que el documento existe en el destino."""


class NoConfiguradoError(RuntimeError):
    """Se intentó usar un módulo destino sin selectores reales en config."""
