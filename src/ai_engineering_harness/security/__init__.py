"""Módulo de Segurança, Secrets e Fronteira de Confiança."""

from .path_guard import (
    GitMetadataPathError,
    GuardedPath,
    PathGuard,
    PathGuardConfigurationError,
    PathGuardError,
    PathOutsideRootError,
    PathResolutionError,
    PathSizeLimitError,
    PathTraversalError,
)
from .redaction import Redactor
from .secrets import SecretManager
from .trust import (
    SecretGrant,
    TrustAuthorization,
    TrustBoundaryConfigurationError,
    TrustBoundaryError,
    TrustBoundaryEvaluator,
    TrustCapabilityDeniedError,
    TrustEvaluationResult,
    TrustMode,
)

__all__ = [
    "GitMetadataPathError",
    "GuardedPath",
    "PathGuard",
    "PathGuardConfigurationError",
    "PathGuardError",
    "PathOutsideRootError",
    "PathResolutionError",
    "PathSizeLimitError",
    "PathTraversalError",
    "Redactor",
    "SecretGrant",
    "SecretManager",
    "TrustAuthorization",
    "TrustBoundaryConfigurationError",
    "TrustBoundaryError",
    "TrustBoundaryEvaluator",
    "TrustCapabilityDeniedError",
    "TrustEvaluationResult",
    "TrustMode",
]
