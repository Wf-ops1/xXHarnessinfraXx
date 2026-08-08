"""Testes unitários para a Fase 5 (Graph Compiler & Verification Engine)."""

import json
from pathlib import Path

import pytest

from ai_engineering_harness.compiler import GraphCompiler, GraphValidationError
from ai_engineering_harness.contracts import CompiledGraphArtifact
from ai_engineering_harness.verification.engine import VerificationEngine
from ai_engineering_harness.verification.evaluator import VerificationEvaluator
from ai_engineering_harness.versioning import ARTIFACT_SCHEMA_VERSION, PACKAGE_VERSION


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

def test_verification_evaluator_polyglot():
    assert VerificationEvaluator.get_argv("python", "unit_test") == ("pytest",)
    assert VerificationEvaluator.get_argv("ts", "lint") == ("eslint", ".")
    assert VerificationEvaluator.get_argv("golang", "typecheck") == ("go", "vet", "./...")

    py_cmd = VerificationEvaluator.get_command("python", "unit_test")
    assert py_cmd == "pytest"

    ts_cmd = VerificationEvaluator.get_command("typescript/javascript", "lint")
    assert ts_cmd == "eslint ."

    go_cmd = VerificationEvaluator.get_command("go", "typecheck")
    assert go_cmd == "go vet ./..."

def test_verification_engine_run(tmp_path: Path):
    engine = VerificationEngine(language="python", working_dir=tmp_path)
    # Gates aplicáveis para Python
    res = engine.verify(active_gates=["typecheck", "unit_test"])
    assert res.total_gates == 2
