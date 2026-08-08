"""Fail-closed path confinement for future operational tool adapters."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import ClassVar


class PathGuardError(ValueError):
    """Base error for path confinement failures."""


class PathGuardConfigurationError(PathGuardError):
    """Raised when the authorized root or a configured limit is unsafe."""


class PathTraversalError(PathGuardError):
    """Raised when a candidate contains an explicit parent traversal."""


class PathOutsideRootError(PathGuardError):
    """Raised when a candidate resolves outside the authorized root."""


class GitMetadataPathError(PathGuardError):
    """Raised when a write targets Git metadata."""


class PathSizeLimitError(PathGuardError):
    """Raised when a read or intended write exceeds its configured limit."""


class PathResolutionError(PathGuardError):
    """Raised when a candidate cannot be resolved or inspected safely."""


@dataclass(frozen=True, slots=True)
class GuardedPath:
    """Canonical consumer path plus the only representation safe for journaling."""

    absolute_path: Path
    relative_path: str


@dataclass(frozen=True, slots=True, init=False)
class PathGuard:
    """Validate paths against one explicit, canonical authorized root.

    The guard performs no content I/O and creates nothing. Future adapters must
    call it immediately before their effect and persist only ``relative_path``.
    """

    DEFAULT_MAX_READ_BYTES: ClassVar[int] = 1_000_000
    DEFAULT_MAX_WRITE_BYTES: ClassVar[int] = 1_000_000

    _authorized_root: Path
    _max_read_bytes: int
    _max_write_bytes: int

    def __init__(
        self,
        authorized_root: str | os.PathLike[str],
        *,
        max_read_bytes: int = DEFAULT_MAX_READ_BYTES,
        max_write_bytes: int = DEFAULT_MAX_WRITE_BYTES,
    ) -> None:
        object.__setattr__(self, "_max_read_bytes", self._validate_limit("max_read_bytes", max_read_bytes))
        object.__setattr__(self, "_max_write_bytes", self._validate_limit("max_write_bytes", max_write_bytes))
        object.__setattr__(self, "_authorized_root", self._resolve_root(authorized_root))

    @property
    def authorized_root(self) -> Path:
        """Return the canonical root explicitly supplied by the caller."""

        return self._authorized_root

    @property
    def max_read_bytes(self) -> int:
        """Maximum size accepted for an existing regular file read."""

        return self._max_read_bytes

    @property
    def max_write_bytes(self) -> int:
        """Maximum declared size accepted for a future write."""

        return self._max_write_bytes

    def guard_read(self, candidate: str | os.PathLike[str]) -> GuardedPath:
        """Resolve an existing path and enforce the regular-file read limit."""

        resolved = self._resolve_candidate(candidate, must_exist=True)
        try:
            if resolved.is_file():
                size_bytes = resolved.stat().st_size
                if size_bytes > self._max_read_bytes:
                    raise PathSizeLimitError("read target exceeds max_read_bytes")
        except PathGuardError:
            raise
        except (OSError, ValueError) as exc:
            raise PathResolutionError("read target could not be inspected safely") from exc
        return self._result(resolved)

    def guard_write(
        self,
        candidate: str | os.PathLike[str],
        *,
        size_bytes: int,
    ) -> GuardedPath:
        """Resolve a future write target and enforce metadata and size policy."""

        intended_size = self._validate_write_size(size_bytes)
        if intended_size > self._max_write_bytes:
            raise PathSizeLimitError("write target exceeds max_write_bytes")

        resolved = self._resolve_candidate(candidate, must_exist=False)
        relative = resolved.relative_to(self._authorized_root)
        if any(part.casefold() == ".git" for part in relative.parts):
            raise GitMetadataPathError("writes to Git metadata are forbidden")
        return self._result(resolved)

    @staticmethod
    def _validate_limit(name: str, value: int) -> int:
        if type(value) is not int or value <= 0:
            raise PathGuardConfigurationError(f"{name} must be a positive integer")
        return value

    @staticmethod
    def _validate_write_size(value: int) -> int:
        if type(value) is not int or value < 0:
            raise PathSizeLimitError("size_bytes must be a non-negative integer")
        return value

    @staticmethod
    def _resolve_root(root: str | os.PathLike[str]) -> Path:
        raw_root = PathGuard._path_from_input(root, label="authorized root")
        try:
            resolved = raw_root.resolve(strict=True)
        except (OSError, RuntimeError, ValueError) as exc:
            raise PathGuardConfigurationError("authorized root must resolve to an existing directory") from exc
        if not resolved.is_dir():
            raise PathGuardConfigurationError("authorized root must resolve to an existing directory")
        if resolved.parent == resolved:
            raise PathGuardConfigurationError("filesystem roots cannot be authorized worktrees")
        return resolved

    def _resolve_candidate(
        self,
        candidate: str | os.PathLike[str],
        *,
        must_exist: bool,
    ) -> Path:
        raw_candidate = self._path_from_input(candidate, label="candidate path")
        self._reject_parent_traversal(raw_candidate)

        anchored = raw_candidate if raw_candidate.is_absolute() else self._authorized_root / raw_candidate
        try:
            resolved = anchored.resolve(strict=must_exist)
        except (OSError, RuntimeError, ValueError) as exc:
            raise PathResolutionError("candidate path could not be resolved safely") from exc

        if not resolved.is_relative_to(self._authorized_root):
            raise PathOutsideRootError("candidate path resolves outside the authorized root")
        return resolved

    @staticmethod
    def _path_from_input(value: str | os.PathLike[str], *, label: str) -> Path:
        try:
            raw = os.fspath(value)
        except TypeError as exc:
            raise PathResolutionError(f"{label} must be a string or path-like value") from exc
        if not isinstance(raw, str):
            raise PathResolutionError(f"{label} must use text, not bytes")
        if "\x00" in raw:
            raise PathResolutionError(f"{label} contains a null byte")
        return Path(raw)

    @staticmethod
    def _reject_parent_traversal(candidate: Path) -> None:
        raw = os.fspath(candidate)
        path_views = (candidate.parts, PurePosixPath(raw).parts, PureWindowsPath(raw).parts)
        if any(part == ".." for parts in path_views for part in parts):
            raise PathTraversalError("parent traversal is forbidden")

    def _result(self, resolved: Path) -> GuardedPath:
        relative_path = resolved.relative_to(self._authorized_root).as_posix()
        return GuardedPath(absolute_path=resolved, relative_path=relative_path)


__all__ = [
    "GitMetadataPathError",
    "GuardedPath",
    "PathGuard",
    "PathGuardConfigurationError",
    "PathGuardError",
    "PathOutsideRootError",
    "PathResolutionError",
    "PathSizeLimitError",
    "PathTraversalError",
]
