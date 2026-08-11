"""End-to-end F2.5 crash, resume, approval, cancellation, and integrity tests."""

from __future__ import annotations

import multiprocessing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from ai_engineering_harness.compiler import GraphCompiler
from ai_engineering_harness.contracts.events import ExecutionEvent
from ai_engineering_harness.contracts.execution import ApprovalStatus, ExecutionRecord, ExecutionState
from ai_engineering_harness.persistence import (
    AtomicFileStateStorage,
    ExecutionBundleIntegrityError,
    ExecutionLock,
    StateWriteError,
)
from ai_engineering_harness.runtime import (
    DeterministicNodeExecutor,
    ExecutionCancellationError,
    ExecutionLifecycleService,
    GraphExecutionPausedResult,
    GraphExecutionResult,
    InterruptedNodeExecutionError,
    NodeExecutionContext,
    NodeExecutionResult,
    NodeExecutorRegistry,
    VerificationRequiredError,
)


@dataclass
class _MarkerBackend:
    marker: Path

    def execute(self, context: NodeExecutionContext) -> NodeExecutionResult:
        with self.marker.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(f"{context.execution_id}:{context.node.id}\n")
            stream.flush()
        return NodeExecutionResult.completed({"node": context.node.id})


class _FailOutcomeCasStorage(AtomicFileStateStorage):
    def __init__(self, project_root: Path) -> None:
        super().__init__(project_root)
        self.fail_outcome_cas = True

    def compare_and_set_execution(
        self,
        execution_id: str,
        expected_revision: int,
        replacement: ExecutionRecord,
        *,
        lock: ExecutionLock | None = None,
    ) -> ExecutionRecord:
        if self.fail_outcome_cas and replacement.current_node_id == "completed":
            self.fail_outcome_cas = False
            raise StateWriteError(
                "simulated crash after durable node outcome",
                execution_id=execution_id,
            )
        return super().compare_and_set_execution(
            execution_id,
            expected_revision,
            replacement,
            lock=lock,
        )


class _FailOutcomeAppendStorage(AtomicFileStateStorage):
    def __init__(self, project_root: Path) -> None:
        super().__init__(project_root)
        self.fail_outcome_append = True

    def append_event(
        self,
        execution_id: str,
        event: ExecutionEvent,
        *,
        lock: ExecutionLock | None = None,
    ) -> ExecutionEvent:
        if self.fail_outcome_append and event.event_type == "NODE_COMPLETED":
            self.fail_outcome_append = False
            raise StateWriteError(
                "simulated interruption before durable node outcome",
                execution_id=execution_id,
            )
        return super().append_event(execution_id, event, lock=lock)


def _artifact(
    project_root: Path,
    *,
    workflow: str,
    human_approval: bool = False,
) -> Path:
    node = (
        "  - id: approval\n"
        "    type: human_approval\n"
        "    approval_strategy: explicit\n"
        "    on_success: completed\n"
        "    on_failure: failed\n"
        if human_approval
        else "  - id: execute\n"
        "    type: deterministic\n"
        "    executor: deterministic_gate\n"
        "    gate_name: e2e\n"
        "    on_success: completed\n"
        "    on_failure: failed\n"
    )
    entrypoint = "approval" if human_approval else "execute"
    spec = project_root / f"{workflow}.yaml"
    spec.write_text(
        f"""graph:
  name: {workflow}
  graph_schema_version: "1.0"
  definition_version: "1.0.0"
  entrypoint: {entrypoint}
  status: stable
nodes:
{node}terminal_states:
  - id: completed
    outcome: success
  - id: failed
    outcome: failure
policies: []
contracts: []
""",
        encoding="utf-8",
    )
    return GraphCompiler(project_root).compile_graph(spec, workflow)


def _service(
    root: Path,
    storage: AtomicFileStateStorage,
    *,
    marker: Path | None = None,
) -> ExecutionLifecycleService:
    registry = (
        NodeExecutorRegistry(
            deterministic=DeterministicNodeExecutor(_MarkerBackend(marker)),
        )
        if marker is not None
        else NodeExecutorRegistry()
    )
    return ExecutionLifecycleService(
        root,
        storage,
        registry,
        git_identity_provider=lambda: ("a" * 40, "task/f2.5-execution-resume"),
    )


def _resume_worker(
    root: str,
    execution_id: str,
    start_event: Any,
    result_queue: Any,
) -> None:
    service = _service(Path(root), AtomicFileStateStorage(Path(root)))
    start_event.wait(20)
    try:
        result = service.resume(execution_id)
    except VerificationRequiredError:
        result_queue.put(("verification_required", None, None))
    else:
        result_queue.put(("ok", result.outcome, result.final_revision))


def test_execution_resume_recovers_pending_outcome_without_reexecuting_completed_node(
    tmp_path: Path,
) -> None:
    compiled = _artifact(tmp_path, workflow="resume-outcome")
    marker = tmp_path / "backend-effects.log"
    storage = _FailOutcomeCasStorage(tmp_path)
    service = _service(tmp_path, storage, marker=marker)

    with pytest.raises(StateWriteError, match="after durable node outcome"):
        service.start(
            compiled,
            execution_id="exec-resume-outcome",
            initial_input={"request": "once"},
            configuration={},
        )

    before = storage.load_events("exec-resume-outcome")
    result = service.resume("exec-resume-outcome")
    after = storage.load_events("exec-resume-outcome")
    assert isinstance(result, GraphExecutionResult)
    assert result.outcome == "success"
    assert marker.read_text(encoding="utf-8").splitlines() == [
        "exec-resume-outcome:execute"
    ]
    assert [event.event_type for event in before].count("NODE_COMPLETED") == 1
    assert [event.event_type for event in after].count("NODE_COMPLETED") == 1
    assert storage.load_execution("exec-resume-outcome").current_state == ExecutionState.VERIFYING


