"""Event-sourced workflow state machine over the canonical F2.2 journal."""

from __future__ import annotations

import math
import re
import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from typing import Annotated, Final

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ai_engineering_harness.contracts.events import ExecutionEvent
from ai_engineering_harness.contracts.execution import (
    ExecutionId,
    ExecutionRecord,
    ExecutionState,
)
from ai_engineering_harness.persistence import (
    EventJournalStateStorageProvider,
    ExecutionLock,
)

ROLLBACK_REQUESTED = "ROLLBACK_REQUESTED"
ROLLBACK_CODE_COMPLETED = "ROLLBACK_CODE_COMPLETED"
ROLLBACK_EFFECTS_COMPLETED = "ROLLBACK_EFFECTS_COMPLETED"
EXECUTION_COMPENSATED = "EXECUTION_COMPENSATED"
STATE_TRANSITIONED: Final = "STATE_TRANSITIONED"

_DEFAULT_LOCK_TIMEOUT_SECONDS: Final = 30.0
_REASON_PATTERN: Final = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")
_TRANSITION_PAYLOAD_KEYS: Final = frozenset(
    {
        "from_state",
        "to_state",
        "node_id",
        "attempt",
        "reason",
        "record_revision",
        "fencing_token",
    }
)


class StateMachineError(Exception):
    """Base class for typed, fail-closed state-machine errors."""

    def __init__(self, message: str, *, execution_id: str | None = None) -> None:
        super().__init__(message)
        self.execution_id = execution_id


class InvalidStateTransitionError(StateMachineError, ValueError):
    """A requested edge is absent from the closed transition table."""


class StateTransitionIntegrityError(StateMachineError):
    """A state transition event is malformed, forged, or illegal."""


class StateReplayError(StateTransitionIntegrityError):
    """Snapshot and canonical state-transition history cannot be reconciled."""


class InterruptedExecutionError(StateMachineError):
    """Graph execution cannot continue without the F2.5 resume contract."""


