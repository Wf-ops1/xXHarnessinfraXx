"""Fail-closed Git revert for one canonically recorded promotion commit."""

from __future__ import annotations

import math
import os
import re
import subprocess
from collections.abc import Callable, Collection
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from ai_engineering_harness.contracts import ApprovalStatus
from ai_engineering_harness.contracts.execution import ExecutionId
from ai_engineering_harness.persistence import canonical_json_digest, canonical_json_object
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
_DANGEROUS_LOCAL_CONFIG = re.compile(
    r"^(?:merge\..+\.driver|filter\..+\.(?:clean|smudge|process)|core\.fsmonitor)$",
    re.IGNORECASE,
)
_NON_EMPTY = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
_DIGEST_PATTERN = r"^sha256:[0-9a-f]{64}$"
_SAFE_GIT_ENVIRONMENT_NAMES = (
    "COMSPEC",
    "ComSpec",
    "HOME",
    "HOMEDRIVE",
    "HOMEPATH",
    "PATH",
    "Path",
    "PATHEXT",
    "SystemRoot",
    "SYSTEMROOT",
    "TEMP",
    "TMP",
    "USERPROFILE",
    "WINDIR",
)
_SAFE_GIT_CONFIGURATION_VALUES = {
    "core.autocrlf": frozenset({"false", "input", "true"}),
    "core.eol": frozenset({"crlf", "lf", "native"}),
    "core.safecrlf": frozenset({"false", "true", "warn"}),
}
_GIT_BOOLEAN_ALIASES = {
    "0": "false",
    "1": "true",
    "no": "false",
    "off": "false",
    "on": "true",
    "yes": "true",
}


class RollbackError(RuntimeError):
    """Base error for canonical rollback."""


class RollbackConfigurationError(RollbackError, ValueError):
    """Rollback configuration cannot name one exact confined effect."""


class RollbackPrerequisiteError(RollbackError):
    """Rollback was refused before Git revert could begin."""


class RollbackCommandError(RollbackError):
    """A read-only rollback prerequisite command could not be observed safely."""


