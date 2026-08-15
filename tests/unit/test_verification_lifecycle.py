"""F4.7 durable verification composition and completion guard."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ai_engineering_harness.compiler import GraphCompiler
from ai_engineering_harness.contracts import ExecutionState
from ai_engineering_harness.contracts.events import ExecutionEvent
from ai_engineering_harness.persistence import AtomicFileStateStorage
from ai_engineering_harness.runtime import (
    VERIFICATION_GATE_RECORDED,
    VERIFICATION_GATE_STARTED,
    VERIFICATION_SUITE_RECORDED,
    DeterministicNodeExecutor,
    ExecutionBudgetExceededError,
    ExecutionLifecycleService,
    NodeExecutionContext,
    NodeExecutionResult,
    NodeExecutorRegistry,
    VerificationLifecycleIntegrityError,
    VerificationLifecyclePrerequisiteError,
)
from ai_engineering_harness.security import (
    PathGuard,
    SecretGrant,
    TrustAuthorization,
    TrustBoundaryEvaluator,
    TrustEvaluationResult,
)
from ai_engineering_harness.verification import GateStatus
from ai_engineering_harness.workspace import (
    ProvisionedWorktree,
    WorktreeReference,
    WorktreeStatus,
)


@dataclass
class _Backend:
    def execute(self, context: NodeExecutionContext) -> NodeExecutionResult:
        return NodeExecutionResult.completed({"node": context.node.id})


@dataclass(frozen=True)
class _Fixture:
    artifact: Path
    commit_sha: str
    branch: str


def _write_fixture(project_root: Path, *, passing: bool) -> _Fixture:
    (project_root / ".harness" / "policies").mkdir(parents=True)
    (project_root / "tests").mkdir()
    (project_root / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\naddopts = '-p no:cacheprovider'\n",
        encoding="utf-8",
    )
    assertion = "True" if passing else "False"
    (project_root / "tests" / "test_target.py").write_text(
        f"def test_target():\n    assert {assertion}\n",
        encoding="utf-8",
    )
    (project_root / ".harness" / "policies" / "verification_policy.yaml").write_text(
        """policy_id: fixture-verification-v1
policy_schema_version: "1.0"
definition_version: "1.0.0"
applies_to:
  - f4-7-fixture
required_gates:
  - id: unit_test
    executor: deterministic
    command: "python -m pytest"
    blocking: true
  - id: security_scan
    executor: deterministic
    command: "python -m bandit -r ."
    blocking: false
termination_rule: ALL_REQUIRED_GATES_PASSED
on_failure: route_to_failure_classifier
""",
        encoding="utf-8",
    )
    graph = project_root / "graph.yaml"
    graph.write_text(
        """graph:
  name: f4-7-fixture
  graph_schema_version: "1.0"
  definition_version: "1.0.0"
  entrypoint: execute
  status: stable
