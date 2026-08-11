"""Deterministic execution of a fully resolved verification suite."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from ai_engineering_harness.security import Redactor
from ai_engineering_harness.tools.adapters.terminal import (
    CommandRequest,
    TerminalAdapter,
    TerminalAdapterError,
    TerminalConfigurationError,
)
from ai_engineering_harness.verification.resolver import (
    ResolvedGateCommand,
    ResolvedVerificationSuite,
    VerificationCommandResolver,
    VerificationConfigurationError,
    VerificationPrerequisiteError,
)
from ai_engineering_harness.verification.results import (
    GateRequirement,
    GateResult,
    GateStatus,
    VerificationSuiteResult,
)
from ai_engineering_harness.workspace import ProvisionedWorktree


class GateRunner:
    """Resolve every prerequisite, then execute gates inside one validated worktree."""

    def __init__(
        self,
        worktree: ProvisionedWorktree,
        *,
        clock: Callable[[], datetime] | None = None,
    ):
        self.worktree = worktree
        self.resolver = VerificationCommandResolver(worktree)
        self._clock = clock or (lambda: datetime.now(UTC))

    def resolve(self, active_gates: list[str]) -> ResolvedVerificationSuite:
        """Expose effect-free resolution through the engine-owned runner."""

        return self.resolver.resolve(active_gates)

    def resolve_requirements(
        self,
        requirements: tuple[GateRequirement, ...],
    ) -> ResolvedVerificationSuite:
        """Resolve one policy-derived suite without terminal effects."""

        return self.resolver.resolve_requirements(requirements)

    def run_applicable_gates(self, active_gates: list[str]) -> VerificationSuiteResult:
        """Execute only after the complete suite and executable policy are available."""

        suite = self.resolve(active_gates)
        return self.run_resolved_suite(suite)

    def run_requirements(
        self,
        requirements: tuple[GateRequirement, ...],
        *,
        before_gate: Callable[
            [GateRequirement, ResolvedGateCommand | None], None
        ]
        | None = None,
        after_gate: Callable[[GateResult], None] | None = None,
    ) -> VerificationSuiteResult:
        """Resolve every prerequisite, then emit durable-observer boundaries."""

        suite = self.resolve_requirements(requirements)
        return self.run_resolved_suite(
            suite,
            before_gate=before_gate,
            after_gate=after_gate,
        )

    def run_resolved_suite(
        self,
        suite: ResolvedVerificationSuite,
        *,
        before_gate: Callable[
            [GateRequirement, ResolvedGateCommand | None], None
        ]
        | None = None,
        after_gate: Callable[[GateResult], None] | None = None,
    ) -> VerificationSuiteResult:
        """Execute an immutable suite that was completely resolved first."""

        if not isinstance(suite, ResolvedVerificationSuite):
            raise TypeError("suite must be a ResolvedVerificationSuite")
        try:
            adapter = self._adapter_for_suite(suite)
        except TerminalConfigurationError as exc:
            raise VerificationPrerequisiteError(
                "resolved verification executable policy is invalid"
            ) from exc

        verified_commit_sha = self.worktree.reference.worktree_head_sha
        if verified_commit_sha is None:
            raise VerificationPrerequisiteError(
                "verification worktree is missing its validated commit"
            )
        commands_by_gate = {command.gate_id: command for command in suite.commands}
        results: list[GateResult] = []
        for requirement in suite.requirements:
            command = commands_by_gate.get(requirement.gate_id)
            if before_gate is not None:
                before_gate(requirement, command)
            started_at = self._clock()
            if command is None:
                finished_at = started_at
                result = GateResult(
                    gate_id=requirement.gate_id,
                    status=GateStatus.SKIPPED_NOT_APPLICABLE,
                    required=requirement.required,
                    argv=(),
                    cwd=".",
                    started_at=started_at,
                    finished_at=finished_at,
                    duration_ms=0,
                    exit_code=None,
                    stdout="",
                    stderr="",
                    verified_commit_sha=verified_commit_sha,
                )
                results.append(result)
                if after_gate is not None:
                    after_gate(result)
                continue
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
                if term_res.timed_out:
                    status = GateStatus.ERROR
                elif term_res.exit_code == 0:
                    status = GateStatus.PASSED
                else:
                    status = GateStatus.FAILED
                exit_code: int | None = term_res.exit_code
                stdout = term_res.stdout
                stderr = term_res.stderr
            except TerminalConfigurationError as exc:
                raise VerificationPrerequisiteError(
                    "verification executable became unavailable before gate execution",
                    gate_id=command.gate_id,
                ) from exc
            except TerminalAdapterError as exc:
                status = GateStatus.ERROR
                exit_code = None
                stdout = ""
                stderr = Redactor.redact_text(str(exc))

            finished_at = self._clock()
            result = GateResult(
                gate_id=command.gate_id,
                status=status,
                required=requirement.required,
                argv=command.argv,
                cwd=command.cwd,
                started_at=started_at,
                finished_at=finished_at,
                duration_ms=int((finished_at - started_at).total_seconds() * 1000),
                exit_code=exit_code,
                stdout=stdout,
                stderr=stderr,
                verified_commit_sha=verified_commit_sha,
            )
            results.append(result)
            if after_gate is not None:
                after_gate(result)

        return VerificationSuiteResult(
            verified_commit_sha=verified_commit_sha,
            gate_results=tuple(results),
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
