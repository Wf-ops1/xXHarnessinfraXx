"""Testes unitários para verificação do CLI Runtime, FSM State, Visualizer e Audit Export."""

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from click.testing import CliRunner

import ai_engineering_harness.cli.main as CLI_MODULE
from ai_engineering_harness.cli.main import main
from ai_engineering_harness.compiler.visualizer import GraphVisualizer
from ai_engineering_harness.contracts.events import EventType, ExecutionEvent
from ai_engineering_harness.contracts.execution import (
    EXECUTION_RECORD_SCHEMA_VERSION,
    ApprovalStatus,
    ExecutionRecord,
    ExecutionState,
)
from ai_engineering_harness.doctor.probes import (
    ComponentProbeResult,
    DoctorResult,
    ProbeStage,
    ProbeStageResult,
    ProbeStatus,
)
from ai_engineering_harness.indexer import SnapshotManager
from ai_engineering_harness.persistence import AtomicFileStateStorage, StateStorageError
from ai_engineering_harness.runtime import (
    ExecutionInspection,
    ExecutionNextAction,
    ExecutionStatusView,
    GraphExecutionResult,
)


class _FakeLifecycle:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.result = GraphExecutionResult(
            execution_id="exec-cli-runtime",
            terminal_id="completed",
            outcome="success",
            output={},
            executed_node_ids=("execute",),
            final_revision=3,
            fencing_token=1,
            failure=None,
        )
        self.status_view = ExecutionStatusView(
            execution_id="exec-cli-runtime",
            workflow_name="new-feature",
            current_node_id="completed",
            current_state=ExecutionState.COMPLETED,
            approval_status=ApprovalStatus.NOT_REQUIRED,
            created_at=datetime(2026, 8, 7, 11, 59, tzinfo=UTC),
            revision=3,
            updated_at=datetime(2026, 8, 7, 12, 0, tzinfo=UTC),
            current_attempt=0,
            duration_ms=60_000,
            next_action=ExecutionNextAction.NONE,
        )
        self.journal = (
            ExecutionEvent.model_validate(
                {
                    "event_id": "exec-cli-runtime-event-1",
                    "execution_id": "exec-cli-runtime",
                    "sequence_number": 1,
                    "event_type": "EXECUTION_COMPLETED",
                    "timestamp": datetime(2026, 8, 7, 12, 0, tzinfo=UTC),
                    "graph_name": "new-feature",
                    "node_id": None,
                    "attempt": 0,
                    "actor": "cli-test",
                    "details": {"status": "completed"},
                    "previous_hash": None,
                    "current_hash": "a" * 64,
                }
            ),
        )
        self.evidence_manifest = SimpleNamespace(
            execution_id="exec-cli-runtime",
            final_result="VERIFIED",
            journal_final_sequence=1,
            journal_final_hash="a" * 64,
            files=(SimpleNamespace(path="summary.json"),),
        )
        self.catalog = (self.status_view,)
        self.verification_result = SimpleNamespace(
            all_passed=True,
            passed_gates=1,
            total_gates=1,
        )

    def start(
        self,
        path: Path,
        *,
        initial_input: dict[str, object],
        profile_name: str = "default",
        cli_overrides: dict[str, object] | None = None,
    ):
        self.calls.append(
            (
                "start",
                {
                    "initial_input": initial_input,
                    "profile_name": profile_name,
                    "cli_overrides": cli_overrides,
                },
            )
        )
        return self.result

    def resume(self, execution_id: str):
        self.calls.append(("resume", execution_id))
        return self.result

    def approve(self, execution_id: str, *, approver: str):
        self.calls.append(("approve", (execution_id, approver)))
        return SimpleNamespace(revision=4)

    def cancel(self, execution_id: str):
        self.calls.append(("cancel", execution_id))
        return SimpleNamespace(revision=5)

    def cleanup_worktree(self, execution_id: str):
        self.calls.append(("cleanup_worktree", execution_id))
        return SimpleNamespace(status=SimpleNamespace(value="REMOVED"))

    def rollback(self, execution_id: str):
        self.calls.append(("rollback", execution_id))
        return SimpleNamespace(current_state=ExecutionState.COMPENSATED)

    def status(self, execution_id: str) -> ExecutionStatusView:
        self.calls.append(("status", execution_id))
        return self.status_view

    def list_executions(self) -> tuple[ExecutionStatusView, ...]:
        self.calls.append(("list_executions", None))
        return self.catalog

    def inspect(self, execution_id: str) -> ExecutionInspection:
        self.calls.append(("inspect", execution_id))
        return ExecutionInspection(
            status=self.status_view,
            artifact_digest=f"sha256:{'a' * 64}",
            configuration_digest=f"sha256:{'b' * 64}",
            initial_input_digest=f"sha256:{'c' * 64}",
            event_count=3,
            event_types=("STATE_TRANSITIONED", "NODE_COMPLETED"),
        )

    def events(self, execution_id: str) -> tuple[ExecutionEvent, ...]:
        self.calls.append(("events", execution_id))
        return self.journal

    def verify_evidence(self, execution_id: str):
        self.calls.append(("verify_evidence", execution_id))
        return self.evidence_manifest

    def verify(self, execution_id: str):
        self.calls.append(("verify", execution_id))
        return self.verification_result