class RollbackHookApproval(BaseModel):
    """Durable human decision bound to one destructive rollback-hook attempt."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    approval_schema_version: Literal["1.0"] = "1.0"
    execution_id: ExecutionId
    hook_id: _NON_EMPTY
    rollback_attempt_id: _NON_EMPTY
    promotion_commit_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    reason: _NON_EMPTY
    requested_at: datetime
    expires_at: datetime
    status: ApprovalStatus
    approver_id: _NON_EMPTY | None
    decided_at: datetime | None
    comment: _NON_EMPTY | None
    subject_digest: str = Field(pattern=_DIGEST_PATTERN)

    @field_validator("requested_at", "expires_at", "decided_at")
    @classmethod
    def require_utc_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("rollback hook approval timestamps must use UTC")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def require_bound_decision(self) -> Self:
        if self.expires_at <= self.requested_at:
            raise ValueError("rollback hook approval expiration must follow its request")
        if self.subject_digest != self.calculate_subject_digest(
            execution_id=self.execution_id,
            hook_id=self.hook_id,
            rollback_attempt_id=self.rollback_attempt_id,
            promotion_commit_sha=self.promotion_commit_sha,
            reason=self.reason,
            requested_at=self.requested_at,
            expires_at=self.expires_at,
        ):
            raise ValueError("rollback hook approval subject digest diverges")
        if self.status is ApprovalStatus.PENDING:
            if any(value is not None for value in (self.approver_id, self.decided_at, self.comment)):
                raise ValueError("pending rollback hook approval cannot contain a decision")
            return self
        if self.status not in {
            ApprovalStatus.APPROVED,
            ApprovalStatus.EXPIRED,
            ApprovalStatus.INVALIDATED,
        }:
            raise ValueError("rollback hook approval status is unsupported")
        if self.decided_at is None or self.decided_at < self.requested_at:
            raise ValueError("rollback hook approval decision timestamp is invalid")
        if self.status is ApprovalStatus.APPROVED:
            if self.approver_id is None or self.decided_at >= self.expires_at:
                raise ValueError("approved rollback hook request needs a timely approver")
        elif self.approver_id is not None:
            raise ValueError("system rollback hook decisions cannot claim an approver")
        return self

    @classmethod
    def pending(
        cls,
        *,
        execution_id: str,
        hook_id: str,
        rollback_attempt_id: str,
        promotion_commit_sha: str,
        reason: str,
        requested_at: datetime,
        expires_at: datetime,
    ) -> RollbackHookApproval:
        subject_digest = cls.calculate_subject_digest(
            execution_id=execution_id,
            hook_id=hook_id,
            rollback_attempt_id=rollback_attempt_id,
            promotion_commit_sha=promotion_commit_sha,
            reason=reason,
            requested_at=requested_at,
            expires_at=expires_at,
        )
        return cls.model_validate(
            {
                "execution_id": execution_id,
                "hook_id": hook_id,
                "rollback_attempt_id": rollback_attempt_id,
                "promotion_commit_sha": promotion_commit_sha,
                "reason": reason,
                "requested_at": requested_at,
                "expires_at": expires_at,
                "status": ApprovalStatus.PENDING,
                "approver_id": None,
                "decided_at": None,
                "comment": None,
                "subject_digest": subject_digest,
            }
        )

    @staticmethod
    def calculate_subject_digest(
        *,
        execution_id: str,
        hook_id: str,
        rollback_attempt_id: str,
        promotion_commit_sha: str,
        reason: str,
        requested_at: datetime,
        expires_at: datetime,
    ) -> str:
        return canonical_json_digest(
            canonical_json_object(
                {
                    "execution_id": execution_id,
                    "expires_at": expires_at.astimezone(UTC).isoformat(),
                    "hook_id": hook_id,
                    "promotion_commit_sha": promotion_commit_sha,
                    "reason": reason,
                    "requested_at": requested_at.astimezone(UTC).isoformat(),
                    "rollback_attempt_id": rollback_attempt_id,
                }
            )
        )

    def approve(
        self,
        *,
        approver_id: str,
        decided_at: datetime,
        comment: str | None = None,
    ) -> RollbackHookApproval:
        if self.status is not ApprovalStatus.PENDING:
            raise RollbackConfigurationError("only a pending rollback hook request can be approved")
        return self._decision(
            status=ApprovalStatus.APPROVED,
            approver_id=approver_id,
            decided_at=decided_at,
            comment=comment,
        )

    def expire(self, *, decided_at: datetime) -> RollbackHookApproval:
        if self.status not in {ApprovalStatus.PENDING, ApprovalStatus.APPROVED}:
            raise RollbackConfigurationError("rollback hook request is not live")
        return self._decision(
            status=ApprovalStatus.EXPIRED,
            approver_id=None,
            decided_at=decided_at,
            comment="approval_expired",
        )

    def invalidate(self, *, decided_at: datetime, reason: str) -> RollbackHookApproval:
        if self.status not in {ApprovalStatus.PENDING, ApprovalStatus.APPROVED}:
            raise RollbackConfigurationError("rollback hook request is not live")
        return self._decision(
            status=ApprovalStatus.INVALIDATED,
            approver_id=None,
            decided_at=decided_at,
            comment=reason,
        )

    def _decision(
        self,
        *,
        status: ApprovalStatus,
        approver_id: str | None,
        decided_at: datetime,
        comment: str | None,
    ) -> RollbackHookApproval:
        document = self.model_dump(mode="python")
        document.update(
            {
                "status": status,
                "approver_id": approver_id,
                "decided_at": decided_at,
                "comment": comment,
            }
        )
        try:
            return RollbackHookApproval.model_validate(document)
        except ValueError as exc:
            raise RollbackConfigurationError("rollback hook approval decision is invalid") from exc


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
        clock: Callable[[], datetime] | None = None,
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
        self._clock = clock or (lambda: datetime.now(UTC))
        self._safe_effective_git_configuration: tuple[tuple[str, str], ...] | None = None

    @property
    def hook_id(self) -> str | None:
        return self._hook_id

    @property
    def hook_destructive(self) -> bool:
        return self._hook_destructive

    @property
    def has_compensation_hook(self) -> bool:
        return self._compensation_hook is not None

    def rollback(
        self,
        *,
        execution_id: str,
        rollback_attempt_id: str,
        promotion_commit_sha: str,
        original_branch: str,
        hook_approval: RollbackHookApproval | None = None,
    ) -> RollbackResult:
        """Run one non-interactive revert, abort conflicts, and never retry ambiguity."""

        commit_sha = self._validate_sha(promotion_commit_sha)
        branch = self._validate_branch(original_branch)
        safe_execution_id = self._validate_identity(execution_id, label="execution_id")
        safe_attempt_id = self._validate_identity(
            rollback_attempt_id,
            label="rollback_attempt_id",
        )
        self._authorize_hook(
            execution_id=safe_execution_id,
            rollback_attempt_id=safe_attempt_id,
            promotion_commit_sha=commit_sha,
            hook_approval=hook_approval,
        )
        self._deny_transitive_git_effects()
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

    def _authorize_hook(
        self,
        *,
        execution_id: str,
        rollback_attempt_id: str,
        promotion_commit_sha: str,
        hook_approval: RollbackHookApproval | None,
    ) -> None:
        if self._compensation_hook is None:
            if hook_approval is not None:
                raise RollbackPrerequisiteError(
                    "rollback hook approval was supplied without an injected hook"
                )
            return
        assert self._hook_id is not None
        approval_granted = False
        if self._hook_destructive:
            if not isinstance(hook_approval, RollbackHookApproval):
                raise RollbackPrerequisiteError(
                    "destructive compensation hook requires a bound approval"
                )
            now = self._clock()
            if now.tzinfo is None or now.utcoffset() != timedelta(0):
                raise RollbackConfigurationError("rollback manager clock must use UTC")
            if (
                hook_approval.status is not ApprovalStatus.APPROVED
                or hook_approval.execution_id != execution_id
                or hook_approval.hook_id != self._hook_id
                or hook_approval.rollback_attempt_id != rollback_attempt_id
                or hook_approval.promotion_commit_sha != promotion_commit_sha
                or now >= hook_approval.expires_at
            ):
                raise RollbackPrerequisiteError(
                    "destructive compensation hook approval does not match this attempt"
                )
            approval_granted = True
        elif hook_approval is not None:
            raise RollbackPrerequisiteError(
                "non-destructive compensation hook does not accept a destructive approval"
            )
        if not self.trust_boundary.validate_hook(
            self._hook_id,
            destructive=self._hook_destructive,
            approval_granted=approval_granted,
        ):
            raise RollbackPrerequisiteError(
                "compensation hook is not explicitly authorized"
            )

    def _deny_transitive_git_effects(self) -> None:
        configured = self._run_git(
            (
                "config",
                "--local",
                "--includes",
                "--get-regexp",
                ".*",
            ),
            allowed_returncodes=(0, 1),
        )
        dangerous: set[str] = set()
        for line in configured.stdout.splitlines():
            name, separator, value = line.strip().partition(" ")
            if _DANGEROUS_LOCAL_CONFIG.fullmatch(name) is None:
                continue
            normalized_value = _GIT_BOOLEAN_ALIASES.get(
                value.strip().casefold(),
                value.strip().casefold(),
            )
            if name.casefold() == "core.fsmonitor" and separator and normalized_value == "false":
                continue
            dangerous.add(name)
        if dangerous:
            raise RollbackPrerequisiteError(
                "repository Git configuration enables an external driver or filter"
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
            ("diff", "--no-ext-diff", "--name-only", "--diff-filter=U", "--"),
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
            base_environment = self._safe_git_environment()
            inherited_configuration = self._discover_safe_git_configuration(
                base_environment
            )
            configuration = (
                ("core.hooksPath", os.devnull),
                ("commit.gpgSign", "false"),
                ("tag.gpgSign", "false"),
                ("core.fsmonitor", "false"),
                ("core.attributesFile", os.devnull),
                *inherited_configuration,
            )
            git_environment = {
                **base_environment,
                "GIT_ATTR_NOSYSTEM": "1",
                "GIT_AUTHOR_EMAIL": "harness@localhost",
                "GIT_AUTHOR_NAME": "AI Engineering Harness",
                "GIT_COMMITTER_EMAIL": "harness@localhost",
                "GIT_COMMITTER_NAME": "AI Engineering Harness",
                "GIT_CONFIG_COUNT": str(len(configuration)),
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_EDITOR": "true",
                "GIT_MERGE_AUTOEDIT": "no",
                "GIT_PAGER": "true",
                "GIT_SEQUENCE_EDITOR": "true",
                "GIT_TERMINAL_PROMPT": "0",
            }
            for index, (key, value) in enumerate(configuration):
                git_environment[f"GIT_CONFIG_KEY_{index}"] = key
                git_environment[f"GIT_CONFIG_VALUE_{index}"] = value
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
                env=git_environment,
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

    def _discover_safe_git_configuration(
        self,
        environment: dict[str, str],
    ) -> tuple[tuple[str, str], ...]:
        cached = self._safe_effective_git_configuration
        if cached is not None:
            return cached
        selected: list[tuple[str, str]] = []
        discovery_environment = {
            **environment,
            "GIT_PAGER": "true",
            "GIT_TERMINAL_PROMPT": "0",
        }
        for key, allowed_values in _SAFE_GIT_CONFIGURATION_VALUES.items():
            try:
                result = subprocess.run(
                    (self.git_executable, "config", "--includes", "--get", key),
                    cwd=self.project_root,
                    check=False,
                    shell=False,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=self.command_timeout_seconds,
                    env=discovery_environment,
                )
            except FileNotFoundError as exc:
                raise RollbackCommandError(
                    "configured Git executable was not found"
                ) from exc
            except subprocess.TimeoutExpired as exc:
                raise RollbackCommandError(
                    "Git configuration discovery timed out"
                ) from exc
            except OSError as exc:
                raise RollbackCommandError(
                    "Git configuration discovery could not start"
                ) from exc
            if result.returncode == 1:
                continue
            if result.returncode != 0:
                raise RollbackCommandError(
                    "Git configuration discovery could not be proven"
                )
            value = result.stdout.strip().casefold()
            value = _GIT_BOOLEAN_ALIASES.get(value, value)
            if value not in allowed_values:
                raise RollbackPrerequisiteError(
                    f"effective Git configuration {key!r} is not canonical"
                )
            selected.append((key, value))
        discovered = tuple(selected)
        self._safe_effective_git_configuration = discovered
        return discovered

    @staticmethod
    def _safe_git_environment() -> dict[str, str]:
        selected: dict[str, str] = {}
        available = {name.casefold(): (name, value) for name, value in os.environ.items()}
        for requested in _SAFE_GIT_ENVIRONMENT_NAMES:
            current = available.get(requested.casefold())
            if current is not None:
                selected[current[0]] = current[1]
        return selected

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

    @staticmethod
    def _validate_identity(value: object, *, label: str) -> str:
        if (
            type(value) is not str
            or not value.strip()
            or value != value.strip()
            or "\x00" in value
            or "\r" in value
            or "\n" in value
        ):
            raise RollbackConfigurationError(f"{label} must be canonical text")
        return value


__all__ = [
    "RollbackCommandError",
    "RollbackConfigurationError",
    "RollbackError",
    "RollbackHookApproval",
    "RollbackManager",
    "RollbackPrerequisiteError",
    "RollbackResult",
]
