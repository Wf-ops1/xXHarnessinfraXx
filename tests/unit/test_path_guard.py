"""F3.4 path confinement tests with no operational adapter effects."""

from __future__ import annotations

import os
import subprocess
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from ai_engineering_harness.security import (
    GitMetadataPathError,
    PathGuard,
    PathGuardConfigurationError,
    PathOutsideRootError,
    PathResolutionError,
    PathSizeLimitError,
    PathTraversalError,
)


def test_internal_paths_return_canonical_absolute_and_posix_journal_path(tmp_path: Path) -> None:
    root = tmp_path / "worktree"
    target = root / "nested" / "file.txt"
    target.parent.mkdir(parents=True)
    target.write_text("safe", encoding="utf-8")
    guard = PathGuard(root, max_read_bytes=4)

    relative_result = guard.guard_read(Path("nested") / "file.txt")
    absolute_result = guard.guard_read(target.resolve())

    assert relative_result == absolute_result
    assert relative_result.absolute_path == target.resolve(strict=True)
    assert relative_result.relative_path == "nested/file.txt"
    assert not Path(relative_result.relative_path).is_absolute()


def test_nonexistent_internal_write_is_resolved_without_creating_anything(tmp_path: Path) -> None:
    root = tmp_path / "worktree"
    root.mkdir()
    target = root / "new" / "file.txt"
    guard = PathGuard(root, max_write_bytes=12)

    result = guard.guard_write("new/file.txt", size_bytes=12)

    assert result.absolute_path == target.resolve(strict=False)
    assert result.relative_path == "new/file.txt"
    assert not target.exists()
    assert not target.parent.exists()


def test_guard_configuration_is_immutable_after_construction(tmp_path: Path) -> None:
    root = tmp_path / "worktree"
    root.mkdir()
    guard = PathGuard(root)

    with pytest.raises(FrozenInstanceError):
        guard._authorized_root = tmp_path  # type: ignore[misc]


@pytest.mark.parametrize("candidate", ["../outside.txt", "nested/../../outside.txt", r"..\outside.txt"])
def test_parent_traversal_is_rejected_before_resolution(tmp_path: Path, candidate: str) -> None:
    root = tmp_path / "worktree"
    root.mkdir()
    guard = PathGuard(root)

    with pytest.raises(PathTraversalError, match="parent traversal"):
        guard.guard_write(candidate, size_bytes=1)


def test_absolute_external_path_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "worktree"
    outside = tmp_path / "outside.txt"
    root.mkdir()
    outside.write_text("outside", encoding="utf-8")
    guard = PathGuard(root)

    with pytest.raises(PathOutsideRootError, match="outside the authorized root"):
        guard.guard_read(outside.resolve())


def test_symlink_escape_is_rejected_for_read_and_future_write(tmp_path: Path) -> None:
    root = tmp_path / "worktree"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "secret.txt").write_text("secret", encoding="utf-8")
    link = root / "escape"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks unavailable on this runner: {exc}")
    guard = PathGuard(root)

    with pytest.raises(PathOutsideRootError):
        guard.guard_read(link / "secret.txt")
    with pytest.raises(PathOutsideRootError):
        guard.guard_write(link / "future.txt", size_bytes=1)


@pytest.mark.skipif(os.name != "nt", reason="Windows junction-specific confinement proof")
def test_windows_junction_escape_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "worktree"
    outside = tmp_path / "outside"
    junction = root / "junction"
    root.mkdir()
    outside.mkdir()
    created = subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(junction), str(outside)],
        capture_output=True,
        check=False,
        text=True,
    )
    assert created.returncode == 0, created.stderr or created.stdout
    guard = PathGuard(root)

    try:
        with pytest.raises(PathOutsideRootError):
            guard.guard_write(junction / "future.txt", size_bytes=1)
    finally:
        if junction.exists():
            junction.rmdir()


@pytest.mark.parametrize("candidate", [".git/config", ".GIT/index", "nested/.Git/objects/new"])
def test_writes_to_git_metadata_are_rejected_case_insensitively(
    tmp_path: Path,
    candidate: str,
) -> None:
    root = tmp_path / "worktree"
    root.mkdir()
    guard = PathGuard(root)

    with pytest.raises(GitMetadataPathError, match="Git metadata"):
        guard.guard_write(candidate, size_bytes=1)


def test_read_and_write_size_limits_fail_closed(tmp_path: Path) -> None:
    root = tmp_path / "worktree"
    root.mkdir()
    oversized = root / "oversized.bin"
    oversized.write_bytes(b"12345")
    guard = PathGuard(root, max_read_bytes=4, max_write_bytes=4)

    with pytest.raises(PathSizeLimitError, match="max_read_bytes"):
        guard.guard_read(oversized)
    with pytest.raises(PathSizeLimitError, match="max_write_bytes"):
        guard.guard_write("future.bin", size_bytes=5)
    with pytest.raises(PathSizeLimitError, match="non-negative integer"):
        guard.guard_write("future.bin", size_bytes=-1)
    with pytest.raises(PathSizeLimitError, match="non-negative integer"):
        guard.guard_write("future.bin", size_bytes=True)


@pytest.mark.parametrize("name,value", [("max_read_bytes", 0), ("max_write_bytes", -1)])
def test_limits_must_be_positive_integers(tmp_path: Path, name: str, value: int) -> None:
    root = tmp_path / "worktree"
    root.mkdir()
    kwargs = {name: value}

    with pytest.raises(PathGuardConfigurationError, match="positive integer"):
        PathGuard(root, **kwargs)


def test_root_must_be_an_existing_non_filesystem_directory(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    regular_file = tmp_path / "file.txt"
    regular_file.write_text("x", encoding="utf-8")

    with pytest.raises(PathGuardConfigurationError, match="existing directory"):
        PathGuard(missing)
    with pytest.raises(PathGuardConfigurationError, match="existing directory"):
        PathGuard(regular_file)
    with pytest.raises(PathGuardConfigurationError, match="filesystem roots"):
        PathGuard(Path(tmp_path.anchor))


def test_missing_read_and_non_text_paths_fail_with_typed_resolution_error(tmp_path: Path) -> None:
    root = tmp_path / "worktree"
    root.mkdir()
    guard = PathGuard(root)

    with pytest.raises(PathResolutionError, match="resolved safely"):
        guard.guard_read("missing.txt")
    with pytest.raises(PathResolutionError, match="text, not bytes"):
        guard.guard_read(b"bytes-path")  # type: ignore[arg-type]


def test_internal_symlink_is_normalized_to_its_canonical_relative_target(tmp_path: Path) -> None:
    root = tmp_path / "worktree"
    real = root / "real"
    alias = root / "alias"
    real.mkdir(parents=True)
    (real / "file.txt").write_text("safe", encoding="utf-8")
    try:
        alias.symlink_to(real, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks unavailable on this runner: {exc}")
    guard = PathGuard(root)

    result = guard.guard_read(alias / "file.txt")

    assert result.relative_path == "real/file.txt"
    assert result.absolute_path == (real / "file.txt").resolve(strict=True)
