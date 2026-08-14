"""Testes unitários para a narrativa agent-centric e componentes do novo ciclo."""

import json
import subprocess
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from ai_engineering_harness.cli.commands.rollback import RollbackManager
from ai_engineering_harness.compiler.compiler import GraphCompiler
from ai_engineering_harness.contracts.execution import ExecutionState
from ai_engineering_harness.contracts.nodes import RetrievalRequest
from ai_engineering_harness.contracts.policies import ContextSufficiencyPolicySpec
from ai_engineering_harness.contracts.structural_index import StructuralSymbol
from ai_engineering_harness.indexer import SnapshotManager
from ai_engineering_harness.models.registry import ProviderConfiguration, ProviderRegistry
from ai_engineering_harness.models.router import ModelRouter, ModelRoutingConfigurationError
from ai_engineering_harness.observability.audit import AuditTrailManager
from ai_engineering_harness.persistence import canonical_json_digest, canonical_json_object
from ai_engineering_harness.runtime.agent_executor import AgentExecutor
from ai_engineering_harness.runtime.context_assembler import (
    ContextAssembler,
    ContextPrerequisiteError,
    InsufficientContextError,
)
from ai_engineering_harness.runtime.engine import (
    RuntimeEngine,
    RuntimeGraphConfigurationError,
)
from ai_engineering_harness.runtime.node_executors import ToolEffectDurabilityError
from ai_engineering_harness.runtime.planner import PlanDocument, Planner
from ai_engineering_harness.runtime.state_machine import (
    WorkflowState,
    WorkflowStateMachine,
)
from ai_engineering_harness.tools.router import ToolRouter


def _prepare_structural_snapshot(project_root: Path, *, persist: bool = True) -> str:
    subprocess.run(["git", "init", "--quiet"], cwd=project_root, check=True, shell=False)
    subprocess.run(["git", "config", "user.name", "Context Test"], cwd=project_root, check=True, shell=False)
    subprocess.run(
        ["git", "config", "user.email", "context@example.invalid"],
        cwd=project_root,
        check=True,
        shell=False,
    )
    (project_root / "tracked.py").write_text("def tracked():\n    return True\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.py"], cwd=project_root, check=True, shell=False)
    subprocess.run(["git", "commit", "--quiet", "-m", "fixture"], cwd=project_root, check=True, shell=False)
    commit_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=project_root,
        check=True,
        shell=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip().lower()
    if persist:
        SnapshotManager(project_root).save_snapshot(
            commit_sha,
            [
                StructuralSymbol(
                    kind="function",
                    name="tracked",
                    qualified_name="tracked",
                    path="tracked",
                    line_start=1,
                    line_end=2,
                )
            ],
        )
    return commit_sha


def _context_policy() -> ContextSufficiencyPolicySpec:
    path = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "ai_engineering_harness"
        / "defaults"
        / "policies"
        / "context_sufficiency.yaml"
    )
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return ContextSufficiencyPolicySpec.model_validate(document)


def _write_context_artifacts(project_root: Path) -> None:
    root = project_root / ".harness" / "knowledge" / "artifacts"
    root.mkdir(parents=True, exist_ok=True)
    for artifact_id in (
        "prd",
        "domain_model",
        "non_functional_requirements",
        "acceptance_criteria",
        "architecture",
    ):
        (root / f"{artifact_id}.md").write_text(f"# {artifact_id}\n", encoding="utf-8")


def _assemble_context(project_root: Path, commit_sha: str, execution_id: str):
    policy = _context_policy()
    return ContextAssembler(project_root=project_root).assemble(
        execution_id=execution_id,
        request=RetrievalRequest(
            requirement_id="req-tracked",
            graph_type="new_feature",
            query="tracked",
        ),
        workflow_name="new-feature",
        commit_sha=commit_sha,
        policy=policy,
        policy_digest=canonical_json_digest(canonical_json_object(policy.model_dump(mode="json"))),
        attempt=1,
    )


def _write_runtime_graph(project_root: Path, workflow_name: str) -> Path:
    graph_path = project_root / "spec.yaml"
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


def test_context_assembly_produces_context_json(tmp_path: Path):
    commit_sha = _prepare_structural_snapshot(tmp_path)
    _write_context_artifacts(tmp_path)
    pkg = _assemble_context(tmp_path, commit_sha, "exec-ctx-1")
    assert pkg.report.confidence >= pkg.report.threshold
    assert pkg.structural_snapshot.commit_sha == commit_sha
    
    ctx_file = tmp_path / ".harness" / "state" / "executions" / "exec-ctx-1" / "context.json"
    assert ctx_file.is_file()
    data = json.loads(ctx_file.read_text(encoding="utf-8"))
    assert "confidence" in data


def test_context_sufficiency_blocks_when_below_threshold(tmp_path: Path):
    commit_sha = _prepare_structural_snapshot(tmp_path)
    with pytest.raises(InsufficientContextError):
        _assemble_context(tmp_path, commit_sha, "exec-ctx-low")


def test_planner_produces_plan_json(tmp_path: Path):
    del tmp_path
    schema = Planner.response_schema()

    assert "objective" in schema["properties"]
    assert "execution_id" not in schema["properties"]
    assert Planner.schema_digest().startswith("sha256:")


