"""Configured, worktree-bound verification boundary."""

from .engine import VerificationEngine
from .resolver import (
    ResolvedGateCommand,
    ResolvedVerificationSuite,
    VerificationConfigurationError,
    VerificationPrerequisiteError,
)
from .results import GateRequirement, GateResult, GateStatus, VerificationSuiteResult

__all__ = [
    "GateRequirement",
    "GateResult",
    "GateStatus",
    "ResolvedGateCommand",
    "ResolvedVerificationSuite",
    "VerificationConfigurationError",
    "VerificationEngine",
    "VerificationPrerequisiteError",
    "VerificationSuiteResult",
]
