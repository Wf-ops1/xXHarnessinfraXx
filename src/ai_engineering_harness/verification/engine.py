"""Worktree-bound verification engine."""

from ai_engineering_harness.verification.gate_runner import GateRunner
from ai_engineering_harness.verification.resolver import ResolvedVerificationSuite
from ai_engineering_harness.verification.results import VerificationSuiteResult
from ai_engineering_harness.workspace import ProvisionedWorktree


class VerificationEngine:
    """Own the only F4.6 command-resolution and execution boundary."""

    def __init__(self, worktree: ProvisionedWorktree):
        self.runner = GateRunner(worktree)

    def resolve(self, active_gates: list[str]) -> ResolvedVerificationSuite:
        """Resolve configured argv and prerequisites without executing a gate."""

        return self.runner.resolve(active_gates)

    def verify(self, active_gates: list[str]) -> VerificationSuiteResult:
        """Resolve the entire suite, then execute it in the validated worktree."""

        return self.runner.run_applicable_gates(active_gates)


__all__ = ["VerificationEngine"]
