"""Canonical gate selection over commands detected from project configuration."""

from __future__ import annotations

from ai_engineering_harness.contracts.policies import (
    CANONICAL_VERIFICATION_GATE_IDS,
    VerificationGateId,
)
from ai_engineering_harness.core.detector import DetectedCommand, DetectedStack


class VerificationEvaluator:
    """Select configured commands without maintaining a parallel language map."""

    @classmethod
    def canonical_gate_ids(cls) -> tuple[VerificationGateId, ...]:
        """Return the shared ordered gate-id vocabulary."""

        return CANONICAL_VERIFICATION_GATE_IDS

    @classmethod
    def is_canonical_gate_id(cls, gate_type: object) -> bool:
        """Return whether one exact value is a canonical verification gate id."""

        return type(gate_type) is str and gate_type in CANONICAL_VERIFICATION_GATE_IDS

    @classmethod
    def configured_command(
        cls,
        stack: DetectedStack,
        gate_type: str,
    ) -> DetectedCommand | None:
        """Return the single command evidenced by the detected configuration."""

        if not cls.is_canonical_gate_id(gate_type):
            return None
        matches = tuple(command for command in stack.commands if command.gate_id == gate_type)
        if len(matches) > 1:
            raise ValueError(f"detected stack contains duplicate command for gate {gate_type!r}")
        return matches[0] if matches else None


__all__ = ["VerificationEvaluator"]