nodes:
  - id: execute
    type: deterministic
    executor: deterministic_gate
    gate_name: fixture
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
    (project_root / ".gitignore").write_text(
        ".harness/state/\n.harness/artifacts/\n__pycache__/\n*.pyc\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "--quiet"], cwd=project_root, check=True, shell=False)
    subprocess.run(
        ["git", "config", "user.name", "F4.7 Test"],
        cwd=project_root,
        check=True,
        shell=False,
    )
    subprocess.run(
        ["git", "config", "user.email", "f47@example.invalid"],
        cwd=project_root,
        check=True,
        shell=False,
    )
    subprocess.run(["git", "add", "."], cwd=project_root, check=True, shell=False)
    subprocess.run(
        ["git", "commit", "--quiet", "-m", "fixture"],
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
    ).stdout.strip()
    branch = subprocess.run(
        ["git", "symbolic-ref", "--quiet", "--short", "HEAD"],
        cwd=project_root,
        check=True,
        shell=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()
    return _Fixture(
        artifact=GraphCompiler(project_root).compile_graph(graph, "f4-7-fixture"),
        commit_sha=commit_sha,
        branch=branch,
    )


def _worktree(
    project_root: Path,
    execution_id: str,
    fixture: _Fixture,
    boundary: TrustEvaluationResult,
) -> ProvisionedWorktree:
    timestamp = datetime(2026, 8, 11, 17, 0, tzinfo=UTC).isoformat()
    return ProvisionedWorktree(
        reference=WorktreeReference(
            execution_id=execution_id,
            project_id="f47-fixture",
            project_root=project_root,
            worktree_path=project_root,
            base_commit_sha=fixture.commit_sha,
            original_branch=fixture.branch,
            worktree_branch=f"harness/{execution_id}",
            worktree_head_sha=fixture.commit_sha,
            status=WorktreeStatus.ACTIVE,
            failure_code=None,
            created_at=timestamp,
            updated_at=timestamp,
        ),
        path_guard=PathGuard(project_root),
        trust_boundary=boundary,
    )


def _verification_boundary(project_root: Path) -> TrustEvaluationResult:
    return TrustBoundaryEvaluator(
        project_root,
        authorization=TrustAuthorization(
            repository_root=str(project_root.resolve()),
            executable_aliases=("python",),
            secret_grants=tuple(
                SecretGrant(name=name, consumers=("terminal:python",))
                for name in ("PATH", "Path", "SYSTEMROOT", "SystemRoot")
            ),
        ),
    ).evaluate()


def _service(
    project_root: Path,
    storage: AtomicFileStateStorage,
    execution_id: str,
    fixture: _Fixture,
) -> ExecutionLifecycleService:
    boundary = _verification_boundary(project_root)
    worktree = _worktree(project_root, execution_id, fixture, boundary)
    return ExecutionLifecycleService(
        project_root,
        storage,
        NodeExecutorRegistry(
            deterministic=DeterministicNodeExecutor(_Backend()),
        ),
        git_identity_provider=lambda: (fixture.commit_sha, fixture.branch),
        verification_worktree_provider=lambda selected: (
            worktree
            if selected == execution_id
            else pytest.fail("unexpected execution id")
        ),
        trust_boundary=boundary,
    )


def test_policy_enabled_lifecycle_persists_gate_and_guards_completed(
    tmp_path: Path,
) -> None:
    fixture = _write_fixture(tmp_path, passing=True)
    storage = AtomicFileStateStorage(tmp_path)
    execution_id = "exec-f47-pass"
    service = _service(tmp_path, storage, execution_id, fixture)

    graph_result = service.start(
        fixture.artifact,
        execution_id=execution_id,
        initial_input={},
        configuration={},
    )

    assert graph_result.outcome == "success"
    assert storage.load_execution(execution_id).current_state == ExecutionState.VERIFYING

    suite = service.verify(execution_id)

    assert suite.all_passed is True
    assert suite.verified_commit_sha == fixture.commit_sha
    assert suite.gate_results[0].status is GateStatus.PASSED
    assert suite.gate_results[0].argv == ("python", "-m", "pytest")
    assert suite.gate_results[0].cwd == "."
    assert suite.gate_results[0].exit_code == 0
    assert suite.gate_results[0].duration_ms >= 0
    assert "1 passed" in suite.gate_results[0].stdout
    assert suite.gate_results[1].status is GateStatus.SKIPPED_NOT_APPLICABLE
    assert suite.gate_results[1].required is False
    assert suite.gate_results[1].argv == ()
    assert storage.load_execution(execution_id).current_state == ExecutionState.COMPLETED

    event_types = tuple(event.event_type for event in storage.load_events(execution_id))
    assert event_types[-4:] == (
        VERIFICATION_GATE_STARTED,
        VERIFICATION_GATE_RECORDED,
        VERIFICATION_SUITE_RECORDED,
        "STATE_TRANSITIONED",
    )
    with pytest.raises(
        VerificationLifecycleIntegrityError,
        match="cannot run verification again",
    ):
        service.verify(execution_id)


def test_failed_suite_stays_verifying_and_is_recovered_without_rerun(
    tmp_path: Path,
) -> None:
    fixture = _write_fixture(tmp_path, passing=False)
    storage = AtomicFileStateStorage(tmp_path)
    execution_id = "exec-f47-fail"
    service = _service(tmp_path, storage, execution_id, fixture)
    service.start(
        fixture.artifact,
        execution_id=execution_id,
        initial_input={},
        configuration={},
    )

    first = service.verify(execution_id)
    event_count = len(storage.load_events(execution_id))
    second = service.verify(execution_id)

    assert first == second
    assert first.all_passed is False
    assert first.gate_results[0].status is GateStatus.FAILED
    assert first.gate_results[0].exit_code != 0
    assert storage.load_execution(execution_id).current_state == ExecutionState.VERIFYING
    assert len(storage.load_events(execution_id)) == event_count


def test_execution_attempt_budget_blocks_before_verification_gate_effect(
    tmp_path: Path,
) -> None:
    fixture = _write_fixture(tmp_path, passing=True)
    storage = AtomicFileStateStorage(tmp_path)
    execution_id = "exec-f54-verification-budget"
    service = _service(tmp_path, storage, execution_id, fixture)
    service.start(
        fixture.artifact,
        execution_id=execution_id,
        initial_input={},
        configuration={"budget": {"max_attempts": 1}},
    )

    with pytest.raises(ExecutionBudgetExceededError):
        service.verify(execution_id)

    assert storage.load_execution(execution_id).current_state == (
        ExecutionState.FAILED_BUDGET_EXCEEDED
    )
    event_types = tuple(event.event_type for event in storage.load_events(execution_id))
    assert "BUDGET_EXCEEDED" in event_types
    assert VERIFICATION_GATE_STARTED not in event_types


def test_open_gate_write_ahead_blocks_automatic_reexecution(tmp_path: Path) -> None:
    fixture = _write_fixture(tmp_path, passing=True)
    storage = AtomicFileStateStorage(tmp_path)
    execution_id = "exec-f47-ambiguous"
    service = _service(tmp_path, storage, execution_id, fixture)
    service.start(
        fixture.artifact,
        execution_id=execution_id,
        initial_input={},
        configuration={},
    )
    storage.append_event(
        execution_id,
        ExecutionEvent(
            event_id="verification-open-effect",
            execution_id=execution_id,
            sequence_number=0,
            event_type=VERIFICATION_GATE_STARTED,
            timestamp=datetime.now(UTC),
            graph_name=storage.load_execution(execution_id).workflow_name,
            node_id=None,
            attempt=0,
            actor="verification_lifecycle_test",
            payload={},
        ),
    )

    with pytest.raises(
        VerificationLifecycleIntegrityError,
        match="incomplete or duplicate suite",
    ):
        service.verify(execution_id)

    assert storage.load_execution(execution_id).current_state == ExecutionState.VERIFYING


def test_dirty_worktree_blocks_before_any_verification_effect(tmp_path: Path) -> None:
    fixture = _write_fixture(tmp_path, passing=True)
    storage = AtomicFileStateStorage(tmp_path)
    execution_id = "exec-f47-dirty"
    service = _service(tmp_path, storage, execution_id, fixture)
    service.start(
        fixture.artifact,
        execution_id=execution_id,
        initial_input={},
        configuration={},
    )
    (tmp_path / "uncommitted.py").write_text("CHANGED = True\n", encoding="utf-8")

    with pytest.raises(
        VerificationLifecyclePrerequisiteError,
        match="worktree could not be validated",
    ):
        service.verify(execution_id)

    assert storage.load_execution(execution_id).current_state == (
        ExecutionState.BLOCKED_PREREQUISITE
    )
    assert not any(
        event.event_type in {
            VERIFICATION_GATE_STARTED,
            VERIFICATION_GATE_RECORDED,
            VERIFICATION_SUITE_RECORDED,
        }
        for event in storage.load_events(execution_id)
    )
