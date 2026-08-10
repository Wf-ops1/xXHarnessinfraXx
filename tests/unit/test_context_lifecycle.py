"""F4.3 lifecycle composition over immutable envelopes and durable context attempts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ai_engineering_harness.compiler import GraphCompiler
from ai_engineering_harness.contracts.events import ExecutionEvent
from ai_engineering_harness.contracts.execution import ExecutionState
from ai_engineering_harness.contracts.nodes import ContextSufficiencyReport
from ai_engineering_harness.contracts.structural_index import StructuralSymbol
from ai_engineering_harness.indexer import SnapshotManager
from ai_engineering_harness.persistence import (
    AtomicFileStateStorage,
    ExecutionLock,
    StateWriteError,
)
from ai_engineering_harness.runtime import (
    CONTEXT_EVALUATED,
    ContextPrerequisiteError,
    ContextRetryExhaustedError,
    DeterministicNodeExecutor,
    ExecutionConfigurationError,
    ExecutionLifecycleService,
    GraphExecutionResult,
    InsufficientContextError,
    NodeExecutionContext,
    NodeExecutionResult,
    NodeExecutorRegistry,
)

COMMIT_SHA = "a" * 40
_BASE_TIME = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)


class _Clock:
    def __init__(self) -> None:
        self.value = _BASE_TIME

    def __call__(self) -> datetime:
        self.value += timedelta(seconds=1)
        return self.value


class _Ids:
    def __init__(self) -> None:
        self.value = 0

    def __call__(self) -> str:
        self.value += 1
        return f"context-lifecycle-event-{self.value}"


@dataclass
class _TraceBackend:
    calls: list[dict[str, object]]

    def execute(self, context: NodeExecutionContext) -> NodeExecutionResult:
        self.calls.append(context.input_payload)
        return NodeExecutionResult.completed({"executed": context.node.id})


class _FailContextPayloadStorage(AtomicFileStateStorage):
    def store_payload(
        self,
        execution_id: str,
        payload: dict[str, object],
        *,
        lock: ExecutionLock | None = None,
    ) -> str:
        raise StateWriteError("controlled context payload failure", execution_id=execution_id)


class _FailPlanningTransitionOnceStorage(AtomicFileStateStorage):
    def __init__(self, project_root: Path) -> None:
        super().__init__(project_root)
        self.failure_pending = True

    def append_event(
        self,
        execution_id: str,
        event: ExecutionEvent,
        *,
        lock: ExecutionLock | None = None,
    ) -> ExecutionEvent:
        if (
            self.failure_pending
            and event.event_type == "STATE_TRANSITIONED"
            and event.payload.get("from_state") == ExecutionState.CONTEXT_ASSEMBLING.value
            and event.payload.get("to_state") == ExecutionState.PLANNING.value
        ):
            self.failure_pending = False
            raise StateWriteError(
                "controlled transition interruption",
                execution_id=execution_id,
            )
        return super().append_event(execution_id, event, lock=lock)


def _compiled_context_graph(project_root: Path) -> Path:
    spec = project_root / "new-feature.yaml"
    spec.write_text(
        """graph:
  name: new-feature
  graph_schema_version: "1.0"
  definition_version: "1.0.0"
  entrypoint: execute
  status: stable
nodes:
  - id: execute
    type: deterministic
    executor: deterministic_gate
    gate_name: lifecycle
    on_success: completed
    on_failure: failed
terminal_states:
  - id: completed
    outcome: success
  - id: failed
    outcome: failure
policies:
  - policies/context_sufficiency.yaml
