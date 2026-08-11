"""Worktree-bound verification engine."""

from collections.abc import Callable
from datetime import datetime

from ai_engineering_harness.verification.gate_runner import GateRunner
from ai_engineering_harness.verification.resolver import (
    ResolvedGateCommand,
    ResolvedVerificationSuite,
)
from ai_engineering_harness.verification.results import (
    GateRequirement,
    GateResult,
    VerificationSuiteResult,
)
from ai_engineering_harness.workspace import ProvisionedWorktree


class VerificationEngine:
    """Own the only F4.6 command-resolution and execution boundary."""

    def __init__(
        self,
        worktree: ProvisionedWorktree,
        *,
        clock: Callable[[], datetime] | None = None,
    ):
        self.worktree = worktree
        self.runner = GateRunner(worktree, clock=clock)

    def resolve(self, active_gates: list[str]) -> ResolvedVerificationSuite:
        """Resolve configured argv and prerequisites without executing a gate."""

        return self.runner.resolve(active_gates)

    def verify(self, active_gates: list[str]) -> VerificationSuiteResult:
        """Resolve the entire suite, then execute it in the validated worktree."""

        return self.runner.run_applicable_gates(active_gates)

    def verify_requirements(
        self,
        requirements: tuple[GateRequirement, ...],
        *,
        before_gate: Callable[
            [GateRequirement, ResolvedGateCommand | None], None
        ]
        | None = None,
        after_gate: Callable[[GateResult], None] | None = None,
    ) -> VerificationSuiteResult:
        """Execute the policy-derived suite through observer persistence boundaries."""

        return self.runner.run_requirements(
            requirements,
            before_gate=before_gate,
            after_gate=after_gate,
        )


__all__ = ["VerificationEngine"]
