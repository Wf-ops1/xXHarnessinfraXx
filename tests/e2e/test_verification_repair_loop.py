"""F4.8 canonical verification failure, repair, targeted retry, and full suite."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ai_engineering_harness.compiler import GraphCompiler
from ai_engineering_harness.contracts import ExecutionRecord, ExecutionState
from ai_engineering_harness.persistence import (
    AtomicFileStateStorage,
    ExecutionLock,
    StateWriteError,
)
from ai_engineering_harness.runtime import (
    VERIFICATION_REPAIR_SCHEDULED,
    VERIFICATION_SUITE_RECORDED,
    DeterministicNodeExecutor,
    ExecutionLifecycleService,
    GraphExecutionResult,
    ModelCallMetadata,
    NodeExecutionContext,
    NodeExecutionResult,
    NodeExecutorRegistry,
    RetryContext,
    VerificationRequiredError,
    VerificationRetryExhaustedError,
)
from ai_engineering_harness.security import PathGuard
from ai_engineering_harness.workspace import (
    ProvisionedWorktree,
    WorktreeReference,
    WorktreeStatus,
)


def _git(project: Path, *argv: str) -> str:
    return subprocess.run(
        ["git", *argv],
        cwd=project,
        check=True,
        shell=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()


@dataclass
class _RepairBackend:
    project: Path
    contexts: list[RetryContext] = field(default_factory=list)
    fix_on_retry: bool = True
    emit_usage: bool = False

    def execute(self, context: NodeExecutionContext) -> NodeExecutionResult:
        if context.node.id == "repair" and context.attempt > 1:
            assert context.retry_context is not None
            self.contexts.append(context.retry_context)
            assertion = "True" if self.fix_on_retry else "False"
            (self.project / "tests" / "test_target.py").write_text(
                f"def test_target():\n    assert {assertion}\n"
                f"# repair attempt {context.attempt}\n",
                encoding="utf-8",
            )
            _git(self.project, "add", "tests/test_target.py")
            _git(self.project, "commit", "-m", "repair failing verification")
        model_calls: tuple[ModelCallMetadata, ...] = ()
        if self.emit_usage and context.node.id == "repair" and context.attempt > 1:
            model_calls = (
                ModelCallMetadata(
                    provider_id="test",
                    model_name="test-model",
                    prompt_tokens=1,
                    completion_tokens=1,
                    total_tokens=2,
                    response_id=f"repair-{context.attempt}",
                ),
            )
        return NodeExecutionResult.completed(
            {"node": context.node.id},
            model_calls=model_calls,
        )


def _write_project(
    project: Path,
    *,
    retry_max: int = 2,
    max_tokens: int = 1000,
    max_cost: float = 1.0,
    max_duration: int = 300,
    max_iterations: int = 2,
) -> tuple[Path, str, str]:
    (project / ".harness" / "policies").mkdir(parents=True)
    (project / "tests").mkdir()
    (project / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\naddopts = '-p no:cacheprovider'\n",
        encoding="utf-8",
    )
    (project / "tests" / "test_target.py").write_text(
        "def test_target():\n    assert False\n",
        encoding="utf-8",
    )
    (project / ".harness" / "policies" / "verification_policy.yaml").write_text(
        """policy_id: f48-verification-v1
