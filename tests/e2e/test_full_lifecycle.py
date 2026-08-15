"""Suíte de Testes E2E do Ciclo de Vida do Harness (TASK-8.3)."""

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ai_engineering_harness.compiler.compiler import GraphCompiler
from ai_engineering_harness.contracts.evidence import EvidenceApplicability
from ai_engineering_harness.contracts.execution import ExecutionState
from ai_engineering_harness.core.detector import StackDetector
from ai_engineering_harness.doctor.checker import DoctorChecker
from ai_engineering_harness.indexer import CodebaseMemoryAdapter, PythonAstIndexer
from ai_engineering_harness.knowledge.synchronizer import KnowledgeSynchronizer
from ai_engineering_harness.observability.audit import AuditTrailManager
from ai_engineering_harness.observability.evidence import EvidenceManifestManager
from ai_engineering_harness.persistence import AtomicFileStateStorage
from ai_engineering_harness.runtime import (
    DeterministicNodeExecutor,
    ExecutionLifecycleService,
    NodeExecutionContext,
    NodeExecutionResult,
    NodeExecutorRegistry,
    RuntimeEngine,
)
from ai_engineering_harness.security import (
    SecretGrant,
    TrustAuthorization,
    TrustBoundaryEvaluator,
)
from ai_engineering_harness.workspace import ExternalWorktreeManager


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
policies:
  - policies/verification_policy.yaml
contracts: []
""",
        encoding="utf-8",
    )
    return graph_path


def test_full_lifecycle_e2e_python(tmp_path: Path):
    # 1. Setup projeto fixture
    (tmp_path / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\naddopts = '-p no:cacheprovider'\n",
        encoding="utf-8",
    )
    (tmp_path / "application.py").write_text(
        "def run_application():\n    return 'ready'\n",
        encoding="utf-8",
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_application.py").write_text(
        "from application import run_application\n\n\n"
        "def test_application():\n    assert run_application() == 'ready'\n",
        encoding="utf-8",
    )
    (tmp_path / ".harness" / "policies").mkdir(parents=True)
    (tmp_path / ".harness" / "policies" / "verification_policy.yaml").write_text(
        """policy_id: e2e-verification-v1
policy_schema_version: "1.0"
definition_version: "1.0.0"
applies_to:
  - new-feature
required_gates:
  - id: unit_test
    executor: deterministic
    command: "python -m pytest"
    blocking: true
