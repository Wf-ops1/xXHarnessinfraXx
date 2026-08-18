"""Focused F2.4 tests for event-sourced state replay and recovery."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from ai_engineering_harness.contracts.events import ExecutionEvent
from ai_engineering_harness.contracts.execution import (
    ApprovalStatus,
    ExecutionRecord,
    ExecutionState,
)
from ai_engineering_harness.persistence import (
    AtomicFileStateStorage,
    ExecutionLock,
    ExecutionNotFoundError,
    StateWriteError,
)
from ai_engineering_harness.runtime import (
    VALID_STATE_TRANSITIONS,
    EventSourcedStateMachine,
    InvalidStateTransitionError,
    StateMachineError,
    StateReplayError,
    StateReplayResult,
    StateTransitionIntegrityError,
    WorkflowState,
    WorkflowStateMachine,
)

_BASE_TIME = datetime(2020, 1, 1, tzinfo=UTC)
_ZERO_DIGEST = f"sha256:{'0' * 64}"
_PAYLOAD_KEYS = {
    "from_state",
    "to_state",
    "node_id",
    "attempt",
    "reason",
    "record_revision",
    "fencing_token",
}


class _Clock:
    def __init__(self, value: datetime = _BASE_TIME) -> None:
        self.value = value

    def __call__(self) -> datetime:
        self.value += timedelta(seconds=1)
        return self.value


class _EventIds:
    def __init__(self) -> None:
        self.value = 0

    def __call__(self) -> str:
        self.value += 1
        return f"state-event-{self.value}"


class _FailingCasStorage(AtomicFileStateStorage):
    def __init__(self, project_root: Path) -> None:
        super().__init__(project_root)
        self.fail_next_cas = True

    def compare_and_set_execution(
        self,
        execution_id: str,
        expected_revision: int,
        replacement: ExecutionRecord,
        *,
        lock: ExecutionLock | None = None,
    ) -> ExecutionRecord:
        if self.fail_next_cas:
            self.fail_next_cas = False
            raise StateWriteError(
                "controlled state CAS failure",
                execution_id=execution_id,
            )
        return super().compare_and_set_execution(
            execution_id,
            expected_revision,
            replacement,
            lock=lock,
        )


def _record(
    execution_id: str,
    **overrides: object,
) -> ExecutionRecord:
    document: dict[str, object] = {
        "record_schema_version": "1.0",
        "revision": 0,
        "execution_id": execution_id,
        "workflow_name": "state-machine-test",
        "artifact_digest": _ZERO_DIGEST,
        "base_commit_sha": "a" * 40,
        "original_branch": "test",
        "worktree_path": None,
        "current_node_id": "start",
        "current_state": ExecutionState.INITIATED,
        "attempt_by_node": {},
        "created_at": _BASE_TIME,
        "updated_at": _BASE_TIME,
        "configuration_digest": _ZERO_DIGEST,
        "approval_status": ApprovalStatus.NOT_REQUIRED,
        "candidate_commit_sha": None,
        "promotion_commit_sha": None,
        "failure": None,
    }
    document.update(overrides)
    return ExecutionRecord.model_validate(document)


def _record_path(root: Path, execution_id: str) -> Path:
    return (
        root
        / ".harness"
        / "state"
        / "executions"
        / execution_id
        / "execution.json"
    )


def _journal_path(root: Path, execution_id: str) -> Path:
    return _record_path(root, execution_id).with_name("event-journal.jsonl")


def _append_transition(
    storage: AtomicFileStateStorage,
    execution_id: str,
    *,
    event_id: str,
    from_state: str = "INITIATED",
    to_state: str = "EXECUTING",
    revision: object = 1,
    fencing_token: object = 1,
    attempt: object = 1,
    reason: object = "graph_execution_started",
    extra: bool = False,
    timestamp: datetime = _BASE_TIME + timedelta(seconds=1),
) -> ExecutionEvent:
    return storage.append_event(
        execution_id,
        _transition_event(
            execution_id,
            event_id=event_id,
            from_state=from_state,
            to_state=to_state,
            revision=revision,
            fencing_token=fencing_token,
            attempt=attempt,
            reason=reason,
            extra=extra,
            timestamp=timestamp,
        ),
    )


def _transition_event(
    execution_id: str,
    *,
    event_id: str,
    from_state: str = "INITIATED",
    to_state: str = "EXECUTING",
    revision: object = 1,
    fencing_token: object = 1,
    attempt: object = 1,
    reason: object = "graph_execution_started",
    extra: bool = False,
    timestamp: datetime = _BASE_TIME + timedelta(seconds=1),
) -> ExecutionEvent:
    payload: dict[str, object] = {
        "from_state": from_state,
        "to_state": to_state,
        "node_id": "start",
        "attempt": attempt,
        "reason": reason,
        "record_revision": revision,
        "fencing_token": fencing_token,
    }
    if extra:
        payload["unexpected"] = True
    return ExecutionEvent(
        event_id=event_id,
        execution_id=execution_id,
        sequence_number=0,
        event_type="STATE_TRANSITIONED",
        timestamp=timestamp,
        graph_name="state-machine-test",
        node_id="start",
        attempt=attempt if type(attempt) is int else 1,
        actor="state_machine_test",
        payload=payload,
    )


def test_public_alias_states_transition_payload_and_snapshot_fields_are_exact(
    tmp_path: Path,
) -> None:
    execution_id = "exec-state-public"
    storage = AtomicFileStateStorage(tmp_path)
    original = _record(execution_id)
    storage.create_execution(original)
    machine = WorkflowStateMachine(
        storage,
        execution_id,
        clock=_Clock(),
        event_id_factory=_EventIds(),
    )

    persisted = machine.transition_to(
        WorkflowState.PLANNING,
        node_id="start",
        attempt=0,
        reason="planning_started",
    )
    event = storage.load_events(execution_id)[0]

    assert WorkflowState is ExecutionState
    assert WorkflowStateMachine is EventSourcedStateMachine
    assert machine.current_state == ExecutionState.PLANNING
    assert persisted.current_state == ExecutionState.PLANNING
    assert persisted.revision == 1
    assert set(event.payload) == _PAYLOAD_KEYS
    assert event.payload == {
        "from_state": "INITIATED",
        "to_state": "PLANNING",
        "node_id": "start",
        "attempt": 0,
        "reason": "planning_started",
        "record_revision": 1,
        "fencing_token": event.payload["fencing_token"],
    }
    assert isinstance(event.payload["fencing_token"], int)
    before = original.model_dump(mode="python")
    after = persisted.model_dump(mode="python")
    assert {
        key for key in before if before[key] != after[key]
    } == {"current_state", "revision", "updated_at"}
    assert not _record_path(tmp_path, execution_id).with_name(
        "workflow-state.json"
    ).exists()
    assert issubclass(InvalidStateTransitionError, StateMachineError)
    assert issubclass(StateReplayError, StateTransitionIntegrityError)


def test_states_table_is_closed_and_illegal_self_terminal_transitions_preserve_bytes(
    tmp_path: Path,
) -> None:
    terminal_states = {
        ExecutionState.DRY_RUN_COMPLETED,
        ExecutionState.BLOCKED_ROLLBACK,
        ExecutionState.CANCELLED,
        ExecutionState.FAILED,
        ExecutionState.FAILED_BUDGET_EXCEEDED,
        ExecutionState.FAILED_RETRY_EXHAUSTED,
        ExecutionState.COMPENSATED,
    }
    assert set(VALID_STATE_TRANSITIONS) == set(ExecutionState)
    assert all(not VALID_STATE_TRANSITIONS[state] for state in terminal_states)
    assert VALID_STATE_TRANSITIONS[ExecutionState.COMPLETED] == {
        ExecutionState.ROLLBACK_IN_PROGRESS
    }
    assert VALID_STATE_TRANSITIONS[ExecutionState.ROLLBACK_IN_PROGRESS] == {
        ExecutionState.BLOCKED_ROLLBACK,
        ExecutionState.COMPENSATED,
    }
    assert {
        ExecutionState.PREPARING_WORKSPACE,
        ExecutionState.PAUSED_AWAITING_APPROVAL,
        ExecutionState.BLOCKED_PREREQUISITE,
        ExecutionState.BLOCKED_BASE_CHANGED,
        ExecutionState.BLOCKED_ROLLBACK,
        ExecutionState.CANCELLED,
        ExecutionState.DRY_RUN_COMPLETED,
        ExecutionState.ROLLBACK_IN_PROGRESS,
        ExecutionState.COMPENSATED,
    }.issubset(ExecutionState)

    execution_id = "exec-state-illegal"
    storage = AtomicFileStateStorage(tmp_path)
    storage.create_execution(_record(execution_id))
    machine = EventSourcedStateMachine(storage, execution_id, clock=_Clock())
    record_before = _record_path(tmp_path, execution_id).read_bytes()

    with pytest.raises(InvalidStateTransitionError):
        machine.transition_to(
            ExecutionState.INITIATED,
            node_id="start",
            attempt=0,
            reason="self_transition",
        )

    assert _record_path(tmp_path, execution_id).read_bytes() == record_before
    assert not _journal_path(tmp_path, execution_id).exists()
    machine.transition_to(
        ExecutionState.FAILED,
        node_id="start",
        attempt=0,
        reason="controlled_failure",
    )
    terminal_record = _record_path(tmp_path, execution_id).read_bytes()
    terminal_journal = _journal_path(tmp_path, execution_id).read_bytes()

    with pytest.raises(InvalidStateTransitionError):
        machine.transition_to(
            ExecutionState.EXECUTING,
            node_id="start",
            attempt=1,
            reason="illegal_restart",
        )

    assert _record_path(tmp_path, execution_id).read_bytes() == terminal_record
    assert _journal_path(tmp_path, execution_id).read_bytes() == terminal_journal


def test_paused_approval_can_resume_only_through_the_explicit_executing_edge(
    tmp_path: Path,
) -> None:
    assert VALID_STATE_TRANSITIONS[ExecutionState.PAUSED_AWAITING_APPROVAL] == {
        ExecutionState.EXECUTING,
        ExecutionState.PROMOTING,
        ExecutionState.CANCELLED,
        ExecutionState.FAILED,
    }
    execution_id = "exec-paused-approval-resume"
    storage = AtomicFileStateStorage(tmp_path)
    storage.create_execution(_record(execution_id))
    machine = EventSourcedStateMachine(storage, execution_id, clock=_Clock())
    machine.transition_to(
        ExecutionState.EXECUTING,
        node_id="approval",
        attempt=1,
        reason="execution_started",
    )
    machine.transition_to(
        ExecutionState.PAUSED_AWAITING_APPROVAL,
        node_id="approval",
        attempt=1,
        reason="approval_requested",
    )

    resumed = machine.transition_to(
        ExecutionState.EXECUTING,
        node_id="approval",
        attempt=1,
        reason="approval_granted",
    )

    assert resumed.current_state == ExecutionState.EXECUTING
    assert machine.recover() == resumed


def test_insufficient_context_can_fail_only_when_retry_budget_is_exhausted(
    tmp_path: Path,
) -> None:
    assert VALID_STATE_TRANSITIONS[ExecutionState.BLOCKED_INSUFFICIENT_CONTEXT] == {
        ExecutionState.CONTEXT_ASSEMBLING,
        ExecutionState.CANCELLED,
        ExecutionState.FAILED,
        ExecutionState.FAILED_RETRY_EXHAUSTED,
    }
    execution_id = "exec-context-retry-exhausted"
    storage = AtomicFileStateStorage(tmp_path)
    storage.create_execution(_record(execution_id))
    machine = EventSourcedStateMachine(storage, execution_id, clock=_Clock())
    machine.transition_to(
        ExecutionState.CONTEXT_ASSEMBLING,
        node_id="context",
        attempt=1,
        reason="context_assembly_started",
    )
    machine.transition_to(
        ExecutionState.BLOCKED_INSUFFICIENT_CONTEXT,
        node_id="context",
        attempt=1,
        reason="context_insufficient",
    )

    exhausted = machine.transition_to(
        ExecutionState.FAILED_RETRY_EXHAUSTED,
        node_id="context",
        attempt=1,
        reason="context_retry_exhausted",
    )

    assert exhausted.current_state == ExecutionState.FAILED_RETRY_EXHAUSTED


def test_replay_allows_node_revision_gaps_and_reproduces_snapshot(
    tmp_path: Path,
) -> None:
    execution_id = "exec-state-replay-gap"
    storage = AtomicFileStateStorage(tmp_path)
    storage.create_execution(_record(execution_id))
    machine = EventSourcedStateMachine(
        storage,
        execution_id,
        clock=_Clock(),
        event_id_factory=_EventIds(),
    )
    planning = machine.transition_to(
        ExecutionState.PLANNING,
        node_id="start",
        attempt=0,
        reason="planning_started",
    )
    node_document = planning.model_dump(mode="python")
    node_document.update(
        {
            "revision": 2,
            "current_node_id": "execute",
            "updated_at": planning.updated_at + timedelta(seconds=1),
        }
    )
    node_snapshot = ExecutionRecord.model_validate(node_document)
    storage.compare_and_set_execution(execution_id, 1, node_snapshot)
    resumed = EventSourcedStateMachine(
        storage,
        execution_id,
        clock=_Clock(_BASE_TIME + timedelta(seconds=10)),
        event_id_factory=lambda: "state-event-after-node-gap",
    )
    executing = resumed.transition_to(
        ExecutionState.EXECUTING,
        node_id="execute",
        attempt=1,
        reason="execution_started",
    )

    result = EventSourcedStateMachine(storage, execution_id).replay()
    assert isinstance(result, StateReplayResult)
    assert result.current_state == ExecutionState.EXECUTING
    assert result.snapshot_revision == 3
    assert result.transition_count == 2
    assert result.last_transition_revision == 3
    assert not result.has_pending_transition
    assert executing == storage.load_execution(execution_id)
    assert [
        event.payload["record_revision"]
        for event in storage.load_events(execution_id)
    ] == [1, 3]


def test_recovery_pending_crash_after_event_before_cas_is_idempotent(
    tmp_path: Path,
) -> None:
    execution_id = "exec-state-cas-failure"
    failing = _FailingCasStorage(tmp_path)
    original = _record(execution_id)
    failing.create_execution(original)
    machine = EventSourcedStateMachine(
        failing,
        execution_id,
        clock=_Clock(),
        event_id_factory=_EventIds(),
    )

    with pytest.raises(StateWriteError, match="controlled state CAS failure"):
        machine.transition_to(
            ExecutionState.EXECUTING,
            node_id="start",
            attempt=1,
            reason="graph_execution_started",
        )

    storage = AtomicFileStateStorage(tmp_path)
    events_before = storage.load_events(execution_id)
    snapshot_before = storage.load_execution(execution_id)
    resumed = EventSourcedStateMachine(storage, execution_id)
    replay = resumed.replay()
    assert replay.current_state == ExecutionState.EXECUTING
    assert replay.snapshot_revision == 0
    assert replay.has_pending_transition
    assert len(events_before) == 1

    recovered = resumed.recover()
    assert recovered.revision == 1
    assert recovered.current_state == ExecutionState.EXECUTING
    assert storage.load_events(execution_id) == events_before
    assert resumed.recover() == recovered
    assert storage.load_events(execution_id) == events_before
    before = snapshot_before.model_dump(mode="python")
    after = recovered.model_dump(mode="python")
    assert {
        key for key in before if before[key] != after[key]
    } == {"current_state", "revision", "updated_at"}


@pytest.mark.parametrize(
    "case",
    [
        "extra",
        "malformed_reason",
        "bool_attempt",
        "illegal",
        "mismatch",
        "gap",
        "zero_revision",
        "duplicate",
        "forged_fencing",
        "snapshot_mismatch",
        "legacy",
    ],
)
def test_invalid_illegal_extra_forged_mismatch_gap_duplicate_legacy_payloads_fail_closed(
    tmp_path: Path,
    case: str,
) -> None:
    execution_id = f"exec-state-{case}"
    storage = AtomicFileStateStorage(tmp_path)
    if case == "legacy":
        legacy = _record_path(tmp_path, execution_id).with_name(
            "workflow-state.json"
        )
        legacy.parent.mkdir(parents=True)
        legacy.write_text(
            json.dumps({"execution_id": execution_id, "state": "COMPLETED"}),
            encoding="utf-8",
        )
        previous = legacy.read_bytes()
        with pytest.raises(ExecutionNotFoundError):
            EventSourcedStateMachine(storage, execution_id)
        assert legacy.read_bytes() == previous
        return

    if case == "snapshot_mismatch":
        storage.create_execution(
            _record(execution_id, current_state=ExecutionState.PLANNING)
        )
    else:
        storage.create_execution(_record(execution_id))
        if case == "extra":
            _append_transition(storage, execution_id, event_id="event-extra", extra=True)
        elif case == "malformed_reason":
            _append_transition(
                storage,
                execution_id,
                event_id="event-reason",
                reason="free text",
            )
        elif case == "bool_attempt":
            _append_transition(
                storage,
                execution_id,
                event_id="event-attempt",
                attempt=True,
            )
        elif case == "illegal":
            _append_transition(
                storage,
                execution_id,
                event_id="event-illegal",
                to_state="COMPLETED",
            )
        elif case == "mismatch":
            _append_transition(
                storage,
                execution_id,
                event_id="event-mismatch",
                from_state="PLANNING",
            )
        elif case == "gap":
            _append_transition(
                storage,
                execution_id,
                event_id="event-gap",
                revision=2,
            )
        elif case == "zero_revision":
            _append_transition(
                storage,
                execution_id,
                event_id="event-zero-revision",
                revision=0,
            )
        elif case == "duplicate":
            _append_transition(
                storage,
                execution_id,
                event_id="event-duplicate-1",
            )
            _append_transition(
                storage,
                execution_id,
                event_id="event-duplicate-2",
                from_state="EXECUTING",
                to_state="COMPLETED",
                revision=1,
                fencing_token=2,
                timestamp=_BASE_TIME + timedelta(seconds=2),
            )
        elif case == "forged_fencing":
            _append_transition(
                storage,
                execution_id,
                event_id="event-forged-1",
                fencing_token=2,
            )
            _append_transition(
                storage,
                execution_id,
                event_id="event-forged-2",
                from_state="EXECUTING",
                to_state="COMPLETED",
                revision=2,
                fencing_token=1,
                timestamp=_BASE_TIME + timedelta(seconds=2),
            )

    record_before = _record_path(tmp_path, execution_id).read_bytes()
    journal = _journal_path(tmp_path, execution_id)
    journal_before = journal.read_bytes() if journal.exists() else None
    with pytest.raises(StateTransitionIntegrityError):
        EventSourcedStateMachine(storage, execution_id)

    assert _record_path(tmp_path, execution_id).read_bytes() == record_before
    assert (journal.read_bytes() if journal.exists() else None) == journal_before


def test_legacy_workflow_state_never_wins_or_is_migrated(tmp_path: Path) -> None:
    execution_id = "exec-state-legacy-conflict"
    storage = AtomicFileStateStorage(tmp_path)
    storage.create_execution(_record(execution_id))
    legacy = _record_path(tmp_path, execution_id).with_name("workflow-state.json")
    legacy.write_text(
        json.dumps({"execution_id": execution_id, "state": "COMPLETED"}),
        encoding="utf-8",
    )
    previous = legacy.read_bytes()

    replay = EventSourcedStateMachine(storage, execution_id).replay()

    assert replay.current_state == ExecutionState.INITIATED
    assert replay.transition_count == 0
    assert legacy.read_bytes() == previous
    assert storage.load_execution(execution_id).current_state == ExecutionState.INITIATED


def test_constructor_rejects_path_and_missing_execution_without_workflow_state(
    tmp_path: Path,
) -> None:
    with pytest.raises(TypeError, match="EventJournalStateStorageProvider"):
        EventSourcedStateMachine(tmp_path, "exec-path")
    assert not (tmp_path / ".harness").exists()

    storage = AtomicFileStateStorage(tmp_path)
    with pytest.raises(ExecutionNotFoundError):
        EventSourcedStateMachine(storage, "exec-missing")
    assert not (
        tmp_path
        / ".harness"
        / "state"
        / "executions"
        / "exec-missing"
        / "workflow-state.json"
    ).exists()


def test_replay_rejects_non_event_and_foreign_event_provider_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for suffix, returned, message in (
        ("non-event", (object(),), "non-ExecutionEvent"),
        (
            "foreign",
            (_transition_event("another-execution", event_id="foreign-event"),),
            "another execution",
        ),
    ):
        execution_id = f"exec-state-provider-{suffix}"
        storage = AtomicFileStateStorage(tmp_path / suffix)
        storage.create_execution(_record(execution_id))
        monkeypatch.setattr(storage, "load_events", lambda *args, values=returned, **kwargs: values)

        with pytest.raises(StateTransitionIntegrityError, match=message):
            EventSourcedStateMachine(storage, execution_id)


def test_replay_ignores_non_transition_events(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    execution_id = "exec-state-unrelated-event"
    storage = AtomicFileStateStorage(tmp_path)
    storage.create_execution(_record(execution_id))
    unrelated = _transition_event(execution_id, event_id="unrelated-event").model_copy(
        update={"event_type": "NODE_STARTED"}
    )
    monkeypatch.setattr(storage, "load_events", lambda *args, **kwargs: (unrelated,))

    replay = EventSourcedStateMachine(storage, execution_id).replay()

    assert replay.current_state is ExecutionState.INITIATED
    assert replay.transition_count == 0


@pytest.mark.parametrize(
    ("snapshot", "events", "message"),
    [
        (
            _record("exec-placeholder"),
            (
                _transition_event(
                    "exec-placeholder",
                    event_id="timestamp-1",
                    timestamp=_BASE_TIME + timedelta(seconds=2),
                ),
                _transition_event(
                    "exec-placeholder",
                    event_id="timestamp-2",
                    from_state="EXECUTING",
                    to_state="COMPLETED",
                    revision=2,
                    timestamp=_BASE_TIME + timedelta(seconds=1),
                ),
            ),
            "timestamps cannot regress",
        ),
        (
            _record("exec-placeholder"),
            (
                _transition_event("exec-placeholder", event_id="pending-1"),
                _transition_event(
                    "exec-placeholder",
                    event_id="pending-2",
                    from_state="EXECUTING",
                    to_state="COMPLETED",
                    revision=2,
                    timestamp=_BASE_TIME + timedelta(seconds=2),
                ),
            ),
            "more than one pending",
        ),
        (
            _record(
                "exec-placeholder",
                revision=1,
                current_state=ExecutionState.EXECUTING,
            ),
            (_transition_event("exec-placeholder", event_id="late-committed"),),
            "timestamp exceeds",
        ),
        (
            _record(
                "exec-placeholder",
                updated_at=_BASE_TIME + timedelta(seconds=2),
            ),
            (_transition_event("exec-placeholder", event_id="early-pending"),),
            "timestamp precedes",
        ),
    ],
)
def test_replay_rejects_temporal_and_pending_order_corruption(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: ExecutionRecord,
    events: tuple[ExecutionEvent, ...],
    message: str,
) -> None:
    execution_id = snapshot.execution_id.replace("placeholder", message.split()[0])
    snapshot = snapshot.model_copy(update={"execution_id": execution_id})
    events = tuple(event.model_copy(update={"execution_id": execution_id}) for event in events)
    storage = AtomicFileStateStorage(tmp_path)
    if snapshot.revision == 0:
        storage.create_execution(snapshot)
    else:
        storage.create_execution(_record(execution_id))
        lock = storage.acquire_execution_lock(
            execution_id,
            "snapshot-fixture",
            timeout_seconds=1.0,
        )
        try:
            storage.compare_and_set_execution(
                execution_id,
                0,
                snapshot,
                lock=lock,
            )
        finally:
            storage.release_execution_lock(lock)
    monkeypatch.setattr(storage, "load_events", lambda *args, **kwargs: events)

    with pytest.raises(StateTransitionIntegrityError, match=message):
        EventSourcedStateMachine(storage, execution_id)


def test_replay_guards_unreachable_pending_commit_order_if_parser_is_corrupt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _CommittedAfterPendingRevision(int):
        def __le__(self, other: object) -> bool:
            return other == 0

    execution_id = "exec-state-corrupt-parser-order"
    storage = AtomicFileStateStorage(tmp_path)
    storage.create_execution(_record(execution_id))
    machine = EventSourcedStateMachine(storage, execution_id)
    events = (
        _transition_event(execution_id, event_id="parser-order-1"),
        _transition_event(execution_id, event_id="parser-order-2"),
    )
    transitions = iter(
        (
            SimpleNamespace(
                event=events[0],
                from_state=ExecutionState.INITIATED,
                to_state=ExecutionState.EXECUTING,
                record_revision=1,
                fencing_token=1,
            ),
            SimpleNamespace(
                event=events[1],
                from_state=ExecutionState.EXECUTING,
                to_state=ExecutionState.COMPLETED,
                record_revision=_CommittedAfterPendingRevision(2),
                fencing_token=2,
            ),
        )
    )
    monkeypatch.setattr(storage, "load_events", lambda *args, **kwargs: events)
    monkeypatch.setattr(machine, "_parse_transition", lambda event: next(transitions))

    with pytest.raises(StateReplayError, match="committed transition follows"):
        machine.replay()


def test_replay_guards_pending_snapshot_mismatch_if_parser_is_corrupt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _ChangingFromState:
        def __init__(self) -> None:
            self.comparisons = 0

        def __ne__(self, other: object) -> bool:
            self.comparisons += 1
            return self.comparisons > 1

    execution_id = "exec-state-corrupt-parser-source"
    storage = AtomicFileStateStorage(tmp_path)
    storage.create_execution(_record(execution_id))
    machine = EventSourcedStateMachine(storage, execution_id)
    event = _transition_event(execution_id, event_id="parser-source")
    transition = SimpleNamespace(
        event=event,
        from_state=_ChangingFromState(),
        to_state=ExecutionState.EXECUTING,
        record_revision=1,
        fencing_token=1,
    )
    monkeypatch.setattr(storage, "load_events", lambda *args, **kwargs: (event,))
    monkeypatch.setattr(machine, "_parse_transition", lambda candidate: transition)

    with pytest.raises(StateReplayError, match="does not continue"):
        machine.replay()


def test_generating_evidence_completion_requires_handler(tmp_path: Path) -> None:
    execution_id = "exec-state-missing-evidence-handler"
    storage = AtomicFileStateStorage(tmp_path)
    storage.create_execution(_record(execution_id))
    machine = EventSourcedStateMachine(storage, execution_id, clock=_Clock())
    for state, reason in (
        (ExecutionState.EXECUTING, "execution_started"),
        (ExecutionState.VERIFYING, "verification_started"),
        (ExecutionState.GENERATING_EVIDENCE, "evidence_started"),
    ):
        machine.transition_to(state, node_id="evidence", attempt=1, reason=reason)

    with pytest.raises(StateTransitionIntegrityError, match="evidence handler"):
        machine.transition_to(
            ExecutionState.COMPLETED,
            node_id="evidence",
            attempt=1,
            reason="evidence_completed",
        )
