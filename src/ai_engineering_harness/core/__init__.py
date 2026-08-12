"""Módulo Core: Configuração, Detector, Manifesto e Contexto."""

from .config import (
    ConfigDocumentError,
    ConfigResolutionError,
    ConfigResolver,
    ConfigValidationError,
    EffectiveConfiguration,
)

__all__ = [
    "ConfigDocumentError",
    "ConfigResolutionError",
    "ConfigResolver",
    "ConfigValidationError",
    "EffectiveConfiguration",
]