policy_schema_version: "1.0"
definition_version: "1.0.0"
applies_to:
  - f4-8-fixture
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
    (project / ".harness" / "policies" / "retry_cost_policy.yaml").write_text(
        f"""policy_id: f48-retry-cost-v1
policy_schema_version: "1.0"
definition_version: "1.0.0"
context_strategy: snapshot_fixed_with_retry_evolution
semantic_cache_threshold: 0.82
context_deduplication_threshold: 0.85
model_routing:
  retry_0: test-model
  retry_1: test-model
  retry_2: test-model
  retry_max: {retry_max}
cost_budget:
  max_tokens_per_node: {max_tokens}
  max_cost_per_execution_usd: {max_cost:.9f}
  input_cost_per_million_tokens_usd: 1.0
  output_cost_per_million_tokens_usd: 1.0
  max_retry_duration_seconds: {max_duration}
  escalate_on_budget_exceeded: true
""",
        encoding="utf-8",
    )
    graph = project / "graph.yaml"
    graph.write_text(
        f"""graph:
  name: f4-8-fixture
  graph_schema_version: "1.0"
  definition_version: "1.0.0"
  entrypoint: repair
  status: stable
nodes:
  - id: repair
    type: deterministic
    executor: deterministic_gate
    gate_name: repair
    on_success: verification
    on_failure: repair
    retry_policy:
      max_iterations: {max_iterations}
      exit_condition: tests_passed
  - id: verification
    type: deterministic
    executor: deterministic_policy
    policy_ref: policies/verification_policy.yaml
    on_success: completed
    on_failure: repair
    retry_policy:
      max_iterations: {max_iterations}
      exit_condition: tests_passed
terminal_states:
  - id: completed
    outcome: success
  - id: failed
    outcome: failure
policies:
  - policies/verification_policy.yaml
  - policies/retry_cost_policy.yaml
contracts: []
""",
        encoding="utf-8",
    )
    (project / ".gitignore").write_text(
        ".harness/state/\n.harness/artifacts/\n__pycache__/\n*.pyc\n",
        encoding="utf-8",
    )
    _git(project, "init", "--quiet")
    _git(project, "config", "user.name", "F4.8 Test")
    _git(project, "config", "user.email", "f48@example.invalid")
    _git(project, "add", ".")
    _git(project, "commit", "-m", "broken fixture")
    commit = _git(project, "rev-parse", "HEAD")
    branch = _git(project, "symbolic-ref", "--quiet", "--short", "HEAD")
    artifact = GraphCompiler(project).compile_graph(graph, "f4-8-fixture")
    return artifact, commit, branch


def _worktree_provider(
    project: Path,
    *,
    execution_id: str,
    base_commit: str,
    branch: str,
):
    def provide(selected: str) -> ProvisionedWorktree:
        if selected != execution_id:
            pytest.fail("unexpected execution id")
        head = _git(project, "rev-parse", "HEAD")
        timestamp = datetime(2026, 8, 11, 22, 0, tzinfo=UTC).isoformat()
        return ProvisionedWorktree(
            reference=WorktreeReference(
                execution_id=execution_id,
                project_id="f48-fixture",
                project_root=project,
                worktree_path=project,
                base_commit_sha=base_commit,
                original_branch=branch,
                worktree_branch=f"harness/{execution_id}",
                worktree_head_sha=head,
                status=WorktreeStatus.ACTIVE,
                failure_code=None,
                created_at=timestamp,
                updated_at=timestamp,
            ),
            path_guard=PathGuard(project),
        )

    return provide


@dataclass
class _Clock:
    current: datetime

    def __call__(self) -> datetime:
        return self.current

    def advance(self, seconds: int) -> None:
        self.current += timedelta(seconds=seconds)


class _FailRepairCursorCasStorage(AtomicFileStateStorage):
    def __init__(self, project_root: Path) -> None:
        super().__init__(project_root)
        self.fail_repair_cursor_cas = False

    def arm_repair_cursor_failure(self) -> None:
        self.fail_repair_cursor_cas = True

    def compare_and_set_execution(
        self,
        execution_id: str,
        expected_revision: int,
        replacement: ExecutionRecord,
        *,
        lock: ExecutionLock | None = None,
    ) -> ExecutionRecord:
        if (
            self.fail_repair_cursor_cas
            and replacement.current_state is ExecutionState.EXECUTING
            and replacement.current_node_id == "repair"
        ):
            self.fail_repair_cursor_cas = False
            raise StateWriteError(
                "controlled verification repair cursor CAS failure",
                execution_id=execution_id,
            )
        return super().compare_and_set_execution(
            execution_id,
            expected_revision,
            replacement,
            lock=lock,
        )


def _service(
    project: Path,
    storage: AtomicFileStateStorage,
    backend: _RepairBackend,
    *,
    execution_id: str,
    base_commit: str,
    branch: str,
    clock: _Clock | None = None,
) -> ExecutionLifecycleService:
    return ExecutionLifecycleService(
        project,
        storage,
        NodeExecutorRegistry(
            deterministic=DeterministicNodeExecutor(backend),
        ),
        clock=clock,
        git_identity_provider=lambda: (base_commit, branch),
        verification_worktree_provider=_worktree_provider(
            project,
            execution_id=execution_id,
            base_commit=base_commit,
            branch=branch,
        ),
    )