def _doctor_result(*, healthy: bool, workflow: str | None = None) -> DoctorResult:
    stages = tuple(
        ProbeStageResult(
            stage=stage,
            status=(
                ProbeStatus.FAIL
                if not healthy and stage is ProbeStage.HEALTHY
                else ProbeStatus.NOT_APPLICABLE
                if stage is ProbeStage.AUTHENTICATED
                else ProbeStatus.PASS
            ),
            code=(
                "CLI_DOCTOR_FAILED"
                if not healthy and stage is ProbeStage.HEALTHY
                else "CLI_DOCTOR_NOT_APPLICABLE"
                if stage is ProbeStage.AUTHENTICATED
                else "CLI_DOCTOR_PASSED"
            ),
            message="Controlled CLI doctor result.",
        )
        for stage in ProbeStage
    )
    component = ComponentProbeResult(
        component_id="cli-doctor",
        component_name="CLI doctor",
        mandatory=True,
        is_healthy=healthy,
        duration_ms=0,
        stages=stages,
    )
    return DoctorResult.build((component,), workflow=workflow)


def _create_cli_audit_execution(project_root: Path, execution_id: str) -> Path:
    timestamp = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)
    storage = AtomicFileStateStorage(project_root)
    storage.create_execution(
        ExecutionRecord(
            record_schema_version=EXECUTION_RECORD_SCHEMA_VERSION,
            revision=0,
            execution_id=execution_id,
            workflow_name="cli-audit",
            artifact_digest=f"sha256:{'a' * 64}",
            base_commit_sha="b" * 40,
            original_branch="main",
            worktree_path=None,
            current_node_id="audit",
            current_state=ExecutionState.INITIATED,
            attempt_by_node={"audit": 0},
            created_at=timestamp,
            updated_at=timestamp,
            configuration_digest=f"sha256:{'c' * 64}",
            approval_status=ApprovalStatus.NOT_REQUIRED,
            candidate_commit_sha=None,
            promotion_commit_sha=None,
            failure=None,
        )
    )
    storage.append_event(
        execution_id,
        ExecutionEvent.model_validate(
            {
                "event_id": f"{execution_id}-event-1",
                "execution_id": execution_id,
                "sequence_number": 0,
                "event_type": "EXECUTION_CREATED",
                "timestamp": timestamp,
                "graph_name": "cli-audit",
                "node_id": None,
                "attempt": 0,
                "actor": "cli-test",
                "details": {"status": "created"},
                "previous_hash": None,
                "current_hash": None,
            }
        ),
    )
    return (
        project_root
        / ".harness"
        / "state"
        / "executions"
        / execution_id
        / "event-journal.jsonl"
    )


