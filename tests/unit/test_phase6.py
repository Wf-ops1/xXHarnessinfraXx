"""Testes unitários para a Fase 6 (Runtime, FSM, Approval e Migrations)."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ai_engineering_harness.compiler.compiler import GraphCompiler
from ai_engineering_harness.contracts.execution import ExecutionState
from ai_engineering_harness.governance.approval import (
    ApprovalContent,
    ApprovalGateResult,
    ApprovalManager,
    ApprovalRequest,
)
from ai_engineering_harness.runtime.engine import (
    RuntimeEngine,
    RuntimeGraphConfigurationError,
)
from ai_engineering_harness.runtime.state_machine import WorkflowState, WorkflowStateMachine


def _write_runtime_graph(project_root: Path, workflow_name: str) -> Path:
    graph_path = project_root / "graph.yaml"
    graph_path.write_text(
        f"""
graph:
  name: {workflow_name}
  graph_schema_version: "1.0"
  definition_version: "1.0.0"
  entrypoint: step1
  status: stable
nodes:
  - id: step1
    type: deterministic
    executor: deterministic_gate
    gate_name: test
    on_success: completed
    on_failure: failed
terminal_states:
  - id: completed
    outcome: success
  - id: failed
    outcome: failure
policies: []
contracts: []
""",
        encoding="utf-8",
    )
    return graph_path


def test_workflow_state_machine_transitions(tmp_path: Path):
    assert WorkflowState is ExecutionState
    with pytest.raises(TypeError, match="EventJournalStateStorageProvider"):
        WorkflowStateMachine(tmp_path, "exec-111")
    state_file = (
        tmp_path
        / ".harness"
        / "state"
        / "executions"
        / "exec-111"
        / "workflow-state.json"
    )
    assert not state_file.exists()

def test_approval_manager_flow(tmp_path: Path):
    execution_id = "exec-222"
    execution_directory = tmp_path / ".harness" / "state" / "executions" / execution_id
    execution_directory.mkdir(parents=True)
    mgr = ApprovalManager(project_root=tmp_path)
    requested_at = datetime(2026, 8, 14, tzinfo=UTC)
    request = ApprovalRequest.pending(
        content=ApprovalContent(
            execution_id=execution_id,
            artifact_digest="sha256:" + "1" * 64,
            plan_digest="sha256:" + "2" * 64,
            diff_digest="sha256:" + "3" * 64,
            candidate_commit_sha="4" * 40,
            gate_results=(
                ApprovalGateResult(
                    gate_id="unit_test",
                    required=True,
                    status="PASSED",
                    result_digest="sha256:" + "5" * 64,
                ),
            ),
            verification_suite_digest="sha256:" + "6" * 64,
        ),
        reason="Precisa aprovação",
        requested_at=requested_at,
        expires_at=requested_at + timedelta(hours=1),
    )
    req_file = mgr.publish(request)
    assert req_file.is_file()

    approved = request.approve(
        approver_id="phase6-reviewer",
        decided_at=requested_at + timedelta(minutes=5),
    )
    mgr.publish(approved)
    assert mgr.load(execution_id) == approved

def test_runtime_engine_with_approval(tmp_path: Path):
    # Compilar grafo primeiro
    yaml_spec = _write_runtime_graph(tmp_path, "test_flow")
    compiler = GraphCompiler(project_root=tmp_path)
    compiled_maf = compiler.compile_graph(yaml_spec, "test_flow")

    engine = RuntimeEngine(project_root=tmp_path, execution_id="exec-333", allowed_providers=["local"])
    with pytest.raises(RuntimeGraphConfigurationError, match="F2.4/F2.5"):
        engine.run_workflow(compiled_maf, approval_required=True)

    execution_dir = tmp_path / ".harness" / "state" / "executions" / "exec-333"
    assert not execution_dir.exists()
