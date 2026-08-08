"""Provision and validate external Git worktrees without touching product files."""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from collections.abc import Collection
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any, ClassVar

from ai_engineering_harness.security import PathGuard
from ai_engineering_harness.workspace.sandbox import SandboxProvider


class WorktreeError(RuntimeError):
    """Base error for external worktree lifecycle failures."""


class WorktreeConfigurationError(WorktreeError):
    """Raised when manager inputs cannot identify a safe workspace."""


class GitUnavailableError(WorktreeError):
    """Raised when the configured Git executable cannot be started."""


class InvalidGitRepositoryError(WorktreeError):
    """Raised when ``project_root`` is not the exact root of a Git worktree."""


class DirtyRepositoryError(WorktreeError):
    """Raised when the original checkout contains tracked or untracked changes."""


class DetachedHeadError(WorktreeError):
    """Raised when the original checkout is not attached to a branch."""


class BaseCommitMismatchError(WorktreeError):
    """Raised when an expected base SHA differs from the repository HEAD."""


class WorktreeCollisionError(WorktreeError):
    """Raised when a path, branch, or durable reference already exists."""


class GitCommandError(WorktreeError):
    """Raised when a bounded Git argv command fails."""


class WorktreeValidationError(WorktreeError):
    """Raised when Git state does not match the durable worktree reference."""


class WorktreeReferenceError(WorktreeError):
    """Raised when durable worktree state is missing, invalid, or cannot be written."""


class WorktreeCleanupError(WorktreeError):
    """Raised when an explicit, non-forced cleanup cannot complete safely."""


class DirtyWorktreeError(WorktreeCleanupError):
    """Raised when cleanup would discard changes from the external worktree."""


class WorktreeStatus(str, Enum):
    """Durable lifecycle states for one external worktree."""

    CREATING = "CREATING"
    ACTIVE = "ACTIVE"
    FAILED = "FAILED"
    CLEANUP_PENDING = "CLEANUP_PENDING"
    REMOVED = "REMOVED"


@dataclass(frozen=True, slots=True)
class WorktreeReference:
    """Strict durable identity for one provisioned worktree."""

    SCHEMA_VERSION: ClassVar[str] = "1.0"
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema_version",
            "execution_id",
            "project_id",
            "project_root",
            "worktree_path",
            "base_commit_sha",
            "original_branch",
            "worktree_branch",
            "worktree_head_sha",
            "status",
            "failure_code",
            "created_at",
            "updated_at",
        }
    )

    execution_id: str
    project_id: str
    project_root: Path
    worktree_path: Path
    base_commit_sha: str
    original_branch: str
    worktree_branch: str
    worktree_head_sha: str | None
    status: WorktreeStatus
    failure_code: str | None
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, str | None]:
        """Return the canonical JSON-compatible representation."""

        return {
            "schema_version": self.SCHEMA_VERSION,
            "execution_id": self.execution_id,
            "project_id": self.project_id,
            "project_root": str(self.project_root),
            "worktree_path": str(self.worktree_path),
            "base_commit_sha": self.base_commit_sha,
            "original_branch": self.original_branch,
            "worktree_branch": self.worktree_branch,
            "worktree_head_sha": self.worktree_head_sha,
            "status": self.status.value,
            "failure_code": self.failure_code,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, payload: object) -> WorktreeReference:
        """Parse a reference without accepting missing, extra, or coerced fields."""

        if not isinstance(payload, dict) or set(payload) != cls._FIELDS:
            raise WorktreeReferenceError("worktree reference fields do not match schema 1.0")
        if payload.get("schema_version") != cls.SCHEMA_VERSION:
            raise WorktreeReferenceError("unsupported worktree reference schema")

        required_strings = (
            "execution_id",
            "project_id",
            "project_root",
            "worktree_path",
            "base_commit_sha",
            "original_branch",
            "worktree_branch",
            "status",
            "created_at",
            "updated_at",
        )
        if any(type(payload.get(field)) is not str or not payload[field] for field in required_strings):
            raise WorktreeReferenceError("worktree reference contains an invalid string field")
        if payload.get("worktree_head_sha") is not None and type(payload["worktree_head_sha"]) is not str:
            raise WorktreeReferenceError("worktree_head_sha must be a string or null")
        if payload.get("failure_code") is not None and type(payload["failure_code"]) is not str:
            raise WorktreeReferenceError("failure_code must be a string or null")

        try:
            status = WorktreeStatus(payload["status"])
        except ValueError as exc:
            raise WorktreeReferenceError("worktree reference contains an invalid status") from exc

        return cls(
            execution_id=payload["execution_id"],
            project_id=payload["project_id"],
            project_root=Path(payload["project_root"]),
            worktree_path=Path(payload["worktree_path"]),
            base_commit_sha=payload["base_commit_sha"],
            original_branch=payload["original_branch"],
            worktree_branch=payload["worktree_branch"],
            worktree_head_sha=payload["worktree_head_sha"],
            status=status,
            failure_code=payload["failure_code"],
            created_at=payload["created_at"],
            updated_at=payload["updated_at"],
        )