def test_graph_visualizer(tmp_path: Path):
    spec_file = tmp_path / "test_graph.yaml"
    spec_file.write_text("""
graph:
  name: test-workflow
  graph_schema_version: "1.0"
  definition_version: "1.0.0"
  entrypoint: step_1
  status: stable
nodes:
  - id: step_1
    type: agent
    role: Amelia
    input_contract: Input
    output_contract: Output
    on_success: step_2
    on_failure: failed
  - id: step_2
    type: agent
    role: Winston
    input_contract: Input
    output_contract: Output
    on_success: completed
    on_failure: failed
terminal_states:
  - id: completed
    outcome: success
  - id: failed
    outcome: failure
policies: []
contracts: []
""", encoding="utf-8")

    mermaid_output = GraphVisualizer.render_mermaid(spec_file)
    assert "flowchart TD" in mermaid_output
    assert "step_1 (Amelia)" in mermaid_output
    assert "step_2 (Winston)" in mermaid_output
    assert "node_0 -->|success| node_1" in mermaid_output
    assert "node_0 -->|failure| terminal_1" in mermaid_output

def test_cli_compile_with_render(tmp_path: Path):
    runner = CliRunner()

    with runner.isolated_filesystem(temp_dir=tmp_path):
        spec_file = Path("sample.yaml")
        spec_file.write_text("""
graph:
  name: sample
  graph_schema_version: "1.0"
  definition_version: "1.0.0"
  entrypoint: verify
  status: stable
nodes:
  - id: verify
    type: deterministic
    executor: deterministic_gate
    gate_name: sample
    on_success: completed
    on_failure: failed
terminal_states:
  - id: completed
    outcome: success
  - id: failed
    outcome: failure
policies: []
contracts: []
""", encoding="utf-8")
        res = runner.invoke(main, ["compile", str(spec_file), "--workflow", "sample", "--render"])
        assert res.exit_code == 0
        assert "Grafo compilado com sucesso" in res.output
        assert "Diagrama Mermaid do Grafo" in res.output

def test_cli_run_status_inspect_lifecycle():
    runner = CliRunner()
    with runner.isolated_filesystem():
        # 1. Init
        res_init = runner.invoke(main, ["init"])
        assert res_init.exit_code == 0

        # 2. Run
        res_run = runner.invoke(
            main,
            [
                "run",
                "new-feature",
                    "--input-json",
                    (
                        '{"context_request":{"requirement_id":"req-1",'
                        '"graph_type":"new_feature","query":"deliver"},'
                        '"graph_input":{"requirement_id":"req-1",'
                        '"graph_type":"new_feature","query":"deliver"}}'
                    ),
            ],
        )
        assert res_run.exit_code != 0
        assert "backend is unavailable" in res_run.output
        assert "concluído" not in res_run.output
        execution_root = Path(".harness/state/executions")
        assert list(execution_root.iterdir()) == []