def _reach_failed_targeted_attempt(
    service: ExecutionLifecycleService,
    artifact: Path,
    storage: AtomicFileStateStorage,
    execution_id: str,
) -> None:
    service.start(
        artifact,
        execution_id=execution_id,
        initial_input={},
        configuration={},
    )
    assert service.verify(execution_id).all_passed is False
    result = service.resume(execution_id)
    assert isinstance(result, GraphExecutionResult)
    assert result.outcome == "success"
    assert service.verify(execution_id).all_passed is False
    event_count = len(storage.load_events(execution_id))
    assert service.verify(execution_id).all_passed is False
    assert len(storage.load_events(execution_id)) == event_count
    assert storage.load_execution(execution_id).current_state is ExecutionState.VERIFYING


def _assert_budget_blocked(
    service: ExecutionLifecycleService,
    storage: AtomicFileStateStorage,
    execution_id: str,
    reason: str,
) -> None:
    with pytest.raises(
        VerificationRetryExhaustedError,
        match="durably exhausted",
    ):
        service.resume(execution_id)
    assert storage.load_execution(execution_id).current_state is (
        ExecutionState.FAILED_RETRY_EXHAUSTED
    )
    assert storage.load_events(execution_id)[-1].payload["reason"] == reason


def test_failed_commit_is_repaired_then_targeted_and_full_suites_run(
    tmp_path: Path,
) -> None:
    artifact, broken_commit, branch = _write_project(tmp_path)
    storage = AtomicFileStateStorage(tmp_path)
    backend = _RepairBackend(tmp_path)
    execution_id = "exec-f48-repair"
    service = _service(
        tmp_path,
        storage,
        backend,
        execution_id=execution_id,
        base_commit=broken_commit,
        branch=branch,
    )

    service.start(
        artifact,
        execution_id=execution_id,
        initial_input={},
        configuration={},
    )
    failed = service.verify(execution_id)

    assert failed.all_passed is False
    assert storage.load_execution(execution_id).current_state is ExecutionState.VERIFYING
    assert "assert False" in failed.gate_results[0].stdout

    repaired_graph = service.resume(execution_id)
    repaired_commit = _git(tmp_path, "rev-parse", "HEAD")

    assert isinstance(repaired_graph, GraphExecutionResult)
    assert repaired_graph.outcome == "success"
    assert repaired_commit != broken_commit
    assert len(backend.contexts) == 1
    context = backend.contexts[0]
    assert context.failed_commit_sha == broken_commit
    assert context.failed_gates == ("unit_test",)
    assert "assert False" in context.redacted_stdout
    assert context.remaining_budget.remaining_time_seconds is not None
    assert storage.load_execution(execution_id).current_state is ExecutionState.VERIFYING
    with pytest.raises(VerificationRequiredError, match="after its repair"):
        service.resume(execution_id)
    assert len(backend.contexts) == 1

    passed = service.verify(execution_id)

    assert passed.all_passed is True
    assert passed.verified_commit_sha == repaired_commit
    assert storage.load_execution(execution_id).current_state is ExecutionState.COMPLETED
    events = storage.load_events(execution_id)
    schedules = [
        event for event in events if event.event_type == VERIFICATION_REPAIR_SCHEDULED
    ]
    suites = [
        event for event in events if event.event_type == VERIFICATION_SUITE_RECORDED
    ]
    assert len(schedules) == 1
    assert [event.payload["attempt"] for event in suites] == [1, 2, 3]
    assert len(suites[0].payload["gate_result_digests"]) == 2
    assert len(suites[1].payload["gate_result_digests"]) == 1
    assert suites[1].payload["all_passed"] is True
    assert len(suites[2].payload["gate_result_digests"]) == 2
    assert suites[2].payload["all_passed"] is True
    completed_transition = next(
        index
        for index, event in enumerate(events)
        if event.event_type == "STATE_TRANSITIONED"
        and event.payload.get("to_state") == ExecutionState.COMPLETED.value
    )
    assert completed_transition > events.index(suites[2])


