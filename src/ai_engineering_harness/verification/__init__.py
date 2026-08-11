"""Configured, worktree-bound verification boundary."""

from .engine import VerificationEngine
from .resolver import (
    ResolvedGateCommand,
    ResolvedVerificationSuite,
    VerificationConfigurationError,
    VerificationPrerequisiteError,
)

__all__ = [
    "ResolvedGateCommand",
    "ResolvedVerificationSuite",
    "VerificationConfigurationError",
    "VerificationEngine",
    "VerificationPrerequisiteError",
]
