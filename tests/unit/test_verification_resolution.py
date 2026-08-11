"""F4.6 contract tests for configured, worktree-bound command resolution."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from ai_engineering_harness.security import PathGuard
from ai_engineering_harness.verification import (
    VerificationConfigurationError,
    VerificationEngine,
    VerificationPrerequisiteError,
)
from ai_engineering_harness.verification.resolver import VerificationCommandResolver
from ai_engineering_harness.workspace import (
    ExternalWorktreeManager,
    ProvisionedWorktree,
    WorktreeReference,
    WorktreeStatus,
)

_SHA = "a" * 40
_TIMESTAMP = "2026-08-11T05:00:00+00:00"


def _provisioned(root: Path) -> ProvisionedWorktree:
    canonical = root.resolve(strict=True)
    reference = WorktreeReference(
        execution_id="exec-f46",
        project_id="project-f46",
        project_root=canonical,
        worktree_path=canonical,
        base_commit_sha=_SHA,
        original_branch="main",
        worktree_branch="harness/exec-f46",
        worktree_head_sha=_SHA,
        status=WorktreeStatus.ACTIVE,
        failure_code=None,
        created_at=_TIMESTAMP,
        updated_at=_TIMESTAMP,
    )
    return ProvisionedWorktree(reference=reference, path_guard=PathGuard(canonical))


def _write_python_project(root: Path, *, security: bool = False) -> None:
    bandit = "\n[tool.bandit]\nexclude_dirs = ['tests']\n" if security else ""
    (root / "pyproject.toml").write_text(
        """
[build-system]
requires = ["setuptools>=61"]
build-backend = "setuptools.build_meta"

[project]
name = "sample"
version = "0.1.0"

[project.optional-dependencies]
dev = ["pytest>=8", "mypy>=1", "ruff>=0.11"]

[tool.pytest.ini_options]
addopts = "-p no:cacheprovider"

[tool.mypy]
python_version = "3.11"

