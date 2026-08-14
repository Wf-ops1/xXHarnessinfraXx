"""Fail-closed Git revert for one canonically recorded promotion commit."""

from __future__ import annotations

import math
import os
import re
import subprocess
from collections.abc import Callable, Collection
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

from ai_engineering_harness.security import (
    Redactor,
    TrustAuthorization,
    TrustBoundaryConfigurationError,
    TrustBoundaryEvaluator,
    TrustCapabilityDeniedError,
    TrustEvaluationResult,
)

_FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
_MAX_EVIDENCE_CHARACTERS = 8_000


class RollbackError(RuntimeError):
    """Base error for canonical rollback."""


class RollbackConfigurationError(RollbackError, ValueError):
    """Rollback configuration cannot name one exact confined effect."""


class RollbackPrerequisiteError(RollbackError):
    """Rollback was refused before Git revert could begin."""


class RollbackCommandError(RollbackError):
    """A read-only rollback prerequisite command could not be observed safely."""


@dataclass(frozen=True, slots=True)
class RollbackResult:
    """Redacted evidence for a compensated or safely blocked rollback."""

    promotion_commit_sha: str
    previous_head_sha: str
    rollback_commit_sha: str | None
    original_branch: str
    outcome: Literal["compensated", "blocked"]
    exit_code: int | None
    stdout: str
    stderr: str
    conflicting_paths: tuple[str, ...]
    abort_attempted: bool
    abort_succeeded: bool
    restored_after_abort: bool
    hook_executed: bool
    reason: str

    @property
    def compensated(self) -> bool:
        return self.outcome == "compensated"