_TRANSITIONS: dict[ExecutionState, frozenset[ExecutionState]] = {
    ExecutionState.INITIATED: frozenset(
        {
            ExecutionState.PREPARING_WORKSPACE,
            ExecutionState.CONTEXT_ASSEMBLING,
            ExecutionState.PLANNING,
            ExecutionState.GENERATING_PLAN,
            ExecutionState.EXECUTING,
            ExecutionState.BLOCKED_PREREQUISITE,
            ExecutionState.CANCELLED,
            ExecutionState.FAILED,
        }
    ),
    ExecutionState.PREPARING_WORKSPACE: frozenset(
        {
            ExecutionState.CONTEXT_ASSEMBLING,
            ExecutionState.BLOCKED_PREREQUISITE,
            ExecutionState.CANCELLED,
            ExecutionState.FAILED,
        }
    ),
    ExecutionState.CONTEXT_ASSEMBLING: frozenset(
        {
            ExecutionState.BLOCKED_INSUFFICIENT_CONTEXT,
            ExecutionState.PLANNING,
            ExecutionState.GENERATING_PLAN,
            ExecutionState.BLOCKED_PREREQUISITE,
            ExecutionState.CANCELLED,
            ExecutionState.FAILED,
        }
    ),
    ExecutionState.BLOCKED_INSUFFICIENT_CONTEXT: frozenset(
        {
            ExecutionState.CONTEXT_ASSEMBLING,
            ExecutionState.CANCELLED,
            ExecutionState.FAILED,
            ExecutionState.FAILED_RETRY_EXHAUSTED,
        }
    ),
    ExecutionState.BLOCKED_PREREQUISITE: frozenset(
        {
            ExecutionState.PREPARING_WORKSPACE,
            ExecutionState.CANCELLED,
            ExecutionState.FAILED,
        }
    ),
    ExecutionState.BLOCKED_BASE_CHANGED: frozenset(
        {ExecutionState.CANCELLED, ExecutionState.FAILED}
    ),
    ExecutionState.PLANNING: frozenset(
        {
            ExecutionState.GENERATING_PLAN,
            ExecutionState.EXECUTING,
            ExecutionState.BLOCKED_PREREQUISITE,
            ExecutionState.CANCELLED,
            ExecutionState.FAILED,
        }
    ),
    ExecutionState.GENERATING_PLAN: frozenset(
        {
            ExecutionState.EXECUTING,
            ExecutionState.BLOCKED_PREREQUISITE,
            ExecutionState.CANCELLED,
            ExecutionState.FAILED,
        }
    ),
    ExecutionState.EXECUTING: frozenset(
        {
            ExecutionState.VERIFYING,
            ExecutionState.PAUSED_AWAITING_APPROVAL,
            ExecutionState.BLOCKED_PREREQUISITE,
            ExecutionState.COMPLETED,
            ExecutionState.CANCELLED,
            ExecutionState.FAILED,
            ExecutionState.FAILED_RETRY_EXHAUSTED,
        }
    ),
    ExecutionState.VERIFYING: frozenset(
        {
            ExecutionState.EXECUTING,
            ExecutionState.PAUSED_AWAITING_APPROVAL,
            ExecutionState.PROMOTING,
            ExecutionState.DRY_RUN_COMPLETED,
            ExecutionState.COMPLETED,
            ExecutionState.BLOCKED_PREREQUISITE,
            ExecutionState.CANCELLED,
            ExecutionState.FAILED,
            ExecutionState.FAILED_RETRY_EXHAUSTED,
        }
    ),
    ExecutionState.AWAITING_APPROVAL: frozenset(
        {
            ExecutionState.PAUSED_AWAITING_APPROVAL,
            ExecutionState.PROMOTING,
            ExecutionState.CANCELLED,
            ExecutionState.FAILED,
        }
    ),
    ExecutionState.PAUSED_AWAITING_APPROVAL: frozenset(
        {
            ExecutionState.EXECUTING,
            ExecutionState.PROMOTING,
            ExecutionState.CANCELLED,
            ExecutionState.FAILED,
        }
    ),
    ExecutionState.PROMOTING: frozenset(
        {
            ExecutionState.REINDEXING,
            ExecutionState.BLOCKED_BASE_CHANGED,
            ExecutionState.ROLLBACK_IN_PROGRESS,
            ExecutionState.COMPLETED,
            ExecutionState.FAILED,
        }
    ),
    ExecutionState.REINDEXING: frozenset(
        {
            ExecutionState.KNOWLEDGE_SYNC,
            ExecutionState.GENERATING_EVIDENCE,
            ExecutionState.COMPLETED,
            ExecutionState.FAILED,
        }
    ),
    ExecutionState.KNOWLEDGE_SYNC: frozenset(
        {
            ExecutionState.GENERATING_EVIDENCE,
            ExecutionState.COMPLETED,
            ExecutionState.FAILED,
        }
    ),
    ExecutionState.GENERATING_EVIDENCE: frozenset(
        {ExecutionState.COMPLETED, ExecutionState.FAILED}
    ),
    ExecutionState.ROLLBACK_IN_PROGRESS: frozenset(
        {ExecutionState.COMPENSATED, ExecutionState.FAILED}
    ),
    ExecutionState.DRY_RUN_COMPLETED: frozenset(),
    ExecutionState.COMPLETED: frozenset(),
    ExecutionState.CANCELLED: frozenset(),
    ExecutionState.FAILED: frozenset(),
    ExecutionState.FAILED_RETRY_EXHAUSTED: frozenset(),
    ExecutionState.COMPENSATED: frozenset(),
}

VALID_STATE_TRANSITIONS: Mapping[ExecutionState, frozenset[ExecutionState]] = (
    MappingProxyType(_TRANSITIONS)
)
VALID_TRANSITIONS = VALID_STATE_TRANSITIONS