termination_rule: ALL_REQUIRED_GATES_PASSED
on_failure: route_to_failure_classifier
""",
        encoding="utf-8",
    )
    (tmp_path / ".gitignore").write_text(
        ".harness/state/\n.harness/artifacts/\n__pycache__/\n*.pyc\n",
        encoding="utf-8",
    )
    yaml_spec = _write_runtime_graph(tmp_path, "new-feature")
    subprocess.run(["git", "init", "--quiet"], cwd=tmp_path, check=True, shell=False)
    subprocess.run(["git", "config", "user.name", "Lifecycle Test"], cwd=tmp_path, check=True, shell=False)
    subprocess.run(
        ["git", "config", "user.email", "lifecycle@example.invalid"], cwd=tmp_path, check=True, shell=False
    )
    subprocess.run(
        ["git", "add", "."],
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
    original_branch = subprocess.run(
        ["git", "symbolic-ref", "--quiet", "--short", "HEAD"],
        cwd=tmp_path,
        check=True,
        shell=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()

    # 2. Detector
    detector = StackDetector(project_root=tmp_path)
    stack = detector.detect()
    assert stack.language == "python"

    # 3. Doctor Probe
    checker = DoctorChecker(config={})
    doctor_results = checker.check_all()
    assert all(r.is_healthy for r in doctor_results)

    # 4. Compile Graph
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
        ("module", "tests.test_application"),
        ("import", "application.run_application"),
        ("function", "tests.test_application.test_application"),
    }

    # 6. Run through the canonical F2.5 lifecycle and immutable resume bundle
    execution_id = "exec-e2e-100"
    storage = AtomicFileStateStorage(tmp_path)
    boundary = TrustBoundaryEvaluator(
        tmp_path,
        authorization=TrustAuthorization(
            repository_root=str(tmp_path.resolve()),
            executable_aliases=("git", "python"),
            secret_grants=tuple(
                SecretGrant(name=name, consumers=("terminal:python",))
                for name in ("PATH", "Path", "SYSTEMROOT", "SystemRoot")
            ),
        ),
    ).evaluate()
    manager = ExternalWorktreeManager(
        tmp_path,
        "e2e-project",
        external_base_dir=tmp_path.parent / f"{tmp_path.name}-worktrees",
        trust_boundary=boundary,
    )
    worktree = manager.create_worktree(
        execution_id,
        expected_base_commit_sha=commit_sha,
    )
    lifecycle = ExecutionLifecycleService(
        tmp_path,
        storage,
        NodeExecutorRegistry(
            deterministic=DeterministicNodeExecutor(_LifecycleBackend()),
        ),
        git_identity_provider=lambda: (commit_sha, original_branch),
        verification_worktree_provider=manager.load_worktree,
        trust_boundary=boundary,
    )
    engine = RuntimeEngine(
        project_root=tmp_path,
        execution_id=execution_id,
        allowed_providers=[],
        lifecycle_service=lifecycle,
    )
    try:
        result = engine.start_execution(
            compiled_maf,
            initial_input={"intent": "Deliver new feature"},
            configuration={"project": {"test_label": "e2e"}},
        )
        assert result.outcome == "success"
        assert result.executed_node_ids == ("step1",)
        assert storage.load_execution(execution_id).current_state == ExecutionState.VERIFYING

        verification = engine.verify_execution()

        assert verification.all_passed is True
        assert verification.verified_commit_sha == commit_sha
        assert verification.gate_results[0].argv == ("python", "-m", "pytest")
        final_record = storage.load_execution(execution_id)
        assert final_record.current_node_id == "completed"
        assert final_record.current_state == ExecutionState.COMPLETED
        assert final_record.revision == 5
        assert engine.status_execution().current_state == ExecutionState.COMPLETED
        assert engine.inspect_execution().event_count == 9
        assert storage.load_execution_bundle(execution_id).execution_id == execution_id
        manifest = EvidenceManifestManager(tmp_path, storage).load_and_verify(execution_id)
        assert manifest.execution_id == execution_id
        assert manifest.final_result == "VERIFIED"
        assert manifest.base_commit_sha == commit_sha
        assert manifest.promotion.status is EvidenceApplicability.NOT_APPLICABLE
        assert manifest.plan.status is EvidenceApplicability.NOT_APPLICABLE
        assert manifest.context.status is EvidenceApplicability.NOT_APPLICABLE
        assert manifest.diff.status is EvidenceApplicability.NOT_APPLICABLE
        assert manifest.approval.status.value == "NOT_REQUIRED"
        assert manifest.gates[0].status == "PASSED"
        assert manifest.journal_final_sequence == 9
        assert manifest.journal_final_hash == storage.load_events(execution_id)[-1].current_hash
    finally:
        for cache in tuple(worktree.worktree_path.rglob("__pycache__")):
            shutil.rmtree(cache)
        manager.cleanup_worktree(execution_id)

    exec_dir = tmp_path / ".harness" / "state" / "executions" / execution_id
    bundle_dir = tmp_path / ".harness" / "artifacts" / "executions" / execution_id
    assert (exec_dir / "execution.json").is_file()
    assert (exec_dir / "event-journal.jsonl").is_file()
    assert len(tuple((bundle_dir / "payloads").glob("*.json"))) == 4
    assert not (exec_dir / "workflow-state.json").exists()
    assert (exec_dir / "evidence.json").is_file()

    # 7. Re-index & Knowledge Sync
    knw_sync = KnowledgeSynchronizer(project_root=tmp_path)
    tx_status = knw_sync.sync_ki("tx-e2e-1", {"id": "ki-feature-1", "title": "New Feature Done"})
    assert tx_status == "COMMITTED"

    # 8. Audit Trail & Hash Chain Verification
    audit = AuditTrailManager(project_root=tmp_path, execution_id=execution_id)
    assert audit.load_events()
    is_valid, _ = audit.verify_integrity()
    assert is_valid is True
