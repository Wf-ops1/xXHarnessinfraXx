"""Real Git integration tests for the F3.6 external worktree boundary."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import ai_engineering_harness.workspace.git_worktree as git_worktree_module
from ai_engineering_harness.workspace import (
    BaseCommitMismatchError,
    DetachedHeadError,
    DirtyRepositoryError,
    DirtyWorktreeError,
    ExternalWorktreeManager,
    GitCommandError,
    GitUnavailableError,
    InvalidGitRepositoryError,
    WorktreeCollisionError,
    WorktreeConfigurationError,
    WorktreeReferenceError,
    WorktreeStatus,
    WorktreeValidationError,
)


def _git(repo: Path, *arguments: str, expected: tuple[int, ...] = (0,)) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", *arguments],
        cwd=repo,
        check=False,
        shell=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    assert result.returncode in expected, result.stderr
    return result


def _repository(tmp_path: Path, *, name: str = "repo") -> tuple[Path, str]:
    repo = tmp_path / name
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Harness Tests")
    _git(repo, "config", "user.email", "harness-tests@example.invalid")
    (repo / ".gitignore").write_text(".harness/state/worktree-references/\n", encoding="utf-8")
    (repo / "tracked.txt").write_text("baseline\n", encoding="utf-8")
    _git(repo, "add", "--", ".gitignore", "tracked.txt")
    _git(repo, "commit", "-m", "baseline")
    head = _git(repo, "rev-parse", "HEAD").stdout.strip().lower()
    return repo, head


def _manager(repo: Path, tmp_path: Path, *, project_id: str = "project-1") -> ExternalWorktreeManager:
    return ExternalWorktreeManager(
        repo,
        project_id=project_id,
        external_base_dir=tmp_path / "external" / project_id,
    )


def _reference_path(repo: Path, execution_id: str) -> Path:
    return repo / ".harness" / "state" / "worktree-references" / f"{execution_id}.json"


def test_create_real_worktree_persists_identity_and_instantiates_guard(tmp_path: Path) -> None:
    repo, base_sha = _repository(tmp_path)
    manager = _manager(repo, tmp_path)

    provisioned = manager.create_worktree("exec-777", expected_base_commit_sha=base_sha.upper())

    assert provisioned.worktree_path.is_dir()
    assert provisioned.worktree_path.resolve() != repo.resolve()
    assert provisioned.path_guard.authorized_root == provisioned.worktree_path.resolve()
    assert provisioned.trust_boundary is not None
    assert Path(provisioned.trust_boundary.repository_root) == repo.resolve()
    assert Path(provisioned.trust_boundary.authorized_root) == provisioned.worktree_path.resolve()
    assert provisioned.reference.status is WorktreeStatus.ACTIVE
    assert provisioned.reference.base_commit_sha == base_sha
    assert provisioned.reference.worktree_head_sha == base_sha
    assert provisioned.reference.original_branch == "main"
    assert provisioned.reference.worktree_branch == "harness/exec-777"
    assert _git(provisioned.worktree_path, "rev-parse", "HEAD").stdout.strip().lower() == base_sha
    assert _git(provisioned.worktree_path, "branch", "--show-current").stdout.strip() == "harness/exec-777"
    assert Path(_git(provisioned.worktree_path, "rev-parse", "--show-toplevel").stdout.strip()).resolve() == (
        provisioned.worktree_path.resolve()
    )
    assert _git(repo, "rev-parse", "HEAD").stdout.strip().lower() == base_sha
    assert _git(repo, "branch", "--show-current").stdout.strip() == "main"
    assert _git(repo, "status", "--porcelain=v1", "--untracked-files=all").stdout == ""

    payload = json.loads(_reference_path(repo, "exec-777").read_text(encoding="utf-8"))
    assert payload == provisioned.reference.to_dict()
    reopened = manager.load_worktree("exec-777")
    assert reopened.reference == provisioned.reference
    assert reopened.path_guard.authorized_root == provisioned.worktree_path.resolve()
    assert reopened.trust_boundary == provisioned.trust_boundary


def test_create_retry_recovers_after_active_publication_interruption(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, base_sha = _repository(tmp_path)
    manager = _manager(repo, tmp_path)
    real_write_reference = manager._write_reference
    real_run_git = manager._run_git
    add_calls = 0
    interrupt_active = True

    def recording_run_git(
        arguments: tuple[str, ...],
        *,
        cwd: Path,
        allowed_returncodes: tuple[int, ...] = (0,),
    ) -> subprocess.CompletedProcess[str]:
        nonlocal add_calls
        if arguments[:2] == ("worktree", "add"):
            add_calls += 1
        return real_run_git(arguments, cwd=cwd, allowed_returncodes=allowed_returncodes)

    def interrupted_write(reference: git_worktree_module.WorktreeReference) -> None:
        nonlocal interrupt_active
        if reference.status is WorktreeStatus.ACTIVE and interrupt_active:
            interrupt_active = False
            raise WorktreeReferenceError("injected ACTIVE publication interruption")
        real_write_reference(reference)

    monkeypatch.setattr(manager, "_run_git", recording_run_git)
    monkeypatch.setattr(manager, "_write_reference", interrupted_write)

    with pytest.raises(WorktreeReferenceError, match="injected ACTIVE"):
        manager.create_worktree("exec-recover-after-effect")

    reference_path = _reference_path(repo, "exec-recover-after-effect")
    interrupted = json.loads(reference_path.read_text(encoding="utf-8"))
    assert interrupted["status"] == "CREATING"
    assert Path(interrupted["worktree_path"]).is_dir()
    assert add_calls == 1

    recovered = manager.create_worktree("exec-recover-after-effect")
    repeated = manager.create_worktree("exec-recover-after-effect")

    assert recovered.reference.status is WorktreeStatus.ACTIVE
    assert recovered.reference.worktree_head_sha == base_sha
    assert repeated.reference == recovered.reference
    assert add_calls == 1
    assert _git(repo, "rev-parse", "refs/heads/harness/exec-recover-after-effect").stdout.strip() == base_sha


def test_create_retry_continues_creating_reference_before_git_effect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, base_sha = _repository(tmp_path)
    manager = _manager(repo, tmp_path)
    real_run_git = manager._run_git
    interrupt_before_effect = True

    def interrupted_run_git(
        arguments: tuple[str, ...],
        *,
        cwd: Path,
        allowed_returncodes: tuple[int, ...] = (0,),
    ) -> subprocess.CompletedProcess[str]:
        nonlocal interrupt_before_effect
        if arguments[:2] == ("worktree", "add") and interrupt_before_effect:
            interrupt_before_effect = False
            raise KeyboardInterrupt
        return real_run_git(arguments, cwd=cwd, allowed_returncodes=allowed_returncodes)

    monkeypatch.setattr(manager, "_run_git", interrupted_run_git)

    with pytest.raises(KeyboardInterrupt):
        manager.create_worktree("exec-recover-before-effect")

    interrupted = json.loads(
        _reference_path(repo, "exec-recover-before-effect").read_text(encoding="utf-8")
    )
    assert interrupted["status"] == "CREATING"
    assert not Path(interrupted["worktree_path"]).exists()

    recovered = manager.create_worktree("exec-recover-before-effect")

    assert recovered.reference.status is WorktreeStatus.ACTIVE
    assert recovered.reference.worktree_head_sha == base_sha


def test_create_retry_rejects_partial_creating_effect_without_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, _ = _repository(tmp_path)
    manager = _manager(repo, tmp_path)
    real_write_reference = manager._write_reference
    interrupt_active = True

    def interrupted_write(reference: git_worktree_module.WorktreeReference) -> None:
        nonlocal interrupt_active
        if reference.status is WorktreeStatus.ACTIVE and interrupt_active:
            interrupt_active = False
            raise WorktreeReferenceError("injected ACTIVE publication interruption")
        real_write_reference(reference)

    monkeypatch.setattr(manager, "_write_reference", interrupted_write)
    with pytest.raises(WorktreeReferenceError, match="injected ACTIVE"):
        manager.create_worktree("exec-partial")

    worktree_path = tmp_path / "external" / "project-1" / "exec-partial"
    _git(repo, "worktree", "remove", str(worktree_path))
    assert not worktree_path.exists()
    assert _git(repo, "show-ref", "--verify", "refs/heads/harness/exec-partial").returncode == 0

    with pytest.raises(WorktreeValidationError, match="partial Git effect"):
        manager.create_worktree("exec-partial")

    payload = json.loads(_reference_path(repo, "exec-partial").read_text(encoding="utf-8"))
    assert payload["status"] == "CREATING"
    assert _git(repo, "show-ref", "--verify", "refs/heads/harness/exec-partial").returncode == 0


def test_create_retry_rejects_creating_reference_after_base_advances(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, _ = _repository(tmp_path)
    manager = _manager(repo, tmp_path)
    real_run_git = manager._run_git
    interrupt_before_effect = True

    def interrupted_run_git(
        arguments: tuple[str, ...],
        *,
        cwd: Path,
        allowed_returncodes: tuple[int, ...] = (0,),
    ) -> subprocess.CompletedProcess[str]:
        nonlocal interrupt_before_effect
        if arguments[:2] == ("worktree", "add") and interrupt_before_effect:
            interrupt_before_effect = False
            raise KeyboardInterrupt
        return real_run_git(arguments, cwd=cwd, allowed_returncodes=allowed_returncodes)

    monkeypatch.setattr(manager, "_run_git", interrupted_run_git)
    with pytest.raises(KeyboardInterrupt):
        manager.create_worktree("exec-base-advanced")

    (repo / "tracked.txt").write_text("advanced\n", encoding="utf-8")
    _git(repo, "add", "--", "tracked.txt")
    _git(repo, "commit", "-m", "advance base")

    with pytest.raises(WorktreeValidationError, match="identity no longer matches"):
        manager.create_worktree("exec-base-advanced")

    payload = json.loads(_reference_path(repo, "exec-base-advanced").read_text(encoding="utf-8"))
    assert payload["status"] == "CREATING"
    assert not (tmp_path / "external" / "project-1" / "exec-base-advanced").exists()


def test_create_retry_rejects_matching_checkout_from_another_repository(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, base_sha = _repository(tmp_path)
    manager = _manager(repo, tmp_path)
    real_run_git = manager._run_git
    interrupt_before_effect = True

    def interrupted_run_git(
        arguments: tuple[str, ...],
        *,
        cwd: Path,
        allowed_returncodes: tuple[int, ...] = (0,),
    ) -> subprocess.CompletedProcess[str]:
        nonlocal interrupt_before_effect
        if arguments[:2] == ("worktree", "add") and interrupt_before_effect:
            interrupt_before_effect = False
            raise KeyboardInterrupt
        return real_run_git(arguments, cwd=cwd, allowed_returncodes=allowed_returncodes)

    monkeypatch.setattr(manager, "_run_git", interrupted_run_git)
    with pytest.raises(KeyboardInterrupt):
        manager.create_worktree("exec-foreign-repo")

    worktree_path = tmp_path / "external" / "project-1" / "exec-foreign-repo"
    _git(repo, "branch", "harness/exec-foreign-repo", base_sha)
    _git(tmp_path, "clone", str(repo), str(worktree_path))
    _git(worktree_path, "checkout", "-b", "harness/exec-foreign-repo", base_sha)

    with pytest.raises(WorktreeValidationError, match="different Git repository"):
        manager.create_worktree("exec-foreign-repo")

    payload = json.loads(_reference_path(repo, "exec-foreign-repo").read_text(encoding="utf-8"))
    assert payload["status"] == "CREATING"
    assert worktree_path.is_dir()
    assert _git(repo, "show-ref", "--verify", "refs/heads/harness/exec-foreign-repo").returncode == 0


def test_cleanup_is_explicit_non_forced_and_preserves_branch(tmp_path: Path) -> None:
    repo, base_sha = _repository(tmp_path)
    manager = _manager(repo, tmp_path)
    provisioned = manager.create_worktree("exec-clean")

    removed = manager.cleanup_worktree("exec-clean")

    assert removed.status is WorktreeStatus.REMOVED
    assert not provisioned.worktree_path.exists()
    assert _git(repo, "rev-parse", "refs/heads/harness/exec-clean").stdout.strip().lower() == base_sha
    assert _git(repo, "rev-parse", "HEAD").stdout.strip().lower() == base_sha
    assert json.loads(_reference_path(repo, "exec-clean").read_text(encoding="utf-8"))["status"] == "REMOVED"
    assert manager.cleanup_worktree("exec-clean") == removed


def test_cleanup_refuses_dirty_worktree_and_keeps_active_reference(tmp_path: Path) -> None:
    repo, _ = _repository(tmp_path)
    manager = _manager(repo, tmp_path)
    provisioned = manager.create_worktree("exec-dirty")
    (provisioned.worktree_path / "tracked.txt").write_text("changed\n", encoding="utf-8")

    with pytest.raises(DirtyWorktreeError, match="non-forced cleanup refused"):
        manager.cleanup_worktree("exec-dirty")

    assert provisioned.worktree_path.exists()
    assert json.loads(_reference_path(repo, "exec-dirty").read_text(encoding="utf-8"))["status"] == "ACTIVE"


def test_non_repository_fails_before_external_or_reference_effect(tmp_path: Path) -> None:
    project = tmp_path / "not-a-repo"
    project.mkdir()
    external = tmp_path / "external"
    manager = ExternalWorktreeManager(project, external_base_dir=external)

    with pytest.raises(InvalidGitRepositoryError):
        manager.create_worktree("exec-invalid")

    assert not external.exists()
    assert not _reference_path(project, "exec-invalid").exists()


def test_repository_without_a_commit_is_not_a_valid_base(tmp_path: Path) -> None:
    repo = tmp_path / "empty-repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    manager = _manager(repo, tmp_path)

    with pytest.raises(InvalidGitRepositoryError, match="valid base commit"):
        manager.create_worktree("exec-empty")

    assert not _reference_path(repo, "exec-empty").exists()


def test_project_root_must_be_exact_git_toplevel(tmp_path: Path) -> None:
    repo, _ = _repository(tmp_path)
    nested = repo / "nested"
    nested.mkdir()
    manager = ExternalWorktreeManager(nested, external_base_dir=tmp_path / "external")

    with pytest.raises(InvalidGitRepositoryError, match="exact Git top-level"):
        manager.create_worktree("exec-nested")


def test_dirty_original_checkout_fails_before_effect(tmp_path: Path) -> None:
    repo, _ = _repository(tmp_path)
    (repo / "untracked.txt").write_text("dirty\n", encoding="utf-8")
    manager = _manager(repo, tmp_path)

    with pytest.raises(DirtyRepositoryError):
        manager.create_worktree("exec-dirty-root")

    assert not (tmp_path / "external").exists()
    assert not _reference_path(repo, "exec-dirty-root").exists()


def test_detached_original_head_fails_before_effect(tmp_path: Path) -> None:
    repo, head = _repository(tmp_path)
    _git(repo, "checkout", "--detach", head)
    manager = _manager(repo, tmp_path)

    with pytest.raises(DetachedHeadError):
        manager.create_worktree("exec-detached")

    assert not _reference_path(repo, "exec-detached").exists()


def test_expected_base_sha_is_a_strict_precondition(tmp_path: Path) -> None:
    repo, _ = _repository(tmp_path)
    manager = _manager(repo, tmp_path)

    with pytest.raises(BaseCommitMismatchError):
        manager.create_worktree("exec-mismatch", expected_base_commit_sha="0" * 40)
    with pytest.raises(WorktreeConfigurationError):
        manager.create_worktree("exec-short", expected_base_commit_sha="abc123")

    assert not _reference_path(repo, "exec-mismatch").exists()
    assert not _reference_path(repo, "exec-short").exists()


@pytest.mark.parametrize(
    "execution_id",
    ("../escape", "nested/name", "nested\\name", "-option", "exec..bad", "branch.lock", ""),
)
def test_execution_id_cannot_escape_path_or_branch(tmp_path: Path, execution_id: str) -> None:
    repo, _ = _repository(tmp_path)
    manager = _manager(repo, tmp_path)

    with pytest.raises(WorktreeConfigurationError):
        manager.create_worktree(execution_id)


def test_project_id_cannot_escape_sandbox_path(tmp_path: Path) -> None:
    repo, _ = _repository(tmp_path)

    with pytest.raises(WorktreeConfigurationError):
        ExternalWorktreeManager(repo, project_id="../escape")


def test_external_base_must_be_outside_project_root(tmp_path: Path) -> None:
    repo, _ = _repository(tmp_path)
    internal_base = repo / ".harness" / "worktrees"
    manager = ExternalWorktreeManager(repo, external_base_dir=internal_base)

    with pytest.raises(WorktreeConfigurationError, match="outside project_root"):
        manager.create_worktree("exec-internal")

    assert not internal_base.exists()


def test_existing_branch_path_or_reference_never_gets_reused(tmp_path: Path) -> None:
    repo, head = _repository(tmp_path)
    manager = _manager(repo, tmp_path)
    _git(repo, "branch", "harness/exec-branch", head)

    with pytest.raises(WorktreeCollisionError, match="branch"):
        manager.create_worktree("exec-branch")

    external_path = tmp_path / "external" / "project-1" / "exec-path"
    external_path.mkdir(parents=True)
    with pytest.raises(WorktreeCollisionError, match="path"):
        manager.create_worktree("exec-path")

    reference_path = _reference_path(repo, "exec-reference")
    reference_path.parent.mkdir(parents=True, exist_ok=True)
    reference_path.write_text("preserve-me\n", encoding="utf-8")
    with pytest.raises(WorktreeCollisionError, match="reference"):
        manager.create_worktree("exec-reference")
    assert reference_path.read_text(encoding="utf-8") == "preserve-me\n"


def test_git_unavailable_is_explicit_and_has_no_state_effect(tmp_path: Path) -> None:
    repo, _ = _repository(tmp_path)
    manager = ExternalWorktreeManager(
        repo,
        external_base_dir=tmp_path / "external",
        git_executable="git-command-that-does-not-exist-f3-6",
    )

    with pytest.raises(GitUnavailableError):
        manager.create_worktree("exec-no-git")

    assert not (tmp_path / "external").exists()
    assert not _reference_path(repo, "exec-no-git").exists()


def test_tampered_reference_and_advanced_head_fail_closed(tmp_path: Path) -> None:
    repo, _ = _repository(tmp_path)
    manager = _manager(repo, tmp_path)
    provisioned = manager.create_worktree("exec-tamper")
    reference_path = _reference_path(repo, "exec-tamper")
    payload = json.loads(reference_path.read_text(encoding="utf-8"))
    payload["unexpected"] = True
    reference_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(WorktreeReferenceError, match="fields"):
        manager.load_worktree("exec-tamper")

    payload = provisioned.reference.to_dict()
    payload["worktree_path"] = str(tmp_path / "external" / "project-1" / "another-execution")
    reference_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    with pytest.raises(WorktreeReferenceError, match="path does not match"):
        manager.load_worktree("exec-tamper")

    reference_path.write_text(json.dumps(provisioned.reference.to_dict(), sort_keys=True), encoding="utf-8")
    (provisioned.worktree_path / "candidate.txt").write_text("candidate\n", encoding="utf-8")
    _git(provisioned.worktree_path, "add", "--", "candidate.txt")
    _git(provisioned.worktree_path, "commit", "-m", "candidate")
    with pytest.raises(WorktreeValidationError, match="HEAD"):
        manager.load_worktree("exec-tamper")


def test_all_git_commands_are_argv_shell_false_and_bounded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, base_sha = _repository(tmp_path)
    manager = _manager(repo, tmp_path)
    real_run = subprocess.run
    observed: list[tuple[list[str], dict[str, object]]] = []

    def recording_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        observed.append((argv, kwargs))
        return real_run(argv, **kwargs)  # type: ignore[arg-type, return-value]

    monkeypatch.setattr(git_worktree_module.subprocess, "run", recording_run)
    provisioned = manager.create_worktree("exec-argv")

    assert observed
    assert all(type(argv) is list for argv, _ in observed)
    assert all(kwargs["shell"] is False for _, kwargs in observed)
    assert all(kwargs["timeout"] == 30.0 for _, kwargs in observed)
    assert [
        "git",
        "worktree",
        "add",
        "-b",
        "harness/exec-argv",
        str(provisioned.worktree_path),
        base_sha,
    ] in [argv for argv, _ in observed]


def test_controlled_git_add_failure_is_durable_and_never_active(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, _ = _repository(tmp_path)
    manager = _manager(repo, tmp_path)
    real_run = subprocess.run

    def failing_add(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if argv[1:3] == ["worktree", "add"]:
            return subprocess.CompletedProcess(argv, 17, stdout="", stderr="injected failure")
        return real_run(argv, **kwargs)  # type: ignore[arg-type, return-value]

    monkeypatch.setattr(git_worktree_module.subprocess, "run", failing_add)
    with pytest.raises(GitCommandError, match="exit code 17"):
        manager.create_worktree("exec-failed")

    payload = json.loads(_reference_path(repo, "exec-failed").read_text(encoding="utf-8"))
    assert payload["status"] == "FAILED"
    assert payload["failure_code"] == "GitCommandError"
    assert not (tmp_path / "external" / "project-1" / "exec-failed").exists()


def test_duplicate_json_keys_are_rejected(tmp_path: Path) -> None:
    repo, _ = _repository(tmp_path)
    manager = _manager(repo, tmp_path)
    manager.create_worktree("exec-duplicate")
    reference_path = _reference_path(repo, "exec-duplicate")
    reference_path.write_text('{"execution_id":"a","execution_id":"b"}', encoding="utf-8")

    with pytest.raises(WorktreeReferenceError, match="duplicate JSON keys"):
        manager.load_worktree("exec-duplicate")