def test_planner_requires_typed_context_and_removes_generic_fallback(tmp_path: Path):
    del tmp_path
    parameters = Planner.create_plan.__annotations__

    assert "context_package" not in parameters
    assert "intent" not in parameters
    assert "context_report" in parameters


def test_context_assembly_fails_without_ready_snapshot_and_writes_no_context(tmp_path: Path):
    commit_sha = _prepare_structural_snapshot(tmp_path, persist=False)
    _write_context_artifacts(tmp_path)

    with pytest.raises(ContextPrerequisiteError, match="snapshot"):
        _assemble_context(tmp_path, commit_sha, "exec-missing-index")

    assert not (tmp_path / ".harness" / "state" / "executions" / "exec-missing-index").exists()


def test_plan_validated_before_execution(tmp_path: Path):
    del tmp_path
    with pytest.raises(ValidationError):
        PlanDocument.model_validate(
            {
                "goal": "",
                "affected_modules": [],
                "applicable_gates": [],
            }
        )


def test_agent_direct_tool_dispatch_is_disabled(tmp_path: Path):
    dummy_file = tmp_path / "dummy.py"
    dummy_file.touch()
    tool_router = ToolRouter(allowed_tools=["serena_edit"])
    model_router = ModelRouter(allowed_providers=["local"])
    executor = AgentExecutor("Amelia", model_router, tool_router=tool_router, project_root=tmp_path)
    
    with pytest.raises(ToolEffectDurabilityError):
        executor.execute_tool(
            "serena_edit",
            {"file_path": str(dummy_file), "changes": {}},
        )

    assert dummy_file.read_text(encoding="utf-8") == ""


def test_agent_direct_tool_dispatch_cannot_bypass_policy(tmp_path: Path):
    tool_router = ToolRouter(allowed_tools=["serena_edit"])
    model_router = ModelRouter(allowed_providers=["local"])
    executor = AgentExecutor("Amelia", model_router, tool_router=tool_router, project_root=tmp_path)
    
    with pytest.raises(ToolEffectDurabilityError):
        executor.execute_tool("terminal_run", {"command": "dir", "cwd": "."})


def test_agent_validates_full_model_route_before_composing_prompt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = ProviderRegistry(
        {
            "openai": ProviderConfiguration(
                adapter="openai",
                model="configured-model",
            )
        }
    )
    router = ModelRouter(
        allowed_providers=("openai", "local"),
        provider_registry=registry,
        default_primary_provider="openai",
    )
    executor = AgentExecutor("Amelia", router, project_root=tmp_path)
    composed = False

    def compose(_: str) -> str:
        nonlocal composed
        composed = True
        return "must-not-be-composed"

    monkeypatch.setattr(executor, "_compose_prompt", compose)

    with pytest.raises(ModelRoutingConfigurationError, match="não registrado"):
        executor.execute_node("sensitive", fallback_providers=("local",))

    assert composed is False


def test_runtime_requires_explicit_graph_executor(tmp_path: Path):
    engine = RuntimeEngine(project_root=tmp_path, execution_id="exec-loop-1", allowed_providers=["local"])
    with pytest.raises(RuntimeGraphConfigurationError, match="GraphExecutor"):
        engine.run_workflow(tmp_path / "missing.json", initial_input={})
    assert not (tmp_path / ".harness").exists()


def test_fsm_legacy_path_constructor_fails_closed(tmp_path: Path):
    assert WorkflowState is ExecutionState
    with pytest.raises(TypeError, match="EventJournalStateStorageProvider"):
        WorkflowStateMachine(tmp_path, "exec-fsm-invalid")
    assert not (tmp_path / ".harness").exists()


def test_runtime_no_longer_runs_fixed_post_verification_sequence(tmp_path: Path):
    yaml_spec = _write_runtime_graph(tmp_path, "seq_workflow")
    compiler = GraphCompiler(project_root=tmp_path)
    compiled_maf = compiler.compile_graph(yaml_spec, "seq_workflow")
    
    engine = RuntimeEngine(project_root=tmp_path, execution_id="exec-seq-1", allowed_providers=["local"])
    with pytest.raises(RuntimeGraphConfigurationError, match="GraphExecutor"):
        engine.run_workflow(compiled_maf, approval_required=False, initial_input={})

    evidence_file = tmp_path / ".harness" / "state" / "executions" / "exec-seq-1" / "evidence.json"
    assert not evidence_file.exists()


def test_legacy_nonpromoted_rollback_path_cannot_claim_success(tmp_path: Path):
    audit = AuditTrailManager(project_root=tmp_path, execution_id="exec-rollback-audit")
    audit.log_event("STEP_1", {"data": "ok"})
    
    initial_content = audit.journal_file.read_text(encoding="utf-8")

    rb_mgr = RollbackManager(project_root=tmp_path)
    assert not hasattr(rb_mgr, "execute_rollback")
    assert audit.journal_file.read_text(encoding="utf-8") == initial_content


def test_rollback_manager_does_not_create_a_parallel_audit_journal(tmp_path: Path):
    rb_mgr = RollbackManager(project_root=tmp_path)
    assert not hasattr(rb_mgr, "execute_rollback")
    assert not (
        tmp_path
        / ".harness"
        / "state"
        / "executions"
        / "exec-rollback-integrity"
    ).exists()
