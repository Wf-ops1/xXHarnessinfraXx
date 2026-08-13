"""Testes unitários para a Fase 5 (Graph Compiler & Verification Engine)."""

import json
from pathlib import Path

import pytest

from ai_engineering_harness.compiler import GraphCompiler, GraphValidationError
from ai_engineering_harness.contracts import (
    CANONICAL_VERIFICATION_GATE_IDS,
    CompiledGraphArtifact,
)
from ai_engineering_harness.core.detector import StackDetector
from ai_engineering_harness.security import (
    PathGuard,
    SecretGrant,
    TrustAuthorization,
    TrustBoundaryEvaluator,
)
from ai_engineering_harness.verification import VerificationConfigurationError
from ai_engineering_harness.verification.engine import VerificationEngine
from ai_engineering_harness.verification.evaluator import VerificationEvaluator
from ai_engineering_harness.versioning import ARTIFACT_SCHEMA_VERSION, PACKAGE_VERSION
from ai_engineering_harness.workspace import (
    ProvisionedWorktree,
    WorktreeReference,
    WorktreeStatus,
)


def _verification_worktree(root: Path) -> ProvisionedWorktree:
    (root / "pyproject.toml").write_text(
        """
[build-system]
requires = ["setuptools>=61"]
build-backend = "setuptools.build_meta"
[project]
name = "sample"
version = "0.1.0"
[project.optional-dependencies]
dev = ["pytest", "mypy", "ruff"]
[tool.pytest.ini_options]
addopts = "-p no:cacheprovider"
[tool.mypy]
python_version = "3.11"
[tool.ruff]
line-length = 100
""".strip()
        + "\n",
        encoding="utf-8",
    )
    resolved = root.resolve(strict=True)
    sha = "b" * 40
    reference = WorktreeReference(
        execution_id="phase5",
        project_id="phase5",
        project_root=resolved,
        worktree_path=resolved,
        base_commit_sha=sha,
        original_branch="main",
        worktree_branch="harness/phase5",
        worktree_head_sha=sha,
        status=WorktreeStatus.ACTIVE,
        failure_code=None,
        created_at="2026-08-11T05:00:00+00:00",
        updated_at="2026-08-11T05:00:00+00:00",
    )
    boundary = TrustBoundaryEvaluator(
        resolved,
        authorization=TrustAuthorization(
            repository_root=str(resolved),
            executable_aliases=("python",),
            secret_grants=tuple(
                SecretGrant(name=name, consumers=("terminal:python",))
                for name in ("PATH", "Path", "SYSTEMROOT", "SystemRoot")
            ),
        ),
    ).evaluate()
    return ProvisionedWorktree(
        reference=reference,
        path_guard=PathGuard(resolved),
        trust_boundary=boundary,
    )


def test_compiler_governed_loops_success(tmp_path: Path):
    yaml_spec = tmp_path / "valid_graph.yaml"
    yaml_spec.write_text("""
graph:
  name: valid_workflow
  graph_schema_version: "1.0"
  definition_version: "1.0.0"
  entrypoint: step1
  status: stable
nodes:
  - id: step1
    type: deterministic
    executor: deterministic_gate
    gate_name: tests_passed
    on_success: completed
    on_failure: step1
    retry_policy:
      max_iterations: 3
      exit_condition: all_required_gates_passed
terminal_states:
  - id: completed
    outcome: success
  - id: failed
    outcome: failure
policies: []
contracts: []
""", encoding="utf-8")

    compiler = GraphCompiler(project_root=tmp_path)
    output = compiler.compile_graph(yaml_spec, "valid_workflow")
    assert output.is_file()

    compiled_data = json.loads(output.read_text(encoding="utf-8"))
    artifact = CompiledGraphArtifact.model_validate(compiled_data)
    assert artifact.graph.graph.name == "valid_workflow"
    assert artifact.artifact_schema_version == ARTIFACT_SCHEMA_VERSION
    assert artifact.package_version == PACKAGE_VERSION
    assert "header" not in compiled_data

def test_compiler_ungoverned_loop_rejection(tmp_path: Path):
    yaml_spec = tmp_path / "invalid_graph.yaml"
    yaml_spec.write_text("""
graph:
  name: invalid_workflow
  graph_schema_version: "1.0"
  definition_version: "1.0.0"
  entrypoint: step1
  status: stable
nodes:
  - id: step1
    type: deterministic
    executor: deterministic_gate
    gate_name: tests_passed
    on_success: completed
    on_failure: step1
terminal_states:
  - id: completed
    outcome: success
  - id: failed
    outcome: failure
policies: []
contracts: []
""", encoding="utf-8")

    compiler = GraphCompiler(project_root=tmp_path)
    with pytest.raises(GraphValidationError) as exc_info:
        compiler.compile_graph(yaml_spec, "invalid_workflow")
    assert "retry_policy" in str(exc_info.value)

def test_verification_evaluator_uses_detected_configuration(tmp_path: Path):
    assert VerificationEvaluator.canonical_gate_ids() == CANONICAL_VERIFICATION_GATE_IDS
    assert CANONICAL_VERIFICATION_GATE_IDS == (
        "typecheck",
        "lint",
        "unit_test",
        "build",
        "security_scan",
    )
    _verification_worktree(tmp_path)
    stack = StackDetector(tmp_path).detect()
    command = VerificationEvaluator.configured_command(stack, "unit_test")
    assert command is not None
    assert command.tool == "pytest"
    assert command.argv_tail == ("-m", "pytest")
    assert VerificationEvaluator.configured_command(stack, "security_scan") is None
    assert VerificationEvaluator.configured_command(stack, "tests") is None


@pytest.mark.parametrize(
    "active_gates",
    [
        [],
        ["unknown"],
        ["tests"],
        ["lint", "lint"],
        ["security_scan"],
    ],
)
def test_verification_runner_rejects_unexecutable_suite_before_effects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    active_gates: list[str],
) -> None:
    engine = VerificationEngine(_verification_worktree(tmp_path))

    def unexpected_adapter(_suite):
        raise AssertionError("configuration errors must fail before terminal effects")

    monkeypatch.setattr(engine.runner, "_adapter_for_suite", unexpected_adapter)

    with pytest.raises(VerificationConfigurationError):
        engine.verify(active_gates=active_gates)


def test_verification_runner_rejects_gate_without_configured_command(tmp_path: Path) -> None:
    engine = VerificationEngine(_verification_worktree(tmp_path))

    with pytest.raises(VerificationConfigurationError, match="no configured command"):
        engine.verify(active_gates=["security_scan"])

def test_verification_engine_run(tmp_path: Path):
    engine = VerificationEngine(_verification_worktree(tmp_path))
    suite = engine.resolve(active_gates=["typecheck", "unit_test"])
    assert tuple(command.gate_id for command in suite.commands) == (
        "typecheck",
        "unit_test",
    )
