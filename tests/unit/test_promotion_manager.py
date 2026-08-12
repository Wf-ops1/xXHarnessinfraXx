"""Real Git tests for the F3.7 candidate and promotion boundary."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ai_engineering_harness.runtime.promotion_manager import (
    PromotionBaseChangedError,
    PromotionManager,
)
from ai_engineering_harness.workspace import ExternalWorktreeManager


def _git(repository: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ("git", *arguments),
        cwd=repository,
        check=True,
        shell=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def _fixture(tmp_path: Path) -> tuple[Path, ExternalWorktreeManager, PromotionManager, str, str]:
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / ".gitignore").write_text(
        ".harness/state/worktree-references/\n",
        encoding="utf-8",
    )
    (repository / "tracked.txt").write_text("base\n", encoding="utf-8")
    _git(repository, "init", "--quiet")
    _git(repository, "config", "user.name", "Promotion Test")
    _git(repository, "config", "user.email", "promotion@example.invalid")
    _git(repository, "add", "--all", "--", ".")
    _git(repository, "commit", "--quiet", "-m", "base")
    base_sha = _git(repository, "rev-parse", "HEAD").stdout.strip().lower()
    branch = _git(repository, "branch", "--show-current").stdout.strip()
    worktrees = ExternalWorktreeManager(
        repository,
        "promotion-tests",
        external_base_dir=tmp_path / "external-worktrees",
    )
    promotion = PromotionManager(repository, worktrees)
    return repository, worktrees, promotion, base_sha, branch


def _candidate(
    tmp_path: Path,
    *,
    execution_id: str = "exec-promote",
) -> tuple[Path, ExternalWorktreeManager, PromotionManager, str, str]:
    repository, worktrees, promotion, base_sha, branch = _fixture(tmp_path)
    provisioned = worktrees.create_worktree(
        execution_id,
        expected_base_commit_sha=base_sha,
    )
    (provisioned.worktree_path / "tracked.txt").write_text(
        "candidate\n",
        encoding="utf-8",
    )
    promotion.create_candidate(execution_id, message="feat: candidate")
    return repository, worktrees, promotion, base_sha, branch


def test_candidate_is_one_real_squashed_commit_without_touching_original(tmp_path: Path) -> None:
    repository, worktrees, promotion, base_sha, branch = _fixture(tmp_path)
    worktree = worktrees.create_worktree(
        "exec-candidate",
        expected_base_commit_sha=base_sha,
    )
    (worktree.worktree_path / "tracked.txt").write_text("candidate\n", encoding="utf-8")
    (worktree.worktree_path / "new.txt").write_text("new\n", encoding="utf-8")

    candidate = promotion.create_candidate(
        "exec-candidate",
        message="feat: real candidate",
    )

    assert candidate.base_commit_sha == base_sha
    assert candidate.original_branch == branch
    assert candidate.candidate_commit_sha != base_sha
    assert _git(repository, "rev-parse", "HEAD").stdout.strip().lower() == base_sha
    assert (repository / "tracked.txt").read_text(encoding="utf-8") == "base\n"
    assert not (repository / "new.txt").exists()
    assert _git(candidate.worktree_path, "rev-parse", "HEAD^").stdout.strip().lower() == base_sha
    assert _git(candidate.worktree_path, "status", "--porcelain").stdout == ""
    assert worktrees.load_worktree("exec-candidate").reference.worktree_head_sha == (
        candidate.candidate_commit_sha
    )


def test_candidate_squashes_a_clean_repair_child_back_to_the_execution_base(tmp_path: Path) -> None:
    repository, worktrees, promotion, base_sha, _ = _fixture(tmp_path)
    worktree = worktrees.create_worktree("exec-repair", expected_base_commit_sha=base_sha)
    (worktree.worktree_path / "tracked.txt").write_text("broken\n", encoding="utf-8")
    first = promotion.create_candidate("exec-repair", message="feat: first candidate")
    (worktree.worktree_path / "tracked.txt").write_text("repaired\n", encoding="utf-8")
    _git(worktree.worktree_path, "add", "--all", "--", ".")
    _git(worktree.worktree_path, "commit", "--quiet", "-m", "repair")

    repaired = promotion.create_candidate("exec-repair", message="feat: repaired candidate")

    assert repaired.candidate_commit_sha != first.candidate_commit_sha
    assert _git(repository, "rev-parse", "HEAD").stdout.strip().lower() == base_sha
    assert _git(repaired.worktree_path, "rev-parse", "HEAD^").stdout.strip().lower() == base_sha
    assert (repaired.worktree_path / "tracked.txt").read_text(encoding="utf-8") == "repaired\n"


def test_dry_run_returns_candidate_without_mutating_original(tmp_path: Path) -> None:
    repository, _, promotion, base_sha, branch = _candidate(tmp_path)
    candidate = promotion.load_candidate("exec-promote")

    result = promotion.promote(candidate, dry_run=True)

    assert result.candidate_commit_sha == candidate.candidate_commit_sha
    assert result.promotion_commit_sha is None
    assert result.original_branch == branch
    assert result.dry_run is True
    assert _git(repository, "rev-parse", "HEAD").stdout.strip().lower() == base_sha
    assert (repository / "tracked.txt").read_text(encoding="utf-8") == "base\n"


def test_live_promotion_cherry_picks_and_recovers_the_exact_real_sha(tmp_path: Path) -> None:
    repository, _, promotion, base_sha, branch = _candidate(tmp_path)
    candidate = promotion.load_candidate("exec-promote")

    promoted = promotion.promote(candidate, dry_run=False)
    recovered = promotion.promote(candidate, dry_run=False)

    assert promoted.promotion_commit_sha is not None
    assert promoted.promotion_commit_sha != candidate.candidate_commit_sha
    assert promoted.original_branch == branch
    assert promoted.dry_run is False
    assert _git(repository, "rev-parse", "HEAD").stdout.strip().lower() == (
        promoted.promotion_commit_sha
    )
    assert _git(repository, "rev-parse", "HEAD^").stdout.strip().lower() == base_sha
    assert (repository / "tracked.txt").read_text(encoding="utf-8") == "candidate\n"
    assert recovered.promotion_commit_sha == promoted.promotion_commit_sha
    assert recovered.recovered is True


def test_base_advance_blocks_without_cherry_pick_or_fallback(tmp_path: Path) -> None:
    repository, _, promotion, _, _ = _candidate(tmp_path)
    candidate = promotion.load_candidate("exec-promote")
    (repository / "base-advance.txt").write_text("advance\n", encoding="utf-8")
    _git(repository, "add", "--all", "--", ".")
    _git(repository, "commit", "--quiet", "-m", "base advance")
    advanced_sha = _git(repository, "rev-parse", "HEAD").stdout.strip().lower()

    with pytest.raises(PromotionBaseChangedError, match="advanced"):
        promotion.promote(candidate, dry_run=False)

    assert _git(repository, "rev-parse", "HEAD").stdout.strip().lower() == advanced_sha
    assert (repository / "base-advance.txt").read_text(encoding="utf-8") == "advance\n"
    assert (repository / "tracked.txt").read_text(encoding="utf-8") == "base\n"


def test_independent_same_tree_commit_is_not_misclassified_as_recovery(
    tmp_path: Path,
) -> None:
    repository, _, promotion, _, _ = _candidate(tmp_path)
    candidate = promotion.load_candidate("exec-promote")
    (repository / "tracked.txt").write_text("candidate\n", encoding="utf-8")
    _git(repository, "add", "--all", "--", ".")
    _git(repository, "commit", "--quiet", "-m", "independent same tree")
    independent_sha = _git(repository, "rev-parse", "HEAD").stdout.strip().lower()

    with pytest.raises(PromotionBaseChangedError, match="advanced"):
        promotion.promote(candidate, dry_run=False)

    assert _git(repository, "rev-parse", "HEAD").stdout.strip().lower() == independent_sha