contracts: []
""",
        encoding="utf-8",
    )
    return GraphCompiler(project_root).compile_graph(spec, "new-feature")


def _save_snapshot(project_root: Path) -> None:
    SnapshotManager(project_root).save_snapshot(
        COMMIT_SHA,
        [
            StructuralSymbol(
                kind="function",
                name="logging",
                qualified_name="logging",
                path="logging",
                line_start=1,
                line_end=2,
            )
        ],
    )


def _write_artifacts(project_root: Path, *, omit: str | None = None) -> None:
    root = project_root / ".harness" / "knowledge" / "artifacts"
    root.mkdir(parents=True, exist_ok=True)
    for artifact_id in (
        "prd",
        "domain_model",
        "non_functional_requirements",
        "acceptance_criteria",
        "architecture",
    ):
        if artifact_id != omit:
            (root / f"{artifact_id}.md").write_text(
                f"# {artifact_id}\n\nvalidated fixture\n",
                encoding="utf-8",
            )


def _envelope() -> dict[str, object]:
    return {
        "context_request": {
            "requirement_id": "req-logging",
            "graph_type": "new_feature",
            "query": "Add logging",
        },
        "graph_input": {"intent": "deliver"},
    }


def _service(
    project_root: Path,
    storage: AtomicFileStateStorage | None = None,
) -> tuple[ExecutionLifecycleService, AtomicFileStateStorage, list[dict[str, object]]]:
    selected_storage = storage or AtomicFileStateStorage(project_root)
    calls: list[dict[str, object]] = []
    service = ExecutionLifecycleService(
        project_root,
        selected_storage,
        NodeExecutorRegistry(
            deterministic=DeterministicNodeExecutor(_TraceBackend(calls)),
        ),
        clock=_Clock(),
        event_id_factory=_Ids(),
        owner_id_factory=lambda: "context-lifecycle-owner",
        git_identity_provider=lambda: (COMMIT_SHA, "task/f4.3-context"),
    )
    return service, selected_storage, calls


def _context_events(storage: AtomicFileStateStorage, execution_id: str):
    return tuple(
        event
        for event in storage.load_events(execution_id)
        if event.event_type == CONTEXT_EVALUATED
    )


def test_start_persists_envelope_decision_event_and_enters_graph_from_planning(
    tmp_path: Path,
) -> None:
    artifact = _compiled_context_graph(tmp_path)
    _save_snapshot(tmp_path)
    _write_artifacts(tmp_path)
    service, storage, calls = _service(tmp_path)

    result = service.start(
        artifact,
        execution_id="exec-context-success",
        initial_input=_envelope(),
        configuration={},
    )

    assert isinstance(result, GraphExecutionResult)
    assert result.outcome == "success"
    assert calls == [{"intent": "deliver"}]
    assert storage.load_execution("exec-context-success").current_state == ExecutionState.COMPLETED
    bundle = storage.load_execution_bundle("exec-context-success")
    assert storage.load_payload("exec-context-success", bundle.initial_input_digest) == _envelope()
    events = _context_events(storage, "exec-context-success")
    assert len(events) == 1
    assert events[0].payload["outcome"] == "sufficient"
    report = ContextSufficiencyReport.model_validate(
        storage.load_payload("exec-context-success", events[0].payload["payload_digest"])
    )
    assert report.is_sufficient is True
    state_edges = [
        (event.payload.get("from_state"), event.payload.get("to_state"))
        for event in storage.load_events("exec-context-success")
        if event.event_type == "STATE_TRANSITIONED"
    ]
    assert ("CONTEXT_ASSEMBLING", "PLANNING") in state_edges
    assert ("PLANNING", "EXECUTING") in state_edges


def test_insufficient_start_blocks_before_node_and_resume_reuses_original_envelope(
    tmp_path: Path,
) -> None:
    artifact = _compiled_context_graph(tmp_path)
    _save_snapshot(tmp_path)
    _write_artifacts(tmp_path, omit="prd")
    service, storage, calls = _service(tmp_path)

    with pytest.raises(InsufficientContextError):
        service.start(
            artifact,
            execution_id="exec-context-resume",
            initial_input=_envelope(),
            configuration={},
        )

    assert calls == []
    assert (
        storage.load_execution("exec-context-resume").current_state
        == ExecutionState.BLOCKED_INSUFFICIENT_CONTEXT
    )
    bundle = storage.load_execution_bundle("exec-context-resume")
    original = storage.load_payload("exec-context-resume", bundle.initial_input_digest)
    assert original == _envelope()
    _write_artifacts(tmp_path)

    result = service.resume("exec-context-resume")

    assert isinstance(result, GraphExecutionResult)
    assert result.outcome == "success"
    assert calls == [{"intent": "deliver"}]
    events = _context_events(storage, "exec-context-resume")
    assert [event.payload["attempt"] for event in events] == [1, 2]
    assert [event.payload["outcome"] for event in events] == ["insufficient", "sufficient"]
    assert storage.load_payload("exec-context-resume", bundle.initial_input_digest) == original


def test_retry_budget_is_initial_plus_two_resumes_then_failed_retry_exhausted(
    tmp_path: Path,
) -> None:
    artifact = _compiled_context_graph(tmp_path)
    _save_snapshot(tmp_path)
    service, storage, calls = _service(tmp_path)

    with pytest.raises(InsufficientContextError):
        service.start(
            artifact,
            execution_id="exec-context-exhausted",
            initial_input=_envelope(),
            configuration={},
        )
    with pytest.raises(InsufficientContextError):
        service.resume("exec-context-exhausted")
    with pytest.raises(InsufficientContextError):
        service.resume("exec-context-exhausted")
    with pytest.raises(ContextRetryExhaustedError):
        service.resume("exec-context-exhausted")

    assert calls == []
    assert (
        storage.load_execution("exec-context-exhausted").current_state
        == ExecutionState.FAILED_RETRY_EXHAUSTED
    )
    events = _context_events(storage, "exec-context-exhausted")
    assert [event.payload["attempt"] for event in events] == [1, 2, 3]
    assert all(event.payload["outcome"] == "insufficient" for event in events)


def test_missing_snapshot_is_blocked_prerequisite_without_context_event_or_node(
    tmp_path: Path,
) -> None:
    artifact = _compiled_context_graph(tmp_path)
    _write_artifacts(tmp_path)
    service, storage, calls = _service(tmp_path)

    with pytest.raises(ContextPrerequisiteError):
        service.start(
            artifact,
            execution_id="exec-context-prerequisite",
            initial_input=_envelope(),
            configuration={},
        )

    assert calls == []
    assert (
        storage.load_execution("exec-context-prerequisite").current_state
        == ExecutionState.BLOCKED_PREREQUISITE
    )
    assert _context_events(storage, "exec-context-prerequisite") == ()


def test_context_payload_storage_failure_is_blocked_prerequisite(tmp_path: Path) -> None:
    artifact = _compiled_context_graph(tmp_path)
    _save_snapshot(tmp_path)
    _write_artifacts(tmp_path)
    failing_storage = _FailContextPayloadStorage(tmp_path)
    service, storage, calls = _service(tmp_path, failing_storage)

    with pytest.raises(ContextPrerequisiteError, match="durably"):
        service.start(
            artifact,
            execution_id="exec-context-storage-failure",
            initial_input=_envelope(),
            configuration={},
        )

    assert calls == []
    assert (
        storage.load_execution("exec-context-storage-failure").current_state
        == ExecutionState.BLOCKED_PREREQUISITE
    )
    assert _context_events(storage, "exec-context-storage-failure") == ()


def test_resume_recovers_durable_context_decision_after_interrupted_transition(
    tmp_path: Path,
) -> None:
    artifact = _compiled_context_graph(tmp_path)
    _save_snapshot(tmp_path)
    _write_artifacts(tmp_path)
    interrupted_storage = _FailPlanningTransitionOnceStorage(tmp_path)
    service, storage, calls = _service(tmp_path, interrupted_storage)

    with pytest.raises(StateWriteError, match="controlled transition interruption"):
        service.start(
            artifact,
            execution_id="exec-context-interrupted",
            initial_input=_envelope(),
            configuration={},
        )

    assert calls == []
    assert (
        storage.load_execution("exec-context-interrupted").current_state
        == ExecutionState.CONTEXT_ASSEMBLING
    )
    assert len(_context_events(storage, "exec-context-interrupted")) == 1

    result = service.resume("exec-context-interrupted")

    assert isinstance(result, GraphExecutionResult)
    assert result.outcome == "success"
    assert calls == [{"intent": "deliver"}]
    assert len(_context_events(storage, "exec-context-interrupted")) == 1


@pytest.mark.parametrize(
    "initial_input",
    [
        {"context_request": _envelope()["context_request"]},
        {**_envelope(), "extra": True},
        {"context_request": _envelope()["context_request"], "graph_input": []},
    ],
)
def test_context_envelope_is_exact_and_rejected_before_bundle_creation(
    tmp_path: Path,
    initial_input: dict[str, object],
) -> None:
    artifact = _compiled_context_graph(tmp_path)
    service, storage, calls = _service(tmp_path)

    with pytest.raises(ExecutionConfigurationError, match="exactly"):
        service.start(
            artifact,
            execution_id="exec-context-envelope",
            initial_input=initial_input,
            configuration={},
        )

    assert calls == []
    assert storage.list_executions() == ()
