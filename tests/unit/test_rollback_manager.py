"""Real Git proofs for the canonical F5.7 rollback manager."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ai_engineering_harness.runtime import (
    RollbackManager,
    RollbackPrerequisiteError,
)
from ai_engineering_harness.security import TrustAuthorization, TrustBoundaryEvaluator


def _git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ("git", *arguments),
        cwd=root,
        check=True,
        shell=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout.strip()


def _repository(root: Path) -> tuple[str, str]:
    root.mkdir()
    _git(root, "init", "--initial-branch=main")
    _git(root, "config", "user.name", "Harness Test")
    _git(root, "config", "user.email", "harness@example.invalid")
    target = root / "artifact.txt"
    target.write_text("base\n", encoding="utf-8")
    _git(root, "add", "--", target.name)
    _git(root, "commit", "-m", "base")
    base = _git(root, "rev-parse", "HEAD")
    target.write_text("promoted\n", encoding="utf-8")
    _git(root, "add", "--", target.name)
    _git(root, "commit", "-m", "promotion")
    promotion = _git(root, "rev-parse", "HEAD")
    return base, promotion


def test_revert_uses_argv_and_proves_new_commit_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "repository"
    base, promotion = _repository(root)
    commit_hook = root / ".git" / "hooks" / "commit-msg"
    commit_hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    commit_hook.chmod(0o700)
    original_run = subprocess.run
    observed_shell: list[bool] = []
    observed_argv: list[tuple[str, ...]] = []

    def observing_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        argv = args[0]
        assert isinstance(argv, tuple)
        observed_argv.append(argv)
        observed_shell.append(bool(kwargs.get("shell")))
        return original_run(*args, **kwargs)  # type: ignore[call-overload,return-value]

    monkeypatch.setattr(subprocess, "run", observing_run)
    result = RollbackManager(root).rollback(
        promotion_commit_sha=promotion,
        original_branch="main",
    )

    assert result.compensated
    assert result.previous_head_sha == promotion
    assert result.rollback_commit_sha == _git(root, "rev-parse", "HEAD")
    assert _git(root, "rev-parse", "HEAD^") == promotion
    assert (root / "artifact.txt").read_text(encoding="utf-8") == "base\n"
    assert _git(root, "status", "--porcelain=v1", "--untracked-files=all") == ""
    assert any(argv[1:3] == ("revert", "--no-edit") for argv in observed_argv)
    assert observed_shell and not any(observed_shell)
    assert base != promotion


def test_conflict_is_aborted_and_blocks_without_claiming_success(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    _, promotion = _repository(root)
    target = root / "artifact.txt"
    target.write_text("later incompatible content\n", encoding="utf-8")
    _git(root, "add", "--", target.name)
    _git(root, "commit", "-m", "later change")
    previous_head = _git(root, "rev-parse", "HEAD")

    result = RollbackManager(root).rollback(
        promotion_commit_sha=promotion,
        original_branch="main",
    )

    assert not result.compensated
    assert result.outcome == "blocked"
    assert result.rollback_commit_sha is None
    assert result.conflicting_paths == ("artifact.txt",)
    assert result.abort_attempted
    assert result.abort_succeeded
    assert result.restored_after_abort
    assert _git(root, "rev-parse", "HEAD") == previous_head
    assert target.read_text(encoding="utf-8") == "later incompatible content\n"
    assert _git(root, "status", "--porcelain=v1", "--untracked-files=all") == ""


def test_dirty_or_wrong_branch_fails_before_effect(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    _, promotion = _repository(root)
    previous_head = _git(root, "rev-parse", "HEAD")
    manager = RollbackManager(root)

    with pytest.raises(RollbackPrerequisiteError, match="branch"):
        manager.rollback(
            promotion_commit_sha=promotion,
            original_branch="release",
        )
    assert _git(root, "rev-parse", "HEAD") == previous_head
    (root / "untracked.txt").write_text("dirty", encoding="utf-8")
    with pytest.raises(RollbackPrerequisiteError, match="clean"):
        manager.rollback(
            promotion_commit_sha=promotion,
            original_branch="main",
        )
    assert _git(root, "rev-parse", "HEAD") == previous_head


def test_destructive_injected_hook_requires_bound_explicit_approval(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    _, promotion = _repository(root)
    harness_root = root / ".harness"
    harness_root.mkdir()
    (harness_root / "trusted_repository").touch()
    boundary = TrustBoundaryEvaluator(
        root,
        authorization=TrustAuthorization(
            repository_root=str(root.resolve(strict=True)),
            executable_aliases=("git",),
            hook_ids=("rollback-compensation",),
        ),
    ).evaluate()
    calls: list[str] = []
    manager = RollbackManager(
        root,
        trust_boundary=boundary,
        compensation_hook=lambda result: calls.append(result.promotion_commit_sha),
        hook_id="rollback-compensation",
        hook_destructive=True,
    )

    with pytest.raises(RollbackPrerequisiteError, match="not explicitly authorized"):
        manager.rollback(
            promotion_commit_sha=promotion,
            original_branch="main",
        )

    assert calls == []
    assert _git(root, "rev-parse", "HEAD") == promotion