def test_execution_resume_started_without_outcome_is_interrupted_without_retry(
    tmp_path: Path,
) -> None:
    compiled = _artifact(tmp_path, workflow="resume-interrupted")
    marker = tmp_path / "ambiguous-effects.log"
    storage = _FailOutcomeAppendStorage(tmp_path)
    service = _service(tmp_path, storage, marker=marker)

    with pytest.raises(StateWriteError, match="before durable node outcome"):
        service.start(
            compiled,
            execution_id="exec-resume-interrupted",
            initial_input={},
            configuration={},
        )
    journal_before = storage.load_events("exec-resume-interrupted")
    with pytest.raises(InterruptedNodeExecutionError) as captured:
        service.resume("exec-resume-interrupted")

    assert captured.value.classification == "requires_intervention"
    assert marker.read_text(encoding="utf-8").splitlines() == [
        "exec-resume-interrupted:execute"
    ]
    assert storage.load_events("exec-resume-interrupted") == journal_before


def test_execution_resume_concurrent_workers_do_not_duplicate_completed_effect(
    tmp_path: Path,
) -> None:
    compiled = _artifact(tmp_path, workflow="resume-concurrent")
    marker = tmp_path / "concurrent-effects.log"
    storage = _FailOutcomeCasStorage(tmp_path)
    service = _service(tmp_path, storage, marker=marker)
    with pytest.raises(StateWriteError):
        service.start(
            compiled,
            execution_id="exec-resume-concurrent",
            initial_input={},
            configuration={},
        )

    context = multiprocessing.get_context("spawn")
    start_event = context.Event()
    result_queue = context.Queue()
    workers = [
        context.Process(
            target=_resume_worker,
            args=(str(tmp_path), "exec-resume-concurrent", start_event, result_queue),
        )
        for _ in range(2)
    ]
    for worker in workers:
        worker.start()
    start_event.set()
    results = [result_queue.get(timeout=30) for _ in workers]
    for worker in workers:
        worker.join(timeout=30)
        assert worker.exitcode == 0

    assert sorted(result[0] for result in results) == ["ok", "verification_required"]
    assert marker.read_text(encoding="utf-8").splitlines() == [
        "exec-resume-concurrent:execute"
    ]
    assert storage.load_execution("exec-resume-concurrent").current_state == ExecutionState.VERIFYING


def test_execution_approval_paused_approve_and_resume_ignores_live_artifact(
    tmp_path: Path,
) -> None:
    compiled = _artifact(tmp_path, workflow="resume-approval", human_approval=True)
    storage = AtomicFileStateStorage(tmp_path)
    service = _service(tmp_path, storage)
    paused = service.start(
        compiled,
        execution_id="exec-resume-approval",
        initial_input={"subject": "immutable"},
        configuration={"profile": "frozen"},
    )
    assert isinstance(paused, GraphExecutionPausedResult)
    compiled.unlink()

    approved = service.approve("exec-resume-approval", approver="reviewer-e2e")
    result = service.resume("exec-resume-approval")
    assert approved.approval_status == ApprovalStatus.APPROVED
    assert isinstance(result, GraphExecutionResult)
    assert result.outcome == "success"
    assert storage.load_execution("exec-resume-approval").current_state == ExecutionState.VERIFYING


def test_execution_cancel_paused_is_final_and_resume_is_rejected(tmp_path: Path) -> None:
    compiled = _artifact(tmp_path, workflow="resume-cancel", human_approval=True)
    storage = AtomicFileStateStorage(tmp_path)
    service = _service(tmp_path, storage)
    service.start(
        compiled,
        execution_id="exec-resume-cancel",
        initial_input={},
        configuration={},
    )

    cancelled = service.cancel("exec-resume-cancel")
    assert cancelled.current_state == ExecutionState.CANCELLED
    assert cancelled.approval_status == ApprovalStatus.INVALIDATED
    assert service.cancel("exec-resume-cancel") == cancelled
    with pytest.raises(ExecutionCancellationError):
        service.resume("exec-resume-cancel")


def test_execution_resume_divergent_artifact_bundle_fails_and_preserves_tamper(
    tmp_path: Path,
) -> None:
    compiled = _artifact(tmp_path, workflow="resume-divergent", human_approval=True)
    storage = AtomicFileStateStorage(tmp_path)
    service = _service(tmp_path, storage)
    service.start(
        compiled,
        execution_id="exec-resume-divergent",
        initial_input={},
        configuration={},
    )
    artifact_path = (
        tmp_path
        / ".harness"
        / "artifacts"
        / "executions"
        / "exec-resume-divergent"
        / "artifact.json"
    )
    artifact_path.write_bytes(b'{"tampered":true}\n')
    tampered = artifact_path.read_bytes()
    record_before = storage.load_execution("exec-resume-divergent")
    journal_before = storage.load_events("exec-resume-divergent")

    with pytest.raises(ExecutionBundleIntegrityError):
        service.resume("exec-resume-divergent")

    assert artifact_path.read_bytes() == tampered
    assert storage.load_execution("exec-resume-divergent") == record_before
    assert storage.load_events("exec-resume-divergent") == journal_before