def test_cli_run_accepts_explicit_json_and_uses_lifecycle(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runner = CliRunner()
    fake = _FakeLifecycle()
    monkeypatch.setattr(CLI_MODULE, "_lifecycle_service", lambda root, **_: fake)
    with runner.isolated_filesystem(temp_dir=tmp_path):
        assert runner.invoke(main, ["init"]).exit_code == 0
        result = runner.invoke(
            main,
            ["run", "new-feature", "--input-json", '{"intent":"bounded"}'],
        )

    assert result.exit_code == 0
    assert "exec-cli-runtime" in result.output
    assert "bounded" not in result.output
    assert fake.calls == [
        (
            "start",
            {
                "initial_input": {"intent": "bounded"},
                "profile_name": "default",
                "cli_overrides": None,
            },
        ),
        ("status", "exec-cli-runtime"),
    ]


def test_cli_run_passes_profile_and_highest_precedence_configuration_overrides(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runner = CliRunner()
    fake = _FakeLifecycle()
    monkeypatch.setattr(CLI_MODULE, "_lifecycle_service", lambda root, **_: fake)
    with runner.isolated_filesystem(temp_dir=tmp_path):
        assert runner.invoke(main, ["init"]).exit_code == 0
        result = runner.invoke(
            main,
            [
                "run",
                "new-feature",
                "--input-json",
                "{}",
                "--profile",
                "secure",
                "--config-json",
                '{"context_sufficiency_threshold":0.91}',
            ],
        )

    assert result.exit_code == 0
    assert fake.calls[0] == (
        "start",
        {
            "initial_input": {},
            "profile_name": "secure",
            "cli_overrides": {"context_sufficiency_threshold": 0.91},
        },
    )


def test_cli_run_does_not_claim_completion_while_verification_is_pending(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runner = CliRunner()
    fake = _FakeLifecycle()
    fake.status_view = fake.status_view.model_copy(
        update={"current_state": ExecutionState.VERIFYING}
    )
    monkeypatch.setattr(CLI_MODULE, "_lifecycle_service", lambda root, **_: fake)
    with runner.isolated_filesystem(temp_dir=tmp_path):
        assert runner.invoke(main, ["init"]).exit_code == 0
        result = runner.invoke(main, ["run", "new-feature", "--input-json", "{}"])

    assert result.exit_code == 0
    assert "aguarda verificação canônica" in result.output
    assert "Workflow new-feature concluído" not in result.output


def test_cli_run_rejects_invalid_input_and_legacy_approval_flag(tmp_path: Path) -> None:
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        invalid = runner.invoke(
            main,
            ["run", "new-feature", "--input-json", "[]"],
        )
        legacy = runner.invoke(main, ["run", "new-feature", "--approval-required"])
        invalid_config = runner.invoke(
            main,
            ["run", "new-feature", "--config-json", "[]"],
        )

    assert invalid.exit_code != 0
    assert "must be a JSON object" in invalid.output
    assert legacy.exit_code != 0
    assert "explicit human node" in legacy.output
    assert invalid_config.exit_code != 0
    assert "--config-json must be a JSON object" in invalid_config.output


def test_cli_resume_approve_cancel_status_and_inspect_are_canonical_and_redacted(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runner = CliRunner()
    fake = _FakeLifecycle()
    monkeypatch.setattr(CLI_MODULE, "_lifecycle_service", lambda root, **_: fake)
    with runner.isolated_filesystem(temp_dir=tmp_path):
        legacy_root = Path(".harness/state/executions/exec-cli-runtime")
        legacy_root.mkdir(parents=True)
        (legacy_root / "workflow-state.json").write_text(
            '{"secret":"legacy-state-secret"}',
            encoding="utf-8",
        )
        (legacy_root / "approval_request.json").write_text(
            '{"secret":"legacy-approval-secret"}',
            encoding="utf-8",
        )
        status_result = runner.invoke(main, ["status", "exec-cli-runtime"])
        inspect_result = runner.invoke(main, ["inspect", "exec-cli-runtime"])
        resume_result = runner.invoke(main, ["resume", "exec-cli-runtime"])
        approve_missing = runner.invoke(main, ["approve", "exec-cli-runtime"])
        approve_result = runner.invoke(
            main,
            ["approve", "exec-cli-runtime", "--approver", "reviewer-1"],
        )
        cancel_result = runner.invoke(main, ["cancel", "exec-cli-runtime"])
        cleanup_result = runner.invoke(
            main,
            ["cleanup-worktree", "exec-cli-runtime"],
        )
        rollback_result = runner.invoke(main, ["rollback", "exec-cli-runtime"])

    for result in (
        status_result,
        inspect_result,
        resume_result,
        approve_result,
        cancel_result,
        cleanup_result,
        rollback_result,
    ):
        assert result.exit_code == 0
        assert "legacy-state-secret" not in result.output
        assert "legacy-approval-secret" not in result.output
    assert "COMPLETED" in status_result.output
    assert "sha256:" in inspect_result.output
    assert "outcome success" in resume_result.output
    assert approve_missing.exit_code != 0
    assert "Missing option '--approver'" in approve_missing.output
    assert ("resume", "exec-cli-runtime") in fake.calls
    assert ("approve", ("exec-cli-runtime", "reviewer-1")) in fake.calls
    assert ("cancel", "exec-cli-runtime") in fake.calls
    assert ("cleanup_worktree", "exec-cli-runtime") in fake.calls
    assert ("rollback", "exec-cli-runtime") in fake.calls


def test_cli_operational_list_status_json_events_and_evidence_are_canonical(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runner = CliRunner()
    fake = _FakeLifecycle()
    monkeypatch.setattr(CLI_MODULE, "_lifecycle_service", lambda root, **_: fake)

    with runner.isolated_filesystem(temp_dir=tmp_path):
        catalog = runner.invoke(main, ["list"])
        status_json = runner.invoke(
            main,
            ["status", "exec-cli-runtime", "--json"],
        )
        journal = runner.invoke(main, ["events", "exec-cli-runtime"])
        evidence_missing_verify = runner.invoke(
            main,
            ["evidence", "exec-cli-runtime"],
        )
        evidence = runner.invoke(
            main,
            ["evidence", "exec-cli-runtime", "--verify"],
        )

    assert catalog.exit_code == 0
    assert "exec-cli-runtime" in catalog.output
    payload = json.loads(status_json.output)
    assert payload == fake.status_view.model_dump(mode="json")
    assert payload["status_schema_version"] == "1.0"
    assert payload["duration_ms"] == 60_000
    journal_lines = journal.output.splitlines()
    assert len(journal_lines) == 1
    assert json.loads(journal_lines[0])["sequence_number"] == 1
    assert evidence_missing_verify.exit_code != 0
    assert "--verify is required" in evidence_missing_verify.output
    assert evidence.exit_code == 0
    assert "VERIFIED" in evidence.output
    combined_output = (
        f"{catalog.output}{status_json.output}{journal.output}{evidence.output}"
    )
    assert "legacy-state-secret" not in combined_output


def test_cli_events_follow_emits_each_sequence_once_and_stops_at_terminal(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runner = CliRunner()
    fake = _FakeLifecycle()
    first = fake.journal[0].model_copy(
        update={
            "event_id": "exec-cli-runtime-event-created",
            "event_type": EventType.EXECUTION_CREATED,
            "details": {"status": "created"},
        }
    )
    second = fake.journal[0].model_copy(
        update={
            "event_id": "exec-cli-runtime-event-completed",
            "sequence_number": 2,
            "previous_hash": "a" * 64,
            "current_hash": "b" * 64,
        }
    )
    event_reads = 0
    status_reads = 0

    def read_events(execution_id: str) -> tuple[ExecutionEvent, ...]:
        nonlocal event_reads
        fake.calls.append(("events", execution_id))
        event_reads += 1
        return (first,) if event_reads == 1 else (first, second)

    def read_status(execution_id: str) -> ExecutionStatusView:
        nonlocal status_reads
        fake.calls.append(("status", execution_id))
        status_reads += 1
        if status_reads == 1:
            return fake.status_view.model_copy(
                update={
                    "current_state": ExecutionState.EXECUTING,
                    "next_action": ExecutionNextAction.RESUME,
                }
            )
        return fake.status_view

    fake.events = read_events  # type: ignore[method-assign]
    fake.status = read_status  # type: ignore[method-assign]
    monkeypatch.setattr(CLI_MODULE, "_lifecycle_service", lambda root, **_: fake)
    monkeypatch.setattr(CLI_MODULE.time, "sleep", lambda _: None)

    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(
            main,
            ["events", "exec-cli-runtime", "--follow"],
        )

    assert result.exit_code == 0
    lines = [json.loads(line) for line in result.output.splitlines()]
    assert [line["sequence_number"] for line in lines] == [1, 2]
    assert event_reads == 3
    assert status_reads == 2


def test_cli_list_preserves_canonical_order_and_handles_empty_catalog(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runner = CliRunner()
    fake = _FakeLifecycle()
    first = fake.status_view.model_copy(
        update={"execution_id": "exec-a", "workflow_name": "alpha"}
    )
    second = fake.status_view.model_copy(
        update={"execution_id": "exec-z", "workflow_name": "zeta"}
    )
    fake.catalog = (first, second)
    monkeypatch.setattr(CLI_MODULE, "_lifecycle_service", lambda root, **_: fake)

    with runner.isolated_filesystem(temp_dir=tmp_path):
        ordered = runner.invoke(main, ["list"])
        fake.catalog = ()
        empty = runner.invoke(main, ["list"])

    assert ordered.exit_code == 0
    assert ordered.output.index("exec-a") < ordered.output.index("exec-z")
    assert empty.exit_code == 0
    assert "Nenhuma execução encontrada" in empty.output


def test_cli_operational_errors_are_nonzero_redacted_and_without_traceback(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runner = CliRunner()
    fake = _FakeLifecycle()
    raw_secret = "sk-" + "x" * 40

    def fail(*args, **kwargs):
        del args, kwargs
        raise StateStorageError(f"execution is unavailable; api_key={raw_secret}")

    fake.list_executions = fail  # type: ignore[method-assign]
    fake.status = fail  # type: ignore[method-assign]
    fake.inspect = fail  # type: ignore[method-assign]
    fake.events = fail  # type: ignore[method-assign]
    fake.verify_evidence = fail  # type: ignore[method-assign]
    monkeypatch.setattr(CLI_MODULE, "_lifecycle_service", lambda root, **_: fake)

    commands = (
        ["list"],
        ["status", "exec-missing", "--json"],
        ["inspect", "exec-missing"],
        ["events", "exec-missing"],
        ["evidence", "exec-missing", "--verify"],
    )
    with runner.isolated_filesystem(temp_dir=tmp_path):
        results = tuple(runner.invoke(main, command) for command in commands)

    for result in results:
        assert result.exit_code != 0
        assert raw_secret not in result.output
        assert "[REDACTED_SECRET]" in result.output
        assert "Traceback" not in result.output


def test_cli_events_follow_fails_closed_if_journal_regresses(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runner = CliRunner()
    fake = _FakeLifecycle()
    reads = 0

    def regressing_events(execution_id: str) -> tuple[ExecutionEvent, ...]:
        nonlocal reads
        fake.calls.append(("events", execution_id))
        reads += 1
        return fake.journal if reads == 1 else ()

    fake.events = regressing_events  # type: ignore[method-assign]
    fake.status = lambda execution_id: fake.status_view.model_copy(  # type: ignore[method-assign]
        update={
            "current_state": ExecutionState.EXECUTING,
            "next_action": ExecutionNextAction.RESUME,
        }
    )
    monkeypatch.setattr(CLI_MODULE, "_lifecycle_service", lambda root, **_: fake)
    monkeypatch.setattr(CLI_MODULE.time, "sleep", lambda _: None)

    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(
            main,
            ["events", "exec-cli-runtime", "--follow"],
        )

    assert result.exit_code != 0
    assert "canonical journal sequence regressed" in result.output
    assert reads == 2


def test_cli_rollback_returns_nonzero_when_compensation_is_blocked(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runner = CliRunner()
    fake = _FakeLifecycle()

    def blocked_rollback(execution_id: str):
        fake.calls.append(("rollback", execution_id))
        return SimpleNamespace(current_state=ExecutionState.BLOCKED_ROLLBACK)

    fake.rollback = blocked_rollback  # type: ignore[method-assign]
    monkeypatch.setattr(CLI_MODULE, "_lifecycle_service", lambda root, **_: fake)
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(main, ["rollback", "exec-cli-runtime"])

    assert result.exit_code != 0
    assert "BLOCKED_ROLLBACK" in result.output
    assert "Rollback de" not in result.output
    assert fake.calls == [("rollback", "exec-cli-runtime")]


def test_cli_help_lists_runtime_and_operational_inspection_commands() -> None:
    result = CliRunner().invoke(main, ["--help"])

    assert result.exit_code == 0
    for command in (
        "run",
        "resume",
        "approve",
        "cancel",
        "cleanup-worktree",
        "rollback",
        "list",
        "status",
        "inspect",
        "events",
        "evidence",
        "verify",
    ):
        assert command in result.output


def test_cli_doctor_json_uses_typed_report_and_workflow(monkeypatch) -> None:
    observed: dict[str, object] = {}

    class FakeChecker:
        def __init__(self, **kwargs) -> None:
            observed.update(kwargs)

        def check(self) -> DoctorResult:
            return _doctor_result(healthy=True, workflow="new-feature")

    monkeypatch.setattr(CLI_MODULE, "DoctorChecker", FakeChecker)
    result = CliRunner().invoke(main, ["doctor", "--json", "--workflow", "new-feature"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["schema_version"] == "1.0"
    assert payload["status"] == "HEALTHY"
    assert payload["workflow"] == "new-feature"
    assert observed["workflow"] == "new-feature"


def test_cli_doctor_returns_nonzero_for_mandatory_failure(monkeypatch) -> None:
    class FakeChecker:
        def __init__(self, **kwargs) -> None:
            del kwargs

        def check(self) -> DoctorResult:
            return _doctor_result(healthy=False)

    monkeypatch.setattr(CLI_MODULE, "DoctorChecker", FakeChecker)
    result = CliRunner().invoke(main, ["doctor"])

    assert result.exit_code == 1
    assert "UNHEALTHY" in result.output


def test_cli_verify_requires_a_worktree_execution_id() -> None:
    runner = CliRunner()
    help_result = runner.invoke(main, ["verify", "--help"])
    missing_result = runner.invoke(main, ["verify"])

    assert help_result.exit_code == 0
    assert "EXECUTION_ID" in help_result.output
    assert "worktree validado" in help_result.output
    assert "--gate" not in help_result.output
    assert missing_result.exit_code != 0
    assert "Missing argument 'EXECUTION_ID'" in missing_result.output


def test_cli_verify_uses_lifecycle_and_returns_nonzero_when_blocked(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runner = CliRunner()
    fake = _FakeLifecycle()
    monkeypatch.setattr(
        CLI_MODULE,
        "_lifecycle_service",
        lambda root, *, project_id="default-proj", trust_boundary=None: fake,
    )
    with runner.isolated_filesystem(temp_dir=tmp_path):
        passed = runner.invoke(
            main,
            ["verify", "exec-cli-runtime", "--project-id", "fixture"],
        )
        fake.verification_result = SimpleNamespace(
            all_passed=False,
            passed_gates=0,
            total_gates=1,
        )
        blocked = runner.invoke(main, ["verify", "exec-cli-runtime"])

    assert passed.exit_code == 0
    assert "Verificação persistida" in passed.output
    assert blocked.exit_code != 0
    assert "verificação bloqueou a conclusão" in blocked.output
    assert fake.calls == [
        ("verify", "exec-cli-runtime"),
        ("verify", "exec-cli-runtime"),
    ]


def test_cli_audit_validates_and_exports_exact_execution_identity(
    tmp_path: Path,
) -> None:
    runner = CliRunner()
    execution_id = "exec-cli-audit"
    with runner.isolated_filesystem(temp_dir=tmp_path):
        _create_cli_audit_execution(Path.cwd(), execution_id)
        verified = runner.invoke(main, ["audit", execution_id])
        json_result = runner.invoke(main, ["audit", execution_id, "--export", "json"])
        sarif_result = runner.invoke(main, ["audit", execution_id, "--export", "sarif"])

    assert verified.exit_code == 0
    assert "AUDIT SUCCESS" in verified.output
    assert "tamper-evident local" in verified.output
    assert json_result.exit_code == 0
    assert json.loads(json_result.output)["execution_id"] == execution_id
    assert sarif_result.exit_code == 0
    assert json.loads(sarif_result.output)["runs"][0]["automationDetails"]["id"] == execution_id


def test_cli_audit_missing_or_corrupt_journal_fails_closed(tmp_path: Path) -> None:
    runner = CliRunner()
    execution_id = "exec-cli-audit-corrupt"
    with runner.isolated_filesystem(temp_dir=tmp_path):
        missing = runner.invoke(main, ["audit", "exec-cli-audit-missing"])
        journal = _create_cli_audit_execution(Path.cwd(), execution_id)
        journal.write_bytes(b"{broken\n")
        corrupt = runner.invoke(main, ["audit", execution_id, "--export", "json"])

    assert missing.exit_code != 0
    assert "exec-cli-audit-missing" in missing.output
    assert corrupt.exit_code != 0
    assert execution_id in corrupt.output
    assert "line 1 is invalid" in corrupt.output
    assert "audit_schema_version" not in corrupt.output


def _initialize_cli_git_repository(project_root: Path) -> str:
    subprocess.run(["git", "init", "--quiet"], cwd=project_root, check=True, shell=False)
    subprocess.run(["git", "config", "user.name", "CLI Test"], cwd=project_root, check=True, shell=False)
    subprocess.run(
        ["git", "config", "user.email", "cli@example.invalid"], cwd=project_root, check=True, shell=False
    )
    (project_root / "tracked.py").write_text("def tracked():\n    return True\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.py"], cwd=project_root, check=True, shell=False)
    subprocess.run(["git", "commit", "--quiet", "-m", "fixture"], cwd=project_root, check=True, shell=False)
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=project_root,
        check=True,
        shell=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip().lower()


def test_cli_index_rebuilds_and_validates_real_commit_snapshot(tmp_path: Path) -> None:
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        project_root = Path.cwd()
        commit_sha = _initialize_cli_git_repository(project_root)
        first = runner.invoke(main, ["index"])
        second = runner.invoke(main, ["index"])

    assert first.exit_code == 0
    assert second.exit_code == 0
    assert "Índice estrutural reconstruído e validado" in first.output
    assert commit_sha in first.output
    assert "Símbolos: 2" in first.output
    snapshot = SnapshotManager(project_root).require_snapshot(commit_sha)
    assert {(symbol.kind, symbol.qualified_name) for symbol in snapshot.symbols} == {
        ("module", "tracked"),
        ("function", "tracked.tracked"),
    }


def test_cli_index_fails_on_committed_syntax_error_without_partial_snapshot(tmp_path: Path) -> None:
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        project_root = Path.cwd()
        _initialize_cli_git_repository(project_root)
        (project_root / "broken.py").write_text("def broken(:\n", encoding="utf-8")
        subprocess.run(["git", "add", "broken.py"], cwd=project_root, check=True, shell=False)
        subprocess.run(
            ["git", "commit", "--quiet", "-m", "broken source"],
            cwd=project_root,
            check=True,
            shell=False,
        )
        commit_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=project_root,
            check=True,
            shell=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        ).stdout.strip().lower()
        result = runner.invoke(main, ["index"])

    assert result.exit_code != 0
    assert "committed Python source could not be parsed: broken.py" in result.output
    assert "reconstruído" not in result.output
    assert not SnapshotManager(project_root).snapshot_path(commit_sha).exists()