class StateReplayResult(BaseModel):
    """Strict immutable summary of canonical state replay."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    execution_id: ExecutionId
    current_state: ExecutionState
    snapshot_revision: int = Field(ge=0)
    transition_count: int = Field(ge=0)
    last_transition_revision: Annotated[int, Field(ge=0)] | None
    has_pending_transition: bool


@dataclass(frozen=True, slots=True)
class _Transition:
    event: ExecutionEvent
    from_state: ExecutionState
    to_state: ExecutionState
    record_revision: int
    fencing_token: int


@dataclass(frozen=True, slots=True)
class _ReplayAnalysis:
    result: StateReplayResult
    snapshot: ExecutionRecord
    pending: _Transition | None


class EventSourcedStateMachine:
    """Validate, replay, recover, and append durable state transitions."""

    def __init__(
        self,
        storage: EventJournalStateStorageProvider,
        execution_id: str,
        *,
        lock_timeout_seconds: float = _DEFAULT_LOCK_TIMEOUT_SECONDS,
        clock: Callable[[], datetime] | None = None,
        event_id_factory: Callable[[], str] | None = None,
        owner_id_factory: Callable[[], str] | None = None,
        lock: ExecutionLock | None = None,
    ) -> None:
        if not isinstance(storage, EventJournalStateStorageProvider):
            raise TypeError(
                "storage must implement EventJournalStateStorageProvider"
            )
        if (
            isinstance(lock_timeout_seconds, bool)
            or not isinstance(lock_timeout_seconds, (int, float))
            or not math.isfinite(lock_timeout_seconds)
            or lock_timeout_seconds < 0
        ):
            raise ValueError("lock_timeout_seconds must be finite and non-negative")
        self._storage = storage
        self.execution_id = execution_id
        self._lock_timeout_seconds = float(lock_timeout_seconds)
        self._clock = clock or (lambda: datetime.now(UTC))
        self._event_id_factory = event_id_factory or (
            lambda: f"state-event-{uuid.uuid4().hex}"
        )
        self._owner_id_factory = owner_id_factory or (
            lambda: f"state-machine-{uuid.uuid4().hex}"
        )
        self._current_state = ExecutionState.INITIATED
        result = self.replay(lock=lock)
        self._current_state = result.current_state

    @property
    def current_state(self) -> ExecutionState:
        """Return the state observed by the latest successful FSM operation."""
        return self._current_state

    def replay(self, *, lock: ExecutionLock | None = None) -> StateReplayResult:
        """Validate and reconstruct state without mutating the snapshot."""
        with self._execution_guard(lock) as active_lock:
            analysis = self._analyze_locked(active_lock)
        self._current_state = analysis.result.current_state
        return analysis.result

    def recover(self, *, lock: ExecutionLock | None = None) -> ExecutionRecord:
        """Apply exactly one pending transition event without appending another."""
        with self._execution_guard(lock) as active_lock:
            recovered = self._recover_locked(active_lock)
        self._current_state = recovered.current_state
        return recovered

    def transition_to(
        self,
        to_state: ExecutionState,
        *,
        node_id: str,
        attempt: int,
        reason: str,
        lock: ExecutionLock | None = None,
    ) -> ExecutionRecord:
        """Append one legal transition and publish its snapshot with one CAS."""
        self._validate_transition_input(to_state, node_id, attempt, reason)
        with self._execution_guard(lock) as active_lock:
            record = self._recover_locked(active_lock)
            allowed = VALID_STATE_TRANSITIONS[record.current_state]
            if to_state not in allowed:
                raise InvalidStateTransitionError(
                    (
                        "invalid state transition: "
                        f"{record.current_state.value} -> {to_state.value}"
                    ),
                    execution_id=self.execution_id,
                )
            timestamp = self._next_timestamp(record.updated_at)
            target_revision = record.revision + 1
            payload: dict[str, object] = {
                "from_state": record.current_state.value,
                "to_state": to_state.value,
                "node_id": node_id,
                "attempt": attempt,
                "reason": reason,
                "record_revision": target_revision,
                "fencing_token": active_lock.fencing_token,
            }
            try:
                event = ExecutionEvent(
                    event_id=self._event_id_factory(),
                    execution_id=self.execution_id,
                    event_type=STATE_TRANSITIONED,
                    timestamp=timestamp,
                    payload=payload,
                )
            except (TypeError, ValueError, ValidationError) as exc:
                raise StateTransitionIntegrityError(
                    "cannot construct a canonical state transition event",
                    execution_id=self.execution_id,
                ) from exc
            self._storage.append_event(
                self.execution_id,
                event,
                lock=active_lock,
            )
            replacement = self._state_replacement(
                record,
                to_state=to_state,
                revision=target_revision,
                updated_at=timestamp,
            )
            persisted = self._storage.compare_and_set_execution(
                self.execution_id,
                record.revision,
                replacement,
                lock=active_lock,
            )
        self._current_state = persisted.current_state
        return persisted

    @contextmanager
    def _execution_guard(
        self,
        lock: ExecutionLock | None,
    ) -> Iterator[ExecutionLock]:
        if lock is not None:
            yield lock
            return
        internal = self._storage.acquire_execution_lock(
            self.execution_id,
            self._owner_id_factory(),
            timeout_seconds=self._lock_timeout_seconds,
        )
        try:
            yield internal
        finally:
            self._storage.release_execution_lock(internal)

    def _analyze_locked(self, lock: ExecutionLock) -> _ReplayAnalysis:
        snapshot = self._storage.load_execution(self.execution_id, lock=lock)
        events = self._storage.load_events(self.execution_id, lock=lock)
        current_state = ExecutionState.INITIATED
        committed_state = ExecutionState.INITIATED
        last_revision: int | None = None
        last_fencing_token = 0
        last_timestamp: datetime | None = None
        pending: _Transition | None = None
        transition_count = 0

        for event in events:
            if not isinstance(event, ExecutionEvent):
                raise StateTransitionIntegrityError(
                    "journal reader returned a non-ExecutionEvent value",
                    execution_id=self.execution_id,
                )
            if event.execution_id != self.execution_id:
                raise StateTransitionIntegrityError(
                    "journal reader returned an event for another execution",
                    execution_id=self.execution_id,
                )
            if event.event_type != STATE_TRANSITIONED:
                continue
            transition = self._parse_transition(event)
            transition_count += 1
            if transition.record_revision == 0:
                raise StateReplayError(
                    "state transition revision must follow a snapshot revision",
                    execution_id=self.execution_id,
                )
            if (
                last_revision is not None
                and transition.record_revision <= last_revision
            ):
                raise StateTransitionIntegrityError(
                    "state transition revisions must increase strictly",
                    execution_id=self.execution_id,
                )
            if transition.fencing_token < last_fencing_token:
                raise StateTransitionIntegrityError(
                    "state transition fencing tokens cannot regress",
                    execution_id=self.execution_id,
                )
            if last_timestamp is not None and event.timestamp < last_timestamp:
                raise StateTransitionIntegrityError(
                    "state transition timestamps cannot regress",
                    execution_id=self.execution_id,
                )
            if transition.from_state != current_state:
                raise StateTransitionIntegrityError(
                    "state transition history has a broken state chain",
                    execution_id=self.execution_id,
                )
            if transition.to_state not in VALID_STATE_TRANSITIONS[current_state]:
                raise StateTransitionIntegrityError(
                    "journal contains an illegal state transition",
                    execution_id=self.execution_id,
                )

            if transition.record_revision <= snapshot.revision:
                if pending is not None:
                    raise StateReplayError(
                        "committed transition follows a pending transition",
                        execution_id=self.execution_id,
                    )
                if event.timestamp > snapshot.updated_at:
                    raise StateReplayError(
                        "committed transition timestamp exceeds the snapshot",
                        execution_id=self.execution_id,
                    )
                committed_state = transition.to_state
            else:
                if pending is not None:
                    raise StateReplayError(
                        "more than one pending state transition exists",
                        execution_id=self.execution_id,
                    )
                if transition.record_revision != snapshot.revision + 1:
                    raise StateReplayError(
                        "pending state transition is not the next snapshot revision",
                        execution_id=self.execution_id,
                    )
                if event.timestamp < snapshot.updated_at:
                    raise StateReplayError(
                        "pending transition timestamp precedes the snapshot",
                        execution_id=self.execution_id,
                    )
                pending = transition

            current_state = transition.to_state
            last_revision = transition.record_revision
            last_fencing_token = transition.fencing_token
            last_timestamp = event.timestamp

        if committed_state != snapshot.current_state:
            raise StateReplayError(
                "snapshot state does not match committed transition history",
                execution_id=self.execution_id,
            )
        if pending is not None and pending.from_state != snapshot.current_state:
            raise StateReplayError(
                "pending transition does not continue from the snapshot state",
                execution_id=self.execution_id,
            )

        result = StateReplayResult(
            execution_id=self.execution_id,
            current_state=current_state,
            snapshot_revision=snapshot.revision,
            transition_count=transition_count,
            last_transition_revision=last_revision,
            has_pending_transition=pending is not None,
        )
        return _ReplayAnalysis(result=result, snapshot=snapshot, pending=pending)

    def _recover_locked(self, lock: ExecutionLock) -> ExecutionRecord:
        analysis = self._analyze_locked(lock)
        if analysis.pending is None:
            return analysis.snapshot
        pending = analysis.pending
        replacement = self._state_replacement(
            analysis.snapshot,
            to_state=pending.to_state,
            revision=pending.record_revision,
            updated_at=pending.event.timestamp,
        )
        return self._storage.compare_and_set_execution(
            self.execution_id,
            analysis.snapshot.revision,
            replacement,
            lock=lock,
        )

    def _parse_transition(self, event: ExecutionEvent) -> _Transition:
        payload = event.payload
        if set(payload) != _TRANSITION_PAYLOAD_KEYS:
            raise StateTransitionIntegrityError(
                "state transition payload has missing or extra fields",
                execution_id=self.execution_id,
            )
        from_state = self._parse_state(payload["from_state"], field="from_state")
        to_state = self._parse_state(payload["to_state"], field="to_state")
        self._require_non_empty_string(payload["node_id"], field="node_id")
        self._require_reason(payload["reason"])
        self._require_integer(payload["attempt"], field="attempt", minimum=0)
        revision = self._require_integer(
            payload["record_revision"],
            field="record_revision",
            minimum=0,
        )
        fencing_token = self._require_integer(
            payload["fencing_token"],
            field="fencing_token",
            minimum=1,
        )
        return _Transition(
            event=event,
            from_state=from_state,
            to_state=to_state,
            record_revision=revision,
            fencing_token=fencing_token,
        )

    def _next_timestamp(self, minimum: datetime) -> datetime:
        observed = self._clock()
        if (
            not isinstance(observed, datetime)
            or observed.tzinfo is None
            or observed.utcoffset() is None
            or observed.utcoffset() != timedelta(0)
            or observed < minimum
        ):
            raise StateTransitionIntegrityError(
                "state-machine clock must be UTC and cannot regress",
                execution_id=self.execution_id,
            )
        return observed.astimezone(UTC)

    def _validate_transition_input(
        self,
        to_state: ExecutionState,
        node_id: str,
        attempt: int,
        reason: str,
    ) -> None:
        if not isinstance(to_state, ExecutionState):
            raise InvalidStateTransitionError(
                "to_state must be an ExecutionState",
                execution_id=self.execution_id,
            )
        self._require_non_empty_string(node_id, field="node_id")
        self._require_integer(attempt, field="attempt", minimum=0)
        self._require_reason(reason)

    def _parse_state(self, value: object, *, field: str) -> ExecutionState:
        if type(value) is not str:
            raise StateTransitionIntegrityError(
                f"{field} must be an exact state string",
                execution_id=self.execution_id,
            )
        try:
            return ExecutionState(value)
        except ValueError as exc:
            raise StateTransitionIntegrityError(
                f"{field} contains an unknown state",
                execution_id=self.execution_id,
            ) from exc

    def _require_non_empty_string(self, value: object, *, field: str) -> str:
        if type(value) is not str or not value.strip() or value != value.strip():
            raise StateTransitionIntegrityError(
                f"{field} must be a non-empty trimmed string",
                execution_id=self.execution_id,
            )
        return value

    def _require_reason(self, value: object) -> str:
        reason = self._require_non_empty_string(value, field="reason")
        if _REASON_PATTERN.fullmatch(reason) is None:
            raise StateTransitionIntegrityError(
                "reason must be a snake_case code",
                execution_id=self.execution_id,
            )
        return reason

    def _require_integer(
        self,
        value: object,
        *,
        field: str,
        minimum: int,
    ) -> int:
        if type(value) is not int or value < minimum:
            raise StateTransitionIntegrityError(
                f"{field} must be an integer greater than or equal to {minimum}",
                execution_id=self.execution_id,
            )
        return value

    @staticmethod
    def _state_replacement(
        record: ExecutionRecord,
        *,
        to_state: ExecutionState,
        revision: int,
        updated_at: datetime,
    ) -> ExecutionRecord:
        document = record.model_dump(mode="python")
        document.update(
            {
                "current_state": to_state,
                "revision": revision,
                "updated_at": updated_at,
            }
        )
        return ExecutionRecord.model_validate(document)


WorkflowState = ExecutionState
WorkflowStateMachine = EventSourcedStateMachine


__all__ = [
    "EXECUTION_COMPENSATED",
    "ROLLBACK_CODE_COMPLETED",
    "ROLLBACK_EFFECTS_COMPLETED",
    "ROLLBACK_REQUESTED",
    "STATE_TRANSITIONED",
    "VALID_STATE_TRANSITIONS",
    "VALID_TRANSITIONS",
    "EventSourcedStateMachine",
    "InterruptedExecutionError",
    "InvalidStateTransitionError",
    "StateMachineError",
    "StateReplayError",
    "StateReplayResult",
    "StateTransitionIntegrityError",
    "WorkflowState",
    "WorkflowStateMachine",
]
