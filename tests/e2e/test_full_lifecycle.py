"""Suíte de Testes E2E do Ciclo de Vida do Harness (TASK-8.3)."""

import subprocess
from dataclasses import dataclass
from pathlib import Path

from ai_engineering_harness.compiler.compiler import GraphCompiler
from ai_engineering_harness.contracts.execution import ExecutionState
from ai_engineering_harness.core.detector import StackDetector
from ai_engineering_harness.doctor.checker import DoctorChecker
from ai_engineering_harness.indexer import CodebaseMemoryAdapter, PythonAstIndexer
from ai_engineering_harness.knowledge.synchronizer import KnowledgeSynchronizer
from ai_engineering_harness.observability.audit import AuditTrailManager
from ai_engineering_harness.persistence import AtomicFileStateStorage
from ai_engineering_harness.runtime import (
    DeterministicNodeExecutor,
    ExecutionLifecycleService,
    NodeExecutionContext,
    NodeExecutionResult,
    NodeExecutorRegistry,
    RuntimeEngine,
)


@dataclass
class _LifecycleBackend:
    def execute(self, context: NodeExecutionContext) -> NodeExecutionResult:
        return NodeExecutionResult.completed(
            {"executed_node": context.node.id, "input": context.input_payload}
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


def test_full_lifecycle_e2e_python(tmp_path: Path):
    # 1. Setup projeto fixture
    (tmp_path / "pyproject.toml").touch()
    (tmp_path / "application.py").write_text(
        "def run_application():\n    return 'ready'\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "--quiet"], cwd=tmp_path, check=True, shell=False)
    subprocess.run(["git", "config", "user.name", "Lifecycle Test"], cwd=tmp_path, check=True, shell=False)
    subprocess.run(
        ["git", "config", "user.email", "lifecycle@example.invalid"], cwd=tmp_path, check=True, shell=False
    )
    subprocess.run(
        ["git", "add", "pyproject.toml", "application.py"],
        cwd=tmp_path,
        check=True,
        shell=False,
    )
    subprocess.run(["git", "commit", "--quiet", "-m", "fixture"], cwd=tmp_path, check=True, shell=False)
    commit_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_path,
        check=True,
        shell=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip().lower()

    # 2. Detector
    detector = StackDetector(project_root=tmp_path)
    stack = detector.detect()
    assert stack.language == "python"

    # 3. Doctor Probe
    checker = DoctorChecker(config={})
    doctor_results = checker.check_all()
    assert all(r.is_healthy for r in doctor_results)

    # 4. Compile Graph
    yaml_spec = _write_runtime_graph(tmp_path, "new-feature")
    compiler = GraphCompiler(project_root=tmp_path)
    compiled_maf = compiler.compile_graph(yaml_spec, "new-feature")
    assert compiled_maf.is_file()

    # 5. Index Structural
    snapshot = PythonAstIndexer(tmp_path).rebuild()
    indexer = CodebaseMemoryAdapter(project_root=tmp_path)
    ast_data = indexer.query_ast("get_structure", commit_sha="HEAD")
    assert ast_data["commit_sha"] == commit_sha
    assert ast_data == snapshot.model_dump(mode="json")
    assert {(symbol["kind"], symbol["qualified_name"]) for symbol in ast_data["symbols"]} == {
        ("module", "application"),
        ("function", "application.run_application"),
    }

    # 6. Run through the canonical F2.5 lifecycle and immutable resume bundle
    execution_id = "exec-e2e-100"
    storage = AtomicFileStateStorage(tmp_path)
    lifecycle = ExecutionLifecycleService(
        tmp_path,
        storage,
        NodeExecutorRegistry(
            deterministic=DeterministicNodeExecutor(_LifecycleBackend()),
        ),
        git_identity_provider=lambda: ("a" * 40, "test"),
    )
    engine = RuntimeEngine(
        project_root=tmp_path,
        execution_id=execution_id,
        allowed_providers=[],
        lifecycle_service=lifecycle,
    )
    result = engine.start_execution(
        compiled_maf,
        initial_input={"intent": "Deliver new feature"},
        configuration={"profile": "e2e"},
    )
    assert result.outcome == "success"
    assert result.executed_node_ids == ("step1",)
    final_record = storage.load_execution(execution_id)
    assert final_record.current_node_id == "completed"
    assert final_record.current_state == ExecutionState.COMPLETED
    assert final_record.revision == 3
    assert engine.status_execution().current_state == ExecutionState.COMPLETED
    assert engine.inspect_execution().event_count == 4
    assert storage.load_execution_bundle(execution_id).execution_id == execution_id

    exec_dir = tmp_path / ".harness" / "state" / "executions" / execution_id
    assert (exec_dir / "execution.json").is_file()
    assert (exec_dir / "event-journal.jsonl").is_file()
    assert not (exec_dir / "workflow-state.json").exists()
    assert not (exec_dir / "evidence.json").exists()

    # 7. Re-index & Knowledge Sync
    knw_sync = KnowledgeSynchronizer(project_root=tmp_path)
    tx_status = knw_sync.sync_ki("tx-e2e-1", {"id": "ki-feature-1", "title": "New Feature Done"})
    assert tx_status == "COMMITTED"

    # 8. Audit Trail & Hash Chain Verification
    audit = AuditTrailManager(project_root=tmp_path, execution_id="exec-e2e-audit")
    audit.log_event("WORKFLOW_COMPLETED", {"status": "SUCCESS"})
    is_valid, _ = audit.verify_integrity()
    assert is_valid is True