def test_pending_repair_cursor_is_recovered_without_duplicate_effect(
    tmp_path: Path,
) -> None:
    artifact, broken_commit, branch = _write_project(tmp_path)
    storage = _FailRepairCursorCasStorage(tmp_path)
    backend = _RepairBackend(tmp_path)
    execution_id = "exec-f48-repair-cursor-crash"
    service = _service(
        tmp_path,
        storage,
        backend,
        execution_id=execution_id,
        base_commit=broken_commit,
        branch=branch,
    )
    service.start(
        artifact,
        execution_id=execution_id,
        initial_input={},
        configuration={},
    )
    assert service.verify(execution_id).all_passed is False
    storage.arm_repair_cursor_failure()

    with pytest.raises(
        StateWriteError,
        match="controlled verification repair cursor CAS failure",
    ):
        service.resume(execution_id)

    events = storage.load_events(execution_id)
    assert backend.contexts == []
    assert sum(
        event.event_type == VERIFICATION_REPAIR_SCHEDULED for event in events
    ) == 1
    assert storage.load_execution(execution_id).current_state is ExecutionState.EXECUTING

    recovered = service.resume(execution_id)

    assert isinstance(recovered, GraphExecutionResult)
    assert recovered.outcome == "success"
    assert len(backend.contexts) == 1
    assert sum(
        event.event_type == VERIFICATION_REPAIR_SCHEDULED
        for event in storage.load_events(execution_id)
    ) == 1
    assert service.verify(execution_id).all_passed is True
    assert storage.load_execution(execution_id).current_state is ExecutionState.COMPLETED


def test_correction_node_limit_blocks_before_first_external_retry(
    tmp_path: Path,
) -> None:
    artifact, broken_commit, branch = _write_project(
        tmp_path,
        max_iterations=1,
    )
    storage = AtomicFileStateStorage(tmp_path)
    execution_id = "exec-f48-node-limit"
    service = _service(
        tmp_path,
        storage,
        _RepairBackend(tmp_path),
        execution_id=execution_id,
        base_commit=broken_commit,
        branch=branch,
    )
    service.start(
        artifact,
        execution_id=execution_id,
        initial_input={},
        configuration={},
    )
    assert service.verify(execution_id).all_passed is False
    _assert_budget_blocked(
        service,
        storage,
        execution_id,
        "verification_node_retry_exhausted",
    )


def test_execution_attempt_limit_blocks_second_repair(tmp_path: Path) -> None:
    artifact, broken_commit, branch = _write_project(
        tmp_path,
        retry_max=1,
        max_iterations=3,
    )
    storage = AtomicFileStateStorage(tmp_path)
    execution_id = "exec-f48-execution-limit"
    service = _service(
        tmp_path,
        storage,
        _RepairBackend(tmp_path, fix_on_retry=False),
        execution_id=execution_id,
        base_commit=broken_commit,
        branch=branch,
    )
    _reach_failed_targeted_attempt(service, artifact, storage, execution_id)
    _assert_budget_blocked(
        service,
        storage,
        execution_id,
        "verification_execution_retry_exhausted",
    )


@pytest.mark.parametrize(
    ("max_tokens", "max_cost", "reason"),
    [
        (2, 1.0, "verification_token_budget_exhausted"),
        (1000, 0.000001, "verification_cost_budget_exhausted"),
    ],
)
def test_persisted_model_usage_blocks_token_or_accounted_cost_budget(
    tmp_path: Path,
    max_tokens: int,
    max_cost: float,
    reason: str,
) -> None:
    artifact, broken_commit, branch = _write_project(
        tmp_path,
        max_tokens=max_tokens,
        max_cost=max_cost,
        max_iterations=3,
    )
    storage = AtomicFileStateStorage(tmp_path)
    execution_id = f"exec-f48-{reason}"
    service = _service(
        tmp_path,
        storage,
        _RepairBackend(tmp_path, fix_on_retry=False, emit_usage=True),
        execution_id=execution_id,
        base_commit=broken_commit,
        branch=branch,
    )
    _reach_failed_targeted_attempt(service, artifact, storage, execution_id)
    _assert_budget_blocked(service, storage, execution_id, reason)


def test_persisted_deadline_blocks_second_repair(tmp_path: Path) -> None:
    artifact, broken_commit, branch = _write_project(
        tmp_path,
        max_duration=1,
        max_iterations=3,
    )
    storage = AtomicFileStateStorage(tmp_path)
    execution_id = "exec-f48-time-limit"
    clock = _Clock(datetime(2026, 8, 11, 23, 30, tzinfo=UTC))
    service = _service(
        tmp_path,
        storage,
        _RepairBackend(tmp_path, fix_on_retry=False),
        execution_id=execution_id,
        base_commit=broken_commit,
        branch=branch,
        clock=clock,
    )
    _reach_failed_targeted_attempt(service, artifact, storage, execution_id)
    clock.advance(2)
    _assert_budget_blocked(
        service,
        storage,
        execution_id,
        "verification_time_budget_exhausted",
    )
