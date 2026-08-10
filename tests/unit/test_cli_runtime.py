"""Testes unitários para verificação do CLI Runtime, FSM State, Visualizer e Audit Export."""

import subprocess
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from click.testing import CliRunner

import ai_engineering_harness.cli.main as CLI_MODULE
from ai_engineering_harness.cli.main import main
from ai_engineering_harness.compiler.visualizer import GraphVisualizer
from ai_engineering_harness.contracts.execution import ApprovalStatus, ExecutionState
from ai_engineering_harness.indexer import SnapshotManager
from ai_engineering_harness.runtime import (
    ExecutionInspection,
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
            revision=3,
            updated_at=datetime(2026, 8, 7, 12, 0, tzinfo=UTC),
        )

    def start(self, path: Path, *, initial_input: dict[str, object]):
        self.calls.append(("start", initial_input))
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

    def status(self, execution_id: str) -> ExecutionStatusView:
        self.calls.append(("status", execution_id))
        return self.status_view

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
    monkeypatch.setattr(CLI_MODULE, "_lifecycle_service", lambda root: fake)
    with runner.isolated_filesystem(temp_dir=tmp_path):
        assert runner.invoke(main, ["init"]).exit_code == 0
        result = runner.invoke(
            main,
            ["run", "new-feature", "--input-json", '{"intent":"bounded"}'],
        )

    assert result.exit_code == 0
    assert "exec-cli-runtime" in result.output
    assert "bounded" not in result.output
    assert fake.calls == [("start", {"intent": "bounded"})]


def test_cli_run_rejects_invalid_input_and_legacy_approval_flag(tmp_path: Path) -> None:
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        invalid = runner.invoke(
            main,
            ["run", "new-feature", "--input-json", "[]"],
        )
        legacy = runner.invoke(main, ["run", "new-feature", "--approval-required"])

    assert invalid.exit_code != 0
    assert "must be a JSON object" in invalid.output
    assert legacy.exit_code != 0
    assert "explicit human node" in legacy.output


def test_cli_resume_approve_cancel_status_and_inspect_are_canonical_and_redacted(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runner = CliRunner()
    fake = _FakeLifecycle()
    monkeypatch.setattr(CLI_MODULE, "_lifecycle_service", lambda root: fake)
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

    for result in (
        status_result,
        inspect_result,
        resume_result,
        approve_result,
        cancel_result,
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


def test_cli_help_lists_resume_approve_cancel_status_and_inspect() -> None:
    result = CliRunner().invoke(main, ["--help"])

    assert result.exit_code == 0
    for command in ("run", "resume", "approve", "cancel", "status", "inspect"):
        assert command in result.output


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