@dataclass(frozen=True, slots=True)
class ProvisionedWorktree:
    """Validated worktree identity plus its canonical path guard."""

    reference: WorktreeReference
    path_guard: PathGuard

    @property
    def worktree_path(self) -> Path:
        """Return the canonical external worktree root."""

        return self.reference.worktree_path


@dataclass(frozen=True, slots=True)
class _RepositorySnapshot:
    root: Path
    head_sha: str
    branch: str


class ExternalWorktreeManager:
    """Create, reopen, and explicitly remove real external Git worktrees."""

    _IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
    _FULL_SHA = re.compile(r"^[0-9a-f]{40}$")

    def __init__(
        self,
        project_root: str | os.PathLike[str],
        project_id: str = "default-proj",
        *,
        external_base_dir: str | os.PathLike[str] | None = None,
        git_executable: str = "git",
        command_timeout_seconds: float = 30.0,
    ) -> None:
        self.project_root = self._existing_directory(project_root, label="project_root")
        self.project_id = self._validate_identifier("project_id", project_id)
        self._configured_external_base = external_base_dir
        if type(git_executable) is not str or not git_executable.strip():
            raise WorktreeConfigurationError("git_executable must be a non-empty string")
        if isinstance(command_timeout_seconds, bool) or not isinstance(command_timeout_seconds, (int, float)):
            raise WorktreeConfigurationError("command_timeout_seconds must be a positive number")
        if command_timeout_seconds <= 0:
            raise WorktreeConfigurationError("command_timeout_seconds must be a positive number")
        self.git_executable = git_executable
        self.command_timeout_seconds = float(command_timeout_seconds)

    def create_worktree(
        self,
        execution_id: str,
        *,
        expected_base_commit_sha: str | None = None,
    ) -> ProvisionedWorktree:
        """Provision a new ``harness/<execution_id>`` worktree from the clean HEAD."""

        safe_execution_id = self._validate_identifier("execution_id", execution_id)
        snapshot = self._inspect_repository(require_clean=True)
        expected_sha = self._validate_expected_sha(expected_base_commit_sha)
        if expected_sha is not None and expected_sha != snapshot.head_sha:
            raise BaseCommitMismatchError("expected base commit does not match repository HEAD")

        worktree_branch = f"harness/{safe_execution_id}"
        self._run_git(("check-ref-format", "--branch", worktree_branch), cwd=snapshot.root)
        self._ensure_branch_absent(worktree_branch)

        external_base = self._external_base_dir()
        worktree_path = (external_base / safe_execution_id).resolve(strict=False)
        if worktree_path.exists():
            raise WorktreeCollisionError("external worktree path already exists")

        reference_path = self._reference_path(safe_execution_id)
        if reference_path.exists():
            raise WorktreeCollisionError("durable worktree reference already exists")

        now = self._now()
        preparing = WorktreeReference(
            execution_id=safe_execution_id,
            project_id=self.project_id,
            project_root=snapshot.root,
            worktree_path=worktree_path,
            base_commit_sha=snapshot.head_sha,
            original_branch=snapshot.branch,
            worktree_branch=worktree_branch,
            worktree_head_sha=None,
            status=WorktreeStatus.CREATING,
            failure_code=None,
            created_at=now,
            updated_at=now,
        )
        self._write_reference(preparing)

        try:
            self._run_git(
                ("worktree", "add", "-b", worktree_branch, str(worktree_path), snapshot.head_sha),
                cwd=snapshot.root,
            )
            validated_head = self._validate_worktree(
                worktree_path,
                expected_branch=worktree_branch,
                expected_head=snapshot.head_sha,
            )
            guard = PathGuard(worktree_path)
        except WorktreeError as exc:
            self._record_controlled_failure(preparing, failure_code=type(exc).__name__)
            raise
        except Exception as exc:  # pragma: no cover - defensive boundary for Path/OS surprises
            self._record_controlled_failure(preparing, failure_code="UNEXPECTED_VALIDATION_FAILURE")
            raise WorktreeValidationError("worktree validation failed unexpectedly") from exc

        active = replace(
            preparing,
            worktree_path=worktree_path.resolve(strict=True),
            worktree_head_sha=validated_head,
            status=WorktreeStatus.ACTIVE,
            updated_at=self._now(),
        )
        self._write_reference(active)
        return ProvisionedWorktree(reference=active, path_guard=guard)

    def load_worktree(self, execution_id: str) -> ProvisionedWorktree:
        """Reopen an ACTIVE reference only after revalidating its Git identity."""

        safe_execution_id = self._validate_identifier("execution_id", execution_id)
        reference = self._read_reference(safe_execution_id)
        self._validate_reference_owner(reference)
        if reference.status is not WorktreeStatus.ACTIVE:
            raise WorktreeValidationError("only ACTIVE worktree references can be reopened")
        if reference.worktree_head_sha is None:
            raise WorktreeValidationError("ACTIVE worktree reference is missing its validated HEAD")

        validated_head = self._validate_worktree(
            reference.worktree_path,
            expected_branch=reference.worktree_branch,
            expected_head=reference.worktree_head_sha,
        )
        if validated_head != reference.base_commit_sha:
            raise WorktreeValidationError("worktree HEAD no longer matches the recorded base commit")
        guard = PathGuard(reference.worktree_path)
        return ProvisionedWorktree(reference=reference, path_guard=guard)

    def cleanup_worktree(self, execution_id: str) -> WorktreeReference:
        """Explicitly remove a clean worktree without forcing or deleting its branch."""

        safe_execution_id = self._validate_identifier("execution_id", execution_id)
        reference = self._read_reference(safe_execution_id)
        self._validate_reference_owner(reference)
        if reference.status is WorktreeStatus.REMOVED:
            return reference
        if reference.status is not WorktreeStatus.ACTIVE:
            raise WorktreeCleanupError("only an ACTIVE worktree can enter explicit cleanup")
        if reference.worktree_head_sha is None:
            raise WorktreeValidationError("ACTIVE worktree reference is missing its validated HEAD")

        self._validate_worktree(
            reference.worktree_path,
            expected_branch=reference.worktree_branch,
            expected_head=reference.worktree_head_sha,
        )
        dirty = self._run_git(
            ("status", "--porcelain=v1", "--untracked-files=all"),
            cwd=reference.worktree_path,
        ).stdout
        if dirty.strip():
            raise DirtyWorktreeError("external worktree contains changes; non-forced cleanup refused")

        pending = replace(reference, status=WorktreeStatus.CLEANUP_PENDING, updated_at=self._now())
        self._write_reference(pending)
        try:
            self._run_git(("worktree", "remove", str(reference.worktree_path)), cwd=self.project_root)
        except WorktreeError as exc:
            raise WorktreeCleanupError("Git could not remove the external worktree safely") from exc
        if reference.worktree_path.exists():
            raise WorktreeCleanupError("external worktree path still exists after Git cleanup")

        removed = replace(pending, status=WorktreeStatus.REMOVED, updated_at=self._now())
        self._write_reference(removed)
        return removed

    def _inspect_repository(self, *, require_clean: bool) -> _RepositorySnapshot:
        inside = self._run_git(
            ("rev-parse", "--is-inside-work-tree"),
            cwd=self.project_root,
            allowed_returncodes=(0, 1, 128),
        )
        if inside.returncode != 0 or inside.stdout.strip() != "true":
            raise InvalidGitRepositoryError("project_root is not a Git working tree")

        root_result = self._run_git(("rev-parse", "--show-toplevel"), cwd=self.project_root)
        try:
            git_root = Path(root_result.stdout.strip()).resolve(strict=True)
        except (OSError, RuntimeError, ValueError) as exc:
            raise InvalidGitRepositoryError("Git repository root cannot be resolved") from exc
        if git_root != self.project_root:
            raise InvalidGitRepositoryError("project_root must be the exact Git top-level directory")

        branch_result = self._run_git(
            ("symbolic-ref", "--quiet", "--short", "HEAD"),
            cwd=self.project_root,
            allowed_returncodes=(0, 1),
        )
        if branch_result.returncode != 0 or not branch_result.stdout.strip():
            raise DetachedHeadError("original checkout must be attached to a branch")

        head_result = self._run_git(
            ("rev-parse", "--verify", "HEAD^{commit}"),
            cwd=self.project_root,
            allowed_returncodes=(0, 128),
        )
        if head_result.returncode != 0:
            raise InvalidGitRepositoryError("repository must contain a valid base commit")
        head = head_result.stdout.strip().lower()
        if self._FULL_SHA.fullmatch(head) is None:
            raise InvalidGitRepositoryError("repository HEAD did not resolve to a full commit SHA")

        if require_clean:
            status = self._run_git(
                ("status", "--porcelain=v1", "--untracked-files=all"),
                cwd=self.project_root,
            ).stdout
            if status.strip():
                raise DirtyRepositoryError("original checkout must be clean before worktree creation")

        return _RepositorySnapshot(root=git_root, head_sha=head, branch=branch_result.stdout.strip())

    def _validate_worktree(
        self,
        worktree_path: Path,
        *,
        expected_branch: str,
        expected_head: str | None,
    ) -> str:
        try:
            canonical_path = worktree_path.resolve(strict=True)
        except (OSError, RuntimeError, ValueError) as exc:
            raise WorktreeValidationError("external worktree path does not exist") from exc
        if not canonical_path.is_dir():
            raise WorktreeValidationError("external worktree path is not a directory")

        root_result = self._run_git(("rev-parse", "--show-toplevel"), cwd=canonical_path)
        try:
            git_root = Path(root_result.stdout.strip()).resolve(strict=True)
        except (OSError, RuntimeError, ValueError) as exc:
            raise WorktreeValidationError("external Git root cannot be resolved") from exc
        if git_root != canonical_path:
            raise WorktreeValidationError("external path is not the exact Git worktree root")

        branch_result = self._run_git(
            ("symbolic-ref", "--quiet", "--short", "HEAD"),
            cwd=canonical_path,
            allowed_returncodes=(0, 1),
        )
        if branch_result.returncode != 0 or branch_result.stdout.strip() != expected_branch:
            raise WorktreeValidationError("external worktree branch does not match its reference")

        head = self._run_git(("rev-parse", "--verify", "HEAD^{commit}"), cwd=canonical_path).stdout.strip().lower()
        if self._FULL_SHA.fullmatch(head) is None:
            raise WorktreeValidationError("external worktree HEAD is not a full commit SHA")
        if expected_head is not None and head != expected_head:
            raise WorktreeValidationError("external worktree HEAD does not match its reference")
        return head

    def _ensure_branch_absent(self, branch: str) -> None:
        result = self._run_git(
            ("show-ref", "--verify", "--quiet", f"refs/heads/{branch}"),
            cwd=self.project_root,
            allowed_returncodes=(0, 1),
        )
        if result.returncode == 0:
            raise WorktreeCollisionError("worktree branch already exists")

    def _external_base_dir(self) -> Path:
        if self._configured_external_base is None:
            base = SandboxProvider.get_external_worktree_base_dir(self.project_id)
        else:
            base = self._path_from_input(self._configured_external_base, label="external_base_dir")
            try:
                proposed = base.resolve(strict=False)
            except (OSError, RuntimeError, ValueError) as exc:
                raise WorktreeConfigurationError("external_base_dir cannot be resolved") from exc
            if proposed.is_relative_to(self.project_root):
                raise WorktreeConfigurationError("external_base_dir must be outside project_root")
            try:
                base.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise WorktreeConfigurationError("external_base_dir cannot be created") from exc
        try:
            canonical = base.resolve(strict=True)
        except (OSError, RuntimeError, ValueError) as exc:
            raise WorktreeConfigurationError("external_base_dir cannot be resolved") from exc
        if not canonical.is_dir():
            raise WorktreeConfigurationError("external_base_dir must be a directory")
        if canonical.is_relative_to(self.project_root):
            raise WorktreeConfigurationError("external_base_dir must be outside project_root")
        return canonical

    def _reference_path(self, execution_id: str) -> Path:
        return self.project_root / ".harness" / "state" / "worktree-references" / f"{execution_id}.json"

    def _write_reference(self, reference: WorktreeReference) -> None:
        destination = self._reference_path(reference.execution_id)
        content = (
            json.dumps(
                reference.to_dict(),
                ensure_ascii=False,
                allow_nan=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            descriptor, raw_temp_path = tempfile.mkstemp(
                prefix=f".{destination.name}.",
                suffix=".tmp",
                dir=destination.parent,
            )
            temp_path = Path(raw_temp_path)
            try:
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temp_path, destination)
                self._fsync_directory(destination.parent)
            finally:
                temp_path.unlink(missing_ok=True)
        except (OSError, TypeError, ValueError) as exc:
            raise WorktreeReferenceError("worktree reference could not be published atomically") from exc

    def _read_reference(self, execution_id: str) -> WorktreeReference:
        reference_path = self._reference_path(execution_id)
        try:
            raw = reference_path.read_text(encoding="utf-8", errors="strict")
            payload = json.loads(raw, object_pairs_hook=self._reject_duplicate_keys, parse_constant=self._reject_constant)
        except WorktreeReferenceError:
            raise
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise WorktreeReferenceError("worktree reference is missing or invalid") from exc
        reference = WorktreeReference.from_dict(payload)
        if reference.execution_id != execution_id:
            raise WorktreeReferenceError("worktree reference execution_id does not match its filename")
        return reference

    def _validate_reference_owner(self, reference: WorktreeReference) -> None:
        self._validate_identifier("execution_id", reference.execution_id)
        self._validate_identifier("project_id", reference.project_id)
        if reference.project_id != self.project_id:
            raise WorktreeReferenceError("worktree reference belongs to another project_id")
        try:
            recorded_root = reference.project_root.resolve(strict=True)
        except (OSError, RuntimeError, ValueError) as exc:
            raise WorktreeReferenceError("recorded project_root cannot be resolved") from exc
        if recorded_root != self.project_root:
            raise WorktreeReferenceError("worktree reference belongs to another project_root")
        expected_path = (self._external_base_dir() / reference.execution_id).resolve(strict=False)
        try:
            recorded_path = reference.worktree_path.resolve(strict=False)
        except (OSError, RuntimeError, ValueError) as exc:
            raise WorktreeReferenceError("recorded worktree_path cannot be resolved") from exc
        if recorded_path != expected_path:
            raise WorktreeReferenceError("worktree reference path does not match its execution_id")
        if reference.worktree_branch != f"harness/{reference.execution_id}":
            raise WorktreeReferenceError("worktree reference branch does not match its execution_id")
        if self._FULL_SHA.fullmatch(reference.base_commit_sha) is None:
            raise WorktreeReferenceError("worktree reference contains an invalid base commit SHA")
        if reference.worktree_head_sha is not None and self._FULL_SHA.fullmatch(reference.worktree_head_sha) is None:
            raise WorktreeReferenceError("worktree reference contains an invalid HEAD SHA")
        if reference.status is WorktreeStatus.ACTIVE and reference.worktree_head_sha is None:
            raise WorktreeReferenceError("ACTIVE worktree reference is missing its validated HEAD")
        if reference.status is WorktreeStatus.FAILED and reference.failure_code is None:
            raise WorktreeReferenceError("FAILED worktree reference is missing its failure code")
        if reference.status in {WorktreeStatus.ACTIVE, WorktreeStatus.REMOVED} and reference.failure_code is not None:
            raise WorktreeReferenceError("successful worktree reference cannot contain a failure code")
        self._validate_timestamp(reference.created_at, label="created_at")
        self._validate_timestamp(reference.updated_at, label="updated_at")

    def _record_controlled_failure(self, reference: WorktreeReference, *, failure_code: str) -> None:
        failed = replace(
            reference,
            status=WorktreeStatus.FAILED,
            failure_code=failure_code,
            updated_at=self._now(),
        )
        self._write_reference(failed)

    def _run_git(
        self,
        arguments: Collection[str],
        *,
        cwd: Path,
        allowed_returncodes: Collection[int] = (0,),
    ) -> subprocess.CompletedProcess[str]:
        argv = [self.git_executable, *arguments]
        try:
            result = subprocess.run(
                argv,
                cwd=cwd,
                check=False,
                shell=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.command_timeout_seconds,
                env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
            )
        except FileNotFoundError as exc:
            raise GitUnavailableError("configured Git executable was not found") from exc
        except subprocess.TimeoutExpired as exc:
            raise GitCommandError("Git command exceeded its configured timeout") from exc
        except OSError as exc:
            raise GitCommandError("Git command could not be started") from exc
        if result.returncode not in allowed_returncodes:
            operation = " ".join(tuple(arguments)[:2])
            raise GitCommandError(f"Git operation {operation!r} failed with exit code {result.returncode}")
        return result

    @classmethod
    def _validate_identifier(cls, label: str, value: str) -> str:
        if type(value) is not str or cls._IDENTIFIER.fullmatch(value) is None:
            raise WorktreeConfigurationError(f"{label} contains unsafe characters or length")
        if ".." in value or value.endswith(".") or value.casefold().endswith(".lock"):
            raise WorktreeConfigurationError(f"{label} is not safe for a path and Git branch")
        return value

    @classmethod
    def _validate_expected_sha(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if type(value) is not str or cls._FULL_SHA.fullmatch(value.lower()) is None:
            raise WorktreeConfigurationError("expected_base_commit_sha must be a full hexadecimal SHA")
        return value.lower()

    @classmethod
    def _existing_directory(cls, value: str | os.PathLike[str], *, label: str) -> Path:
        raw_path = cls._path_from_input(value, label=label)
        try:
            path = raw_path.resolve(strict=True)
        except (OSError, RuntimeError, ValueError) as exc:
            raise WorktreeConfigurationError(f"{label} must resolve to an existing directory") from exc
        if not path.is_dir():
            raise WorktreeConfigurationError(f"{label} must resolve to an existing directory")
        return path

    @staticmethod
    def _path_from_input(value: str | os.PathLike[str], *, label: str) -> Path:
        try:
            raw = os.fspath(value)
        except TypeError as exc:
            raise WorktreeConfigurationError(f"{label} must be a string or path-like value") from exc
        if not isinstance(raw, str) or "\x00" in raw:
            raise WorktreeConfigurationError(f"{label} must be non-null text")
        return Path(raw)

    @staticmethod
    def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise WorktreeReferenceError("worktree reference contains duplicate JSON keys")
            result[key] = value
        return result

    @staticmethod
    def _reject_constant(value: str) -> None:
        raise WorktreeReferenceError(f"invalid JSON constant in worktree reference: {value}")

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _validate_timestamp(value: str, *, label: str) -> None:
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as exc:
            raise WorktreeReferenceError(f"worktree reference contains an invalid {label}") from exc
        if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
            raise WorktreeReferenceError(f"worktree reference {label} must be UTC")

    @staticmethod
    def _fsync_directory(directory: Path) -> None:
        try:
            descriptor = os.open(directory, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(descriptor)
        except OSError:
            pass
        finally:
            os.close(descriptor)


__all__ = [
    "BaseCommitMismatchError",
    "DetachedHeadError",
    "DirtyRepositoryError",
    "DirtyWorktreeError",
    "ExternalWorktreeManager",
    "GitCommandError",
    "GitUnavailableError",
    "InvalidGitRepositoryError",
    "ProvisionedWorktree",
    "WorktreeCleanupError",
    "WorktreeCollisionError",
    "WorktreeConfigurationError",
    "WorktreeError",
    "WorktreeReference",
    "WorktreeReferenceError",
    "WorktreeStatus",
    "WorktreeValidationError",
]
