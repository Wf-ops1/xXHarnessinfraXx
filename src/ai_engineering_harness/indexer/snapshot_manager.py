"""Integrity-checked persistence for commit-bound structural snapshots."""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from collections.abc import Iterable, Mapping
from pathlib import Path

from pydantic import ValidationError

from ai_engineering_harness.contracts.structural_index import (
    StructuralSnapshot,
    StructuralSymbol,
    validate_commit_sha,
)

_SAFE_GIT_REVISION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/~^-]{0,255}$")


class StructuralIndexError(Exception):
    """Base error for structural snapshot identity, persistence, and loading."""


class GitCommitResolutionError(StructuralIndexError):
    """A Git revision could not be proven to identify a real commit."""


class SnapshotIntegrityError(StructuralIndexError):
    """A stored snapshot is malformed, noncanonical, or digest-invalid."""


class SnapshotConflictError(SnapshotIntegrityError):
    """An immutable commit identity already has different snapshot content."""


class SnapshotNotFoundError(StructuralIndexError):
    """No validated snapshot exists for the requested real Git commit."""


class SnapshotWriteError(StructuralIndexError):
    """A validated snapshot could not be published atomically."""


def resolve_git_commit(
    project_root: Path,
    revision: str = "HEAD",
    *,
    git_executable: str = "git",
    timeout_seconds: float = 10.0,
) -> str:
    """Resolve a transient Git revision to its real full lowercase commit SHA."""

    root = _existing_project_root(project_root)
    if type(revision) is not str or _SAFE_GIT_REVISION.fullmatch(revision) is None:
        raise GitCommitResolutionError("Git revision is empty or contains unsupported characters")
    if type(git_executable) is not str or not git_executable.strip() or "\x00" in git_executable:
        raise GitCommitResolutionError("git_executable must be non-empty NUL-free text")
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)) or timeout_seconds <= 0:
        raise GitCommitResolutionError("Git resolution timeout must be a positive number")
    try:
        result = subprocess.run(
            [git_executable, "rev-parse", "--verify", f"{revision}^{{commit}}"],
            cwd=root,
            check=False,
            shell=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=float(timeout_seconds),
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
    except FileNotFoundError as exc:
        raise GitCommitResolutionError("configured Git executable was not found") from exc
    except subprocess.TimeoutExpired as exc:
        raise GitCommitResolutionError("Git commit resolution timed out") from exc
    except OSError as exc:
        raise GitCommitResolutionError("Git commit resolution could not be started") from exc
    if result.returncode != 0:
        raise GitCommitResolutionError(
            f"Git revision could not be resolved to a commit (exit {result.returncode})"
        )
    resolved = result.stdout.strip().lower()
    try:
        return validate_commit_sha(resolved)
    except ValueError as exc:
        raise GitCommitResolutionError("Git returned a noncanonical commit identity") from exc


class SnapshotManager:
    """Store one immutable canonical JSON snapshot per real Git commit SHA."""

    def __init__(self, project_root: Path):
        self.project_root = _existing_project_root(project_root)
        self.index_dir = (
            self.project_root / ".harness" / "state" / "structural-index" / "snapshots"
        )

    def snapshot_path(self, commit_sha: str) -> Path:
        """Return the only canonical path for a validated full commit SHA."""

        try:
            validated_sha = validate_commit_sha(commit_sha)
        except ValueError as exc:
            raise SnapshotIntegrityError(str(exc)) from exc
        return self.index_dir / f"{validated_sha}.json"

    def save_snapshot(
        self,
        commit_sha: str,
        symbols: Iterable[StructuralSymbol | Mapping[str, object]],
    ) -> Path:
        """Publish a ready snapshot atomically without replacing divergent content."""

        try:
            snapshot = StructuralSnapshot.create(commit_sha, symbols)
        except (TypeError, ValueError, ValidationError) as exc:
            raise SnapshotIntegrityError(f"structural snapshot content is invalid: {exc}") from exc
        destination = self.snapshot_path(snapshot.commit_sha)
        self._ensure_index_directory()

        if destination.exists() or destination.is_symlink():
            existing = self.get_snapshot(snapshot.commit_sha)
            if existing == snapshot:
                return destination
            raise SnapshotConflictError("snapshot content conflicts with the immutable commit identity")

        try:
            _atomic_replace_text(destination, snapshot.canonical_json())
        except OSError as exc:
            raise SnapshotWriteError("structural snapshot could not be published atomically") from exc

        persisted = self.get_snapshot(snapshot.commit_sha)
        if persisted != snapshot:
            raise SnapshotWriteError("published structural snapshot failed read-after-write validation")
        return destination

    def get_snapshot(self, commit_sha: str) -> StructuralSnapshot | None:
        """Load one ready snapshot only after every integrity check passes."""

        source = self.snapshot_path(commit_sha)
        self._validate_storage_boundary(for_write=False)
        if source.is_symlink():
            raise SnapshotIntegrityError("structural snapshot file must not be a symbolic link")
        try:
            raw_text = source.read_text(encoding="utf-8", errors="strict")
        except FileNotFoundError:
            return None
        except (OSError, UnicodeError) as exc:
            raise SnapshotIntegrityError("structural snapshot could not be read") from exc

        try:
            payload = json.loads(
                raw_text,
                object_pairs_hook=_reject_duplicate_keys,
                parse_constant=_reject_json_constant,
            )
            snapshot = StructuralSnapshot.model_validate(payload)
            snapshot.verify_digest()
        except (SnapshotIntegrityError, ValidationError, ValueError, TypeError, json.JSONDecodeError) as exc:
            if isinstance(exc, SnapshotIntegrityError):
                raise
            raise SnapshotIntegrityError(f"structural snapshot is invalid: {exc}") from exc
        if snapshot.commit_sha != commit_sha:
            raise SnapshotIntegrityError("snapshot commit_sha does not match the requested identity")
        if raw_text != snapshot.canonical_json():
            raise SnapshotIntegrityError("structural snapshot is not canonical JSON")
        return snapshot

    def require_snapshot(self, commit_sha: str) -> StructuralSnapshot:
        """Load a validated snapshot or fail explicitly when it does not exist."""

        snapshot = self.get_snapshot(commit_sha)
        if snapshot is None:
            raise SnapshotNotFoundError(f"no ready structural snapshot exists for commit {commit_sha}")
        return snapshot

    def _ensure_index_directory(self) -> None:
        self._validate_storage_boundary(for_write=True)
        try:
            self.index_dir.mkdir(parents=True, exist_ok=True)
            canonical_index_dir = self.index_dir.resolve(strict=True)
        except (OSError, RuntimeError, ValueError) as exc:
            raise SnapshotWriteError("structural snapshot directory could not be prepared") from exc
        if not canonical_index_dir.is_relative_to(self.project_root):
            raise SnapshotWriteError("structural snapshot directory escapes the project root")
        self._validate_storage_boundary(for_write=True)

    def _validate_storage_boundary(self, *, for_write: bool) -> None:
        error_type = SnapshotWriteError if for_write else SnapshotIntegrityError
        current = self.project_root
        for part in self.index_dir.relative_to(self.project_root).parts:
            current /= part
            if current.is_symlink():
                raise error_type("structural snapshot path must not traverse symbolic links")
        if not self.index_dir.exists():
            return
        try:
            canonical_index_dir = self.index_dir.resolve(strict=True)
        except (OSError, RuntimeError, ValueError) as exc:
            raise error_type("structural snapshot directory could not be validated") from exc
        if not canonical_index_dir.is_relative_to(self.project_root):
            raise error_type("structural snapshot directory escapes the project root")


def _existing_project_root(project_root: Path) -> Path:
    try:
        root = Path(project_root).resolve(strict=True)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise GitCommitResolutionError("project_root must resolve to an existing directory") from exc
    if not root.is_dir():
        raise GitCommitResolutionError("project_root must resolve to an existing directory")
    return root


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise SnapshotIntegrityError("structural snapshot contains duplicate JSON keys")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise SnapshotIntegrityError(f"structural snapshot contains invalid JSON constant {value!r}")


def _atomic_replace_text(destination: Path, content: str) -> None:
    descriptor: int | None = None
    temp_path: Path | None = None
    try:
        descriptor, raw_temp_path = tempfile.mkstemp(
            prefix=f".{destination.name}.",
            suffix=".tmp",
            dir=destination.parent,
        )
        temp_path = Path(raw_temp_path)
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = None
            stream.write(content.encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, destination)
        temp_path = None
        _fsync_directory(destination.parent)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def _fsync_directory(directory: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


__all__ = [
    "GitCommitResolutionError",
    "SnapshotConflictError",
    "SnapshotIntegrityError",
    "SnapshotManager",
    "SnapshotNotFoundError",
    "SnapshotWriteError",
    "StructuralIndexError",
    "resolve_git_commit",
]