class RollbackManager:
    """Revert exactly one recorded promotion and prove the observed Git outcome."""

    def __init__(
        self,
        project_root: Path,
        *,
        git_executable: str = "git",
        command_timeout_seconds: float = 30.0,
        trust_boundary: TrustEvaluationResult | None = None,
        compensation_hook: Callable[[RollbackResult], None] | None = None,
        hook_id: str | None = None,
        hook_destructive: bool = False,
    ) -> None:
        try:
            root = Path(project_root).resolve(strict=True)
        except (OSError, RuntimeError, ValueError) as exc:
            raise RollbackConfigurationError(
                "project_root must resolve to an existing directory"
            ) from exc
        if not root.is_dir():
            raise RollbackConfigurationError("project_root must be a directory")
        if type(git_executable) is not str or not git_executable.strip():
            raise RollbackConfigurationError("git_executable must be canonical text")
        if (
            isinstance(command_timeout_seconds, bool)
            or not isinstance(command_timeout_seconds, (int, float))
            or not math.isfinite(command_timeout_seconds)
            or command_timeout_seconds <= 0
        ):
            raise RollbackConfigurationError(
                "command_timeout_seconds must be a positive finite number"
            )
        if compensation_hook is None:
            if hook_id is not None or hook_destructive:
                raise RollbackConfigurationError(
                    "hook metadata requires an explicitly injected compensation hook"
                )
        elif (
            not callable(compensation_hook)
            or type(hook_id) is not str
            or not hook_id.strip()
            or hook_id != hook_id.strip()
        ):
            raise RollbackConfigurationError(
                "an injected compensation hook requires one canonical hook_id"
            )
        boundary = trust_boundary
        if boundary is None:
            boundary = TrustBoundaryEvaluator(
                root,
                authorization=TrustAuthorization(
                    repository_root=os.fspath(root),
                    executable_aliases=(git_executable,),
                ),
            ).evaluate()
        if not isinstance(boundary, TrustEvaluationResult):
            raise RollbackConfigurationError(
                "trust_boundary must be a TrustEvaluationResult"
            )
        try:
            boundary.require_root(root)
        except (TrustBoundaryConfigurationError, TrustCapabilityDeniedError) as exc:
            raise RollbackConfigurationError(
                "trust boundary must authorize the exact rollback root"
            ) from exc
        if Path(boundary.repository_root) != root:
            raise RollbackConfigurationError(
                "trust boundary belongs to another repository root"
            )
        self.project_root = root
        self.git_executable = git_executable
        self.command_timeout_seconds = float(command_timeout_seconds)
        self.trust_boundary = boundary
        self._compensation_hook = compensation_hook
        self._hook_id = hook_id
        self._hook_destructive = hook_destructive

    def rollback(
        self,
        *,
        promotion_commit_sha: str,
        original_branch: str,
        hook_approval_granted: bool = False,
    ) -> RollbackResult:
        """Run one non-interactive revert, abort conflicts, and never retry ambiguity."""

        commit_sha = self._validate_sha(promotion_commit_sha)
        branch = self._validate_branch(original_branch)
        self._authorize_hook(hook_approval_granted=hook_approval_granted)
        observed_branch, previous_head, status = self._original_identity()
        if observed_branch != branch:
            raise RollbackPrerequisiteError(
                "original branch does not match the execution record"
            )
        if status:
            raise RollbackPrerequisiteError(
                "original checkout must be clean before rollback"
            )
        ancestor = self._run_git(
            ("merge-base", "--is-ancestor", commit_sha, previous_head),
            allowed_returncodes=(0, 1),
        )
        if ancestor.returncode != 0:
            raise RollbackPrerequisiteError(
                "promotion commit is not an ancestor of the current original HEAD"
            )

        try:
            reverted = self._run_git(
                ("revert", "--no-edit", commit_sha),
                allowed_returncodes=(0, 1, 128),
            )
        except RollbackCommandError as exc:
            return self._reconcile_failed_effect(
                promotion_commit_sha=commit_sha,
                original_branch=branch,
                previous_head=previous_head,
                exit_code=None,
                stdout="",
                stderr=str(exc),
                reason="git_revert_outcome_ambiguous",
            )
        stdout = self._safe_evidence(reverted.stdout)
        stderr = self._safe_evidence(reverted.stderr)
        if reverted.returncode != 0:
            return self._reconcile_failed_effect(
                promotion_commit_sha=commit_sha,
                original_branch=branch,
                previous_head=previous_head,
                exit_code=reverted.returncode,
                stdout=stdout,
                stderr=stderr,
                reason="git_revert_failed",
            )

        try:
            observed_branch, rollback_sha, status = self._original_identity()
            parent = self._run_git(
                ("rev-parse", "--verify", f"{rollback_sha}^"),
            ).stdout.strip().lower()
        except RollbackError as exc:
            return RollbackResult(
                promotion_commit_sha=commit_sha,
                previous_head_sha=previous_head,
                rollback_commit_sha=None,
                original_branch=branch,
                outcome="blocked",
                exit_code=reverted.returncode,
                stdout=stdout,
                stderr=self._safe_evidence(str(exc)),
                conflicting_paths=(),
                abort_attempted=False,
                abort_succeeded=False,
                restored_after_abort=False,
                hook_executed=False,
                reason="git_revert_success_could_not_be_proven",
            )
        if (
            observed_branch != branch
            or rollback_sha == previous_head
            or _FULL_SHA.fullmatch(rollback_sha) is None
            or parent != previous_head
            or status
        ):
            return RollbackResult(
                promotion_commit_sha=commit_sha,
                previous_head_sha=previous_head,
                rollback_commit_sha=rollback_sha,
                original_branch=branch,
                outcome="blocked",
                exit_code=reverted.returncode,
                stdout=stdout,
                stderr=stderr,
                conflicting_paths=(),
                abort_attempted=False,
                abort_succeeded=False,
                restored_after_abort=False,
                hook_executed=False,
                reason="git_revert_success_could_not_be_proven",
            )
        result = RollbackResult(
            promotion_commit_sha=commit_sha,
            previous_head_sha=previous_head,
            rollback_commit_sha=rollback_sha,
            original_branch=branch,
            outcome="compensated",
            exit_code=reverted.returncode,
            stdout=stdout,
            stderr=stderr,
            conflicting_paths=(),
            abort_attempted=False,
            abort_succeeded=False,
            restored_after_abort=False,
            hook_executed=False,
            reason="git_revert_verified",
        )
        if self._compensation_hook is not None:
            try:
                self._compensation_hook(result)
            except Exception:  # noqa: BLE001 - injected hooks are an external effect boundary
                return replace(
                    result,
                    outcome="blocked",
                    reason="compensation_hook_failed",
                )
            result = replace(result, hook_executed=True)
        return result

    def _reconcile_failed_effect(
        self,
        *,
        promotion_commit_sha: str,
        original_branch: str,
        previous_head: str,
        exit_code: int | None,
        stdout: str,
        stderr: str,
        reason: str,
    ) -> RollbackResult:
        conflicts = self._conflicting_paths()
        revert_in_progress = self._run_git(
            ("rev-parse", "--verify", "--quiet", "REVERT_HEAD"),
            allowed_returncodes=(0, 1),
        ).returncode == 0
        abort_attempted = revert_in_progress or bool(conflicts)
        abort_succeeded = False
        if abort_attempted:
            aborted = self._run_git(
                ("revert", "--abort"),
                allowed_returncodes=(0, 128),
            )
            abort_succeeded = aborted.returncode == 0
        observed_branch, observed_head, status = self._original_identity(
            require_clean=False
        )
        restored = (
            abort_attempted
            and abort_succeeded
            and observed_branch == original_branch
            and observed_head == previous_head
            and not status
        )
        return RollbackResult(
            promotion_commit_sha=promotion_commit_sha,
            previous_head_sha=previous_head,
            rollback_commit_sha=None,
            original_branch=original_branch,
            outcome="blocked",
            exit_code=exit_code,
            stdout=self._safe_evidence(stdout),
            stderr=self._safe_evidence(stderr),
            conflicting_paths=conflicts,
            abort_attempted=abort_attempted,
            abort_succeeded=abort_succeeded,
            restored_after_abort=restored,
            hook_executed=False,
            reason=reason if not restored else "git_revert_aborted_after_conflict",
        )

    def _authorize_hook(self, *, hook_approval_granted: bool) -> None:
        if self._compensation_hook is None:
            return
        assert self._hook_id is not None
        if not self.trust_boundary.validate_hook(
            self._hook_id,
            destructive=self._hook_destructive,
            approval_granted=hook_approval_granted,
        ):
            raise RollbackPrerequisiteError(
                "compensation hook is not explicitly authorized"
            )

    def _original_identity(self, *, require_clean: bool = True) -> tuple[str, str, str]:
        root = self._run_git(("rev-parse", "--show-toplevel")).stdout.strip()
        try:
            resolved_root = Path(root).resolve(strict=True)
        except (OSError, RuntimeError, ValueError) as exc:
            raise RollbackPrerequisiteError(
                "original Git root cannot be resolved"
            ) from exc
        if resolved_root != self.project_root:
            raise RollbackPrerequisiteError(
                "project_root is not the exact original Git root"
            )
        branch_result = self._run_git(
            ("symbolic-ref", "--quiet", "--short", "HEAD"),
            allowed_returncodes=(0, 1),
        )
        if branch_result.returncode != 0:
            raise RollbackPrerequisiteError("original checkout is detached")
        head = self._run_git(
            ("rev-parse", "--verify", "HEAD^{commit}"),
        ).stdout.strip().lower()
        if _FULL_SHA.fullmatch(head) is None:
            raise RollbackPrerequisiteError("original HEAD is not a full commit SHA")
        status = self._run_git(
            ("status", "--porcelain=v1", "--untracked-files=all"),
        ).stdout.strip()
        if require_clean and status:
            raise RollbackPrerequisiteError("original checkout is not clean")
        return branch_result.stdout.strip(), head, status

    def _conflicting_paths(self) -> tuple[str, ...]:
        output = self._run_git(
            ("diff", "--name-only", "--diff-filter=U", "--"),
        ).stdout
        return tuple(
            sorted(
                {
                    self._safe_evidence(line.strip())
                    for line in output.splitlines()
                    if line.strip()
                }
            )
        )

    def _run_git(
        self,
        arguments: Collection[str],
        *,
        allowed_returncodes: Collection[int] = (0,),
    ) -> subprocess.CompletedProcess[str]:
        try:
            self.trust_boundary.require_root(self.project_root)
            self.trust_boundary.require_executable(self.git_executable)
        except (TrustBoundaryConfigurationError, TrustCapabilityDeniedError) as exc:
            raise RollbackPrerequisiteError(
                "Git is not allowed by the exact rollback trust boundary"
            ) from exc
        try:
            result = subprocess.run(
                (self.git_executable, *arguments),
                cwd=self.project_root,
                check=False,
                shell=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.command_timeout_seconds,
                env={
                    **os.environ,
                    "GIT_CONFIG_COUNT": "2",
                    "GIT_CONFIG_KEY_0": "core.hooksPath",
                    "GIT_CONFIG_KEY_1": "commit.gpgSign",
                    "GIT_CONFIG_VALUE_0": os.devnull,
                    "GIT_CONFIG_VALUE_1": "false",
                    "GIT_TERMINAL_PROMPT": "0",
                },
            )
        except FileNotFoundError as exc:
            raise RollbackCommandError("configured Git executable was not found") from exc
        except subprocess.TimeoutExpired as exc:
            raise RollbackCommandError("Git rollback command timed out") from exc
        except OSError as exc:
            raise RollbackCommandError("Git rollback command could not start") from exc
        if result.returncode not in allowed_returncodes:
            operation = " ".join(tuple(arguments)[:2])
            raise RollbackCommandError(
                f"Git operation {operation!r} failed with exit code {result.returncode}"
            )
        return result

    @staticmethod
    def _safe_evidence(value: str) -> str:
        return Redactor.redact_text(value)[:_MAX_EVIDENCE_CHARACTERS]

    @staticmethod
    def _validate_sha(value: object) -> str:
        if type(value) is not str or _FULL_SHA.fullmatch(value) is None:
            raise RollbackConfigurationError(
                "promotion_commit_sha must be a full lowercase SHA"
            )
        return value

    @staticmethod
    def _validate_branch(value: object) -> str:
        if (
            type(value) is not str
            or not value.strip()
            or value != value.strip()
            or "\x00" in value
            or "\r" in value
            or "\n" in value
        ):
            raise RollbackConfigurationError("original_branch must be canonical text")
        return value


__all__ = [
    "RollbackCommandError",
    "RollbackConfigurationError",
    "RollbackError",
    "RollbackManager",
    "RollbackPrerequisiteError",
    "RollbackResult",
]
