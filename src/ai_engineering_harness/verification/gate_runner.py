"""Deterministic execution of a fully resolved verification suite."""

from __future__ import annotations

from ai_engineering_harness.security import Redactor
from ai_engineering_harness.tools.adapters.terminal import (
    CommandRequest,
    TerminalAdapter,
    TerminalAdapterError,
    TerminalConfigurationError,
)
from ai_engineering_harness.verification.resolver import (
    ResolvedVerificationSuite,
    VerificationCommandResolver,
    VerificationConfigurationError,
    VerificationPrerequisiteError,
)
from ai_engineering_harness.verification.results import GateResult, VerificationSuiteResult
from ai_engineering_harness.workspace import ProvisionedWorktree


class GateRunner:
    """Resolve every prerequisite, then execute gates inside one validated worktree."""

    def __init__(self, worktree: ProvisionedWorktree):
        self.worktree = worktree
        self.resolver = VerificationCommandResolver(worktree)

    def resolve(self, active_gates: list[str]) -> ResolvedVerificationSuite:
        """Expose effect-free resolution through the engine-owned runner."""

        return self.resolver.resolve(active_gates)

    def run_applicable_gates(self, active_gates: list[str]) -> VerificationSuiteResult:
        """Execute only after the complete suite and executable policy are available."""

        suite = self.resolve(active_gates)
        try:
            adapter = self._adapter_for_suite(suite)
        except TerminalConfigurationError as exc:
            raise VerificationPrerequisiteError(
                "resolved verification executable policy is invalid"
            ) from exc

        results: list[GateResult] = []
        for command in suite.commands:
            try:
                term_res = adapter.execute(
                    CommandRequest(
                        argv=command.argv,
                        cwd=command.cwd,
                        timeout_seconds=30,
                        env_allowlist=tuple(self.resolver.environment),
                        max_output_bytes=1_000_000,
                    )
                )
                passed = not term_res.timed_out and term_res.exit_code == 0
                stdout = term_res.stdout
                stderr = term_res.stderr
            except TerminalConfigurationError as exc:
                raise VerificationPrerequisiteError(
                    "verification executable became unavailable before gate execution",
                    gate_id=command.gate_id,
                ) from exc
            except TerminalAdapterError as exc:
                passed = False
                stdout = ""
                stderr = Redactor.redact_text(str(exc))

            results.append(
                GateResult(
                    gate_type=command.gate_id,
                    command=" ".join(command.argv),
                    passed=passed,
                    stdout=stdout,
                    stderr=stderr,
                )
            )

        return VerificationSuiteResult(
            all_passed=all(result.passed for result in results),
            total_gates=len(results),
            passed_gates=sum(1 for result in results if result.passed),
            gate_results=results,
        )

    def _adapter_for_suite(self, suite: ResolvedVerificationSuite) -> TerminalAdapter:
        executables = {
            command.executable_alias: command.executable_path
            for command in suite.commands
        }
        return TerminalAdapter(
            path_guard=self.worktree.path_guard,
            executables=executables,
            environment=self.resolver.environment,
        )


__all__ = [
    "GateRunner",
    "VerificationConfigurationError",
    "VerificationPrerequisiteError",
]