[tool.ruff]
line-length = 100
""".strip()
        + bandit
        + "\n",
        encoding="utf-8",
    )


def _git(project: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments],
        cwd=project,
        check=True,
        shell=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )


def _initialize_repository(project: Path) -> None:
    project.mkdir()
    _git(project, "init", "-b", "main")
    _git(project, "config", "user.name", "F4.6 Test")
    _git(project, "config", "user.email", "f46@example.invalid")
    (project / ".gitignore").write_text(
        ".harness/\n.pytest_cache/\n__pycache__/\n*.pyc\n", encoding="utf-8"
    )
    _write_python_project(project)
    tests = project / "tests"
    tests.mkdir()
    (tests / "test_sample.py").write_text(
        "def test_sample() -> None:\n    assert True\n", encoding="utf-8"
    )
    _git(project, "add", ".")
    _git(project, "commit", "-m", "initial")


def test_engine_resolves_python_tools_from_pyproject_before_effects(tmp_path: Path) -> None:
    _write_python_project(tmp_path)
    engine = VerificationEngine(_provisioned(tmp_path))

    suite = engine.resolve(["typecheck", "lint", "unit_test", "build"])

    assert suite.worktree_root == tmp_path.resolve()
    assert suite.stack.language == "python"
    assert tuple(command.gate_id for command in suite.commands) == (
        "typecheck",
        "lint",
        "unit_test",
        "build",
    )
    assert tuple(command.argv for command in suite.commands) == (
        ("python", "-m", "mypy", "."),
        ("python", "-m", "ruff", "check", "."),
        ("python", "-m", "pytest"),
        ("python", "-m", "build"),
    )
    assert all(command.cwd == "." for command in suite.commands)
    assert all(
        command.executable_path == Path(os.path.abspath(sys.executable))
        for command in suite.commands
    )
    assert all(command.source.startswith("pyproject.toml:") for command in suite.commands)


def test_python_executable_does_not_dereference_launcher(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = Path(os.path.abspath(sys.executable))

    def unexpected_resolve(*_args: object, **_kwargs: object) -> Path:
        raise AssertionError("the Python launcher path must not be dereferenced")

    monkeypatch.setattr(Path, "resolve", unexpected_resolve)

    assert VerificationCommandResolver._python_executable() == expected


@pytest.mark.skipif(os.name == "nt", reason="POSIX venv launchers are symlinks")
def test_python_executable_preserves_real_posix_symlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_executable = Path(sys.executable).resolve(strict=True)
    launcher = tmp_path / "venv-python"
    launcher.symlink_to(base_executable)
    monkeypatch.setattr(sys, "executable", str(launcher))

    resolved = VerificationCommandResolver._python_executable()

    assert resolved == launcher.absolute()
    assert resolved != base_executable


@pytest.mark.parametrize(
    "active_gates",
    [[], ["unknown"], ["tests"], ["lint", "lint"]],
)
def test_invalid_suite_fails_before_detector_or_terminal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    active_gates: list[str],
) -> None:
    _write_python_project(tmp_path)
    engine = VerificationEngine(_provisioned(tmp_path))

    def unexpected_detect():
        raise AssertionError("suite validation must precede stack detection")

    def unexpected_adapter(_suite):
        raise AssertionError("suite validation must precede terminal policy")

    monkeypatch.setattr(engine.runner.resolver._detector, "detect", unexpected_detect)
    monkeypatch.setattr(engine.runner, "_adapter_for_suite", unexpected_adapter)

    with pytest.raises(VerificationConfigurationError):
        engine.verify(active_gates)


def test_missing_required_tool_is_error_prerequisite_before_any_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_python_project(tmp_path, security=True)
    engine = VerificationEngine(_provisioned(tmp_path))
    probed: list[str] = []

    def module_available(module: str) -> bool:
        probed.append(module)
        return module != "bandit"

    def unexpected_adapter(_suite):
        raise AssertionError("missing prerequisite must prevent every terminal effect")

    monkeypatch.setattr(engine.runner.resolver, "_python_module_available", module_available)
    monkeypatch.setattr(engine.runner, "_adapter_for_suite", unexpected_adapter)

    with pytest.raises(VerificationPrerequisiteError) as exc_info:
        engine.verify(["lint", "security_scan"])

    assert exc_info.value.code == "ERROR_PREREQUISITE"
    assert exc_info.value.gate_id == "security_scan"
    assert probed == ["ruff", "bandit"]


def test_required_gate_without_project_configuration_is_error_prerequisite(
    tmp_path: Path,
) -> None:
    _write_python_project(tmp_path)
    engine = VerificationEngine(_provisioned(tmp_path))

    with pytest.raises(VerificationPrerequisiteError) as exc_info:
        engine.resolve(["security_scan"])

    assert exc_info.value.code == "ERROR_PREREQUISITE"
    assert exc_info.value.gate_id == "security_scan"
    assert "no configured command" in str(exc_info.value)


def test_engine_rejects_path_guard_not_bound_to_worktree(tmp_path: Path) -> None:
    root = tmp_path / "worktree"
    other = tmp_path / "other"
    root.mkdir()
    other.mkdir()
    provisioned = _provisioned(root)
    mismatched = ProvisionedWorktree(
        reference=provisioned.reference,
        path_guard=PathGuard(other),
    )

    with pytest.raises(VerificationConfigurationError, match="must match"):
        VerificationEngine(mismatched)


def test_engine_rejects_non_active_worktree(tmp_path: Path) -> None:
    provisioned = _provisioned(tmp_path)
    inactive_reference = replace(
        provisioned.reference,
        status=WorktreeStatus.REMOVED,
    )

    with pytest.raises(VerificationConfigurationError, match="ACTIVE"):
        VerificationEngine(
            ProvisionedWorktree(
                reference=inactive_reference,
                path_guard=provisioned.path_guard,
            )
        )


def test_gate_executes_inside_real_external_git_worktree(tmp_path: Path) -> None:
    project = tmp_path / "project"
    external = tmp_path / "external"
    _initialize_repository(project)
    manager = ExternalWorktreeManager(
        project,
        project_id="f46-project",
        external_base_dir=external,
    )
    worktree = manager.create_worktree("f46-execution")

    try:
        result = VerificationEngine(worktree).verify(["unit_test"])
        assert result.all_passed is True
        assert result.total_gates == 1
        assert result.passed_gates == 1
        assert result.gate_results[0].command == "python -m pytest"
        assert "1 passed" in result.gate_results[0].stdout
        assert not (project / ".pytest_cache").exists()
    finally:
        for cache in tuple(worktree.worktree_path.rglob("__pycache__")):
            shutil.rmtree(cache)
        manager.cleanup_worktree("f46-execution")


def test_engine_constructor_no_longer_accepts_caller_selected_language_or_cwd(
    tmp_path: Path,
) -> None:
    with pytest.raises(TypeError):
        VerificationEngine(language="python", working_dir=tmp_path)  # type: ignore[call-arg]
