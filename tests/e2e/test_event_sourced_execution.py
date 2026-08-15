"""End-to-end F2.4 lifecycle and crash recovery over canonical files."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from ai_engineering_harness.contracts.events import ExecutionEvent
from ai_engineering_harness.contracts.execution import (
    ApprovalStatus,
    ExecutionRecord,
    ExecutionState,
)
from ai_engineering_harness.persistence import AtomicFileStateStorage
from ai_engineering_harness.runtime import EventSourcedStateMachine

_BASE_TIME = datetime(2020, 1, 1, tzinfo=UTC)
_ZERO_DIGEST = f"sha256:{'0' * 64}"


class _Clock:
    def __init__(self) -> None:
        self.value = _BASE_TIME

    def __call__(self) -> datetime:
        self.value += timedelta(seconds=1)
        return self.value


class _EventIds:
    def __init__(self) -> None:
        self.value = 0

    def __call__(self) -> str:
        self.value += 1
        return f"e2e-state-event-{self.value}"


def _record(execution_id: str) -> ExecutionRecord:
    return ExecutionRecord(
        record_schema_version="1.0",
        revision=0,
        execution_id=execution_id,
        workflow_name="event-sourced-lifecycle",
        artifact_digest=_ZERO_DIGEST,
        base_commit_sha="a" * 40,
        original_branch="test",
        worktree_path=None,
        current_node_id="start",
        current_state=ExecutionState.INITIATED,
        attempt_by_node={},
        created_at=_BASE_TIME,
        updated_at=_BASE_TIME,
        configuration_digest=_ZERO_DIGEST,
        approval_status=ApprovalStatus.NOT_REQUIRED,
        candidate_commit_sha=None,
        promotion_commit_sha=None,
        failure=None,
    )


def _execution_dir(root: Path, execution_id: str) -> Path:
    return root / ".harness" / "state" / "executions" / execution_id


def test_event_sourced_lifecycle_transitions_replay_terminal_state(
    tmp_path: Path,
) -> None:
    execution_id = "exec-e2e-state-lifecycle"
    storage = AtomicFileStateStorage(tmp_path)
    storage.create_execution(_record(execution_id))
    machine = EventSourcedStateMachine(
        storage,
        execution_id,
        clock=_Clock(),
        event_id_factory=_EventIds(),
    )
    sequence = (
        (ExecutionState.PREPARING_WORKSPACE, "workspace_preparation_started"),
        (ExecutionState.CONTEXT_ASSEMBLING, "context_assembly_started"),
        (ExecutionState.PLANNING, "planning_started"),
        (ExecutionState.EXECUTING, "execution_started"),
        (ExecutionState.VERIFYING, "verification_started"),
        (ExecutionState.COMPLETED, "execution_completed"),
    )
    for state, reason in sequence:
        machine.transition_to(
            state,
            node_id="start",
            attempt=0,
            reason=reason,
        )

    reopened = AtomicFileStateStorage(tmp_path)
    replay = EventSourcedStateMachine(reopened, execution_id).replay()
    record = reopened.load_execution(execution_id)
    events = reopened.load_events(execution_id)
    directory = _execution_dir(tmp_path, execution_id)

    assert replay.current_state == ExecutionState.COMPLETED
    assert replay.snapshot_revision == len(sequence)
    assert replay.transition_count == len(sequence)
    assert not replay.has_pending_transition
    assert record.current_state == ExecutionState.COMPLETED
    assert record.revision == len(sequence)
    assert [event.payload["to_state"] for event in events] == [
        state.value for state, _ in sequence
    ]
    assert all(event.previous_hash is not None for event in events)
    assert all(event.current_hash is not None for event in events)
    assert (directory / "execution.json").is_file()
    assert (directory / "event-journal.jsonl").is_file()
    assert not (directory / "workflow-state.json").exists()


def test_crash_recovery_pending_transition_is_idempotent_after_provider_restart(
    tmp_path: Path,
) -> None:
    execution_id = "exec-e2e-state-crash"
    storage = AtomicFileStateStorage(tmp_path)
    storage.create_execution(_record(execution_id))
    lock = storage.acquire_execution_lock(
        execution_id,
        "crashing-worker",
        timeout_seconds=0,
    )
    try:
        storage.append_event(
            execution_id,
            ExecutionEvent(
                event_id="e2e-pending-transition",
                execution_id=execution_id,
                sequence_number=0,
                event_type="STATE_TRANSITIONED",
                timestamp=_BASE_TIME + timedelta(seconds=1),
                graph_name="event-sourced-lifecycle",
                node_id="start",
                attempt=1,
                actor="event_sourced_test",
                payload={
                    "from_state": "INITIATED",
                    "to_state": "EXECUTING",
                    "node_id": "start",
                    "attempt": 1,
                    "reason": "graph_execution_started",
                    "record_revision": 1,
                    "fencing_token": lock.fencing_token,
                },
            ),
            lock=lock,
        )
    finally:
        storage.release_execution_lock(lock)

    reopened = AtomicFileStateStorage(tmp_path)
    machine = EventSourcedStateMachine(reopened, execution_id)
    replay = machine.replay()
    events_before = reopened.load_events(execution_id)
    assert replay.current_state == ExecutionState.EXECUTING
    assert replay.snapshot_revision == 0
    assert replay.has_pending_transition

    recovered = machine.recover()
    assert recovered.current_state == ExecutionState.EXECUTING
    assert recovered.revision == 1
    assert machine.recover() == recovered
    assert reopened.load_events(execution_id) == events_before
    assert not (
        _execution_dir(tmp_path, execution_id) / "workflow-state.json"
    ).exists()
