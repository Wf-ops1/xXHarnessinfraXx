"""Canonical traversal of compiled graphs over durable execution state."""

from __future__ import annotations

import hashlib
import math
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol, runtime_checkable

from jsonschema import SchemaError as JsonSchemaError
from jsonschema import ValidationError as JsonValidationError
from jsonschema import validate as validate_json_schema
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from ai_engineering_harness.contracts import (
    AgentNodeSpec,
    CompiledGraphArtifact,
    HumanApprovalNodeSpec,
    NodeSpec,
    ResolvedContractSpec,
    TerminalStateSpec,
)
from ai_engineering_harness.contracts.events import ExecutionEvent
from ai_engineering_harness.contracts.execution import (
    ExecutionId,
    ExecutionRecord,
    ExecutionState,
)
from ai_engineering_harness.governance import ToolPolicyDecision
from ai_engineering_harness.persistence import (
    EventJournalStateStorageProvider,
    ExecutionLock,
    ResumeStateStorageProvider,
)
from ai_engineering_harness.security.redaction import Redactor

from .node_executors import (
    FailedToolCall,
    ModelCallMetadata,
    NodeBackendError,
    NodeExecutionContext,
    NodeExecutionFailure,
    NodeExecutionResult,
    NodeExecutor,
    NodeExecutorError,
    NodeExecutorRegistry,
    NodeExecutorResultError,
    RetryContext,
    RetryEvidence,
    ToolCallIntent,
    ToolEffectAmbiguousError,
    ToolEffectDurabilityError,
    ToolEffectIntegrityError,
    ToolExecutionRecord,
    _copy_json_object,
)
from .state_machine import (
    EventSourcedStateMachine,
    InterruptedExecutionError,
    StateReplayError,
)

VERIFICATION_REPAIR_SCHEDULED: Literal["VERIFICATION_REPAIR_SCHEDULED"] = (
    "VERIFICATION_REPAIR_SCHEDULED"
)


class GraphExecutionError(Exception):
    """Base class for fail-closed graph traversal errors."""

    def __init__(
        self,
        message: str,
        *,
        execution_id: str | None = None,
        node_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.execution_id = execution_id
        self.node_id = node_id


class ArtifactExecutionMismatchError(GraphExecutionError):
    """The artifact is invalid or does not match immutable execution identity."""


class UnknownCurrentNodeError(GraphExecutionError):
    """The persisted current node is absent from the compiled graph."""


class NodeContractNotFoundError(GraphExecutionError):
    """An agent contract reference is absent or ambiguous in the artifact."""


class NodeInputValidationError(GraphExecutionError):
    """A node input is not a JSON object or violates its declared contract."""


class NodeOutputValidationError(GraphExecutionError):
    """A successful node output violates its declared contract."""


class GraphCycleExecutionError(GraphExecutionError):
    """Traversal attempted a cycle without a valid retry episode."""


class RetryContextIntegrityError(GraphExecutionError):
    """Retry evidence or its durable digest chain is missing or divergent."""


class RetryExhaustedError(GraphExecutionError):
    """A node reached its declared maximum number of invocations."""

    classification = "retry_exhausted"


class GraphClockError(GraphExecutionError):
    """The injected clock is invalid or regresses durable execution time."""


class GraphEventConstructionError(GraphExecutionError):
    """A canonical node event could not be constructed."""


class InterruptedNodeExecutionError(GraphExecutionError):
    """A started node has no durable outcome and cannot be replayed in F2.5."""

    classification = "requires_intervention"


@dataclass(slots=True)
class _DurableToolEffectRecorder:
    """Bind one backend's tool effects to the active graph journal and lock."""

    owner: GraphExecutor
    execution_id: str
    node: NodeSpec
    attempt: int
    lock: ExecutionLock
    current_timestamp: datetime
    open_intent: ToolCallIntent | None = None
    records: list[ToolExecutionRecord] = field(default_factory=list)

    def record_call(self, intent: ToolCallIntent) -> None:
        if self.open_intent is not None:
            raise ToolEffectIntegrityError(
                "a prior tool call has no durable outcome"
            )
        if intent.step != len(self.records) + 1:
            raise ToolEffectIntegrityError(
                "tool write-ahead steps must be contiguous and start at one"
            )
        called_at = self.owner._next_timestamp(
            self.current_timestamp,
            execution_id=self.execution_id,
            node_id=self.node.id,
        )
        try:
            self.owner._append_tool_event(
                self.execution_id,
                self.node,
                self.attempt,
                self.lock,
                called_at,
                "TOOL_CALLED",
                intent,
            )
        except Exception as exc:
            raise ToolEffectDurabilityError(
                "tool call write-ahead could not be persisted"
            ) from exc
        self.current_timestamp = called_at
        self.open_intent = intent

    def record_outcome(self, record: ToolExecutionRecord) -> None:
        if self.open_intent is None or not _record_matches_intent(
            record,
            self.open_intent,
        ):
            raise ToolEffectIntegrityError(
                "tool outcome does not match the open durable call"
            )
        outcome_at = self.owner._next_timestamp(
            self.current_timestamp,
            execution_id=self.execution_id,
            node_id=self.node.id,
        )
        outcome_type: Literal["TOOL_COMPLETED", "TOOL_FAILED"] = (
            "TOOL_COMPLETED" if record.succeeded else "TOOL_FAILED"
        )
        try:
            self.owner._append_tool_event(
                self.execution_id,
                self.node,
                self.attempt,
                self.lock,
                outcome_at,
                outcome_type,
                record,
            )
        except Exception as exc:
            raise ToolEffectAmbiguousError(
                "tool effect completed but its durable outcome is ambiguous"
            ) from exc
        self.current_timestamp = outcome_at
        self.open_intent = None
        self.records.append(record)

    def finish(self, expected: tuple[ToolExecutionRecord, ...]) -> datetime:
        if self.open_intent is not None:
            raise ToolEffectAmbiguousError(
                "tool call remains open after backend execution"
            )
        if tuple(self.records) != expected:
            raise ToolEffectIntegrityError(
                "backend tool evidence diverges from the durable journal"
            )
        return self.current_timestamp


def _record_matches_intent(
    record: ToolExecutionRecord,
    intent: ToolCallIntent,
) -> bool:
    return (
        record.step == intent.step
        and record.call_id == intent.call_id
        and record.tool_name == intent.tool_name
        and record.arguments_digest == intent.arguments_digest
        and record.policy_decision_digest == intent.policy_decision.digest()
    )


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")


class GraphExecutionResult(_StrictFrozenModel):
    """Final terminal reached by one locked graph traversal call."""

    execution_id: ExecutionId
    terminal_id: str = Field(min_length=1)
    outcome: Literal["success", "failure"]
    output: dict[str, object]
    executed_node_ids: tuple[str, ...]
    final_revision: int = Field(ge=0)
    fencing_token: int = Field(gt=0)
    failure: NodeExecutionFailure | None = None

    @field_validator("output", mode="before")
    @classmethod
    def detach_output(cls, value: object) -> dict[str, object]:
        return _copy_json_object(value, path="output")

    @field_validator("executed_node_ids", mode="before")
    @classmethod
    def freeze_node_ids(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def require_matching_failure(self) -> GraphExecutionResult:
        if self.outcome == "success" and self.failure is not None:
            raise ValueError("a successful graph result cannot contain failure details")
        if self.outcome == "failure" and self.failure is None:
            raise ValueError("a failed graph result requires failure details")
        return self


class GraphExecutionPausedResult(_StrictFrozenModel):
    """A graph stopped durably at an explicit human-approval node."""

    execution_id: ExecutionId
    node_id: str = Field(min_length=1)
    approval_subject_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    executed_node_ids: tuple[str, ...]
    final_revision: int = Field(ge=0)
    fencing_token: int = Field(gt=0)

    @field_validator("executed_node_ids", mode="before")
    @classmethod
    def freeze_node_ids(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value


class VerificationRepairRequest(_StrictFrozenModel):
    """Lifecycle-owned retry decision consumed atomically by graph traversal."""

    source_verification_attempt: int = Field(ge=1)
    source_suite_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    source_verified_commit_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    repair_attempt: int = Field(ge=1)
    retry_policy_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    origin_node_id: str = Field(min_length=1)
    target_node_id: str = Field(min_length=1)
    deadline_at: datetime
    retry_context: RetryContext

    @model_validator(mode="after")
    def require_bound_context(self) -> VerificationRepairRequest:
        budget = self.retry_context.remaining_budget
        if self.retry_context.origin_node_id != self.origin_node_id:
            raise ValueError("retry context origin must match the verification node")
        if self.retry_context.failed_commit_sha != self.source_verified_commit_sha:
            raise ValueError("retry context commit must match the failed suite")
        if budget.remaining_time_seconds is None or budget.remaining_time_seconds <= 0:
            raise ValueError("verification retry requires positive remaining time")
        if self.deadline_at.tzinfo is None or self.deadline_at.utcoffset() is None:
            raise ValueError("verification retry deadline must be timezone-aware")
        return self


@runtime_checkable
class ApprovalPauseHandler(Protocol):
    """Lifecycle boundary used only for explicit human-approval nodes."""

    def pause_for_approval(
        self,
        *,
        artifact: CompiledGraphArtifact,
        record: ExecutionRecord,
        node: HumanApprovalNodeSpec,
        input_digest: str,
        executed_node_ids: tuple[str, ...],
        lock: ExecutionLock,
    ) -> GraphExecutionPausedResult:
        """Persist one approval request and paused execution snapshot."""

    def is_approval_granted(
        self,
        *,
        record: ExecutionRecord,
        node: HumanApprovalNodeSpec,
        input_digest: str,
        lock: ExecutionLock,
    ) -> bool:
        """Return true only for a grant bound to this exact approval subject."""


class GraphExecutor:
    """Execute only nodes and edges declared by a canonical compiled artifact."""

    def __init__(
        self,
        storage: EventJournalStateStorageProvider,
        executors: NodeExecutorRegistry,
        *,
        resume_enabled: bool = False,
        approval_handler: ApprovalPauseHandler | None = None,
        lock_timeout_seconds: float = 30.0,
        clock: Callable[[], datetime] | None = None,
        event_id_factory: Callable[[], str] | None = None,
        owner_id_factory: Callable[[], str] | None = None,
    ) -> None:
        if not isinstance(storage, EventJournalStateStorageProvider):
            raise TypeError(
                "storage must implement EventJournalStateStorageProvider"
            )
        if not isinstance(executors, NodeExecutorRegistry):
            raise TypeError("executors must be a NodeExecutorRegistry")
        if type(resume_enabled) is not bool:
            raise TypeError("resume_enabled must be a bool")
        if resume_enabled and not isinstance(storage, ResumeStateStorageProvider):
            raise TypeError(
                "resume-enabled execution requires ResumeStateStorageProvider"
            )
        if approval_handler is not None and not isinstance(
            approval_handler,
            ApprovalPauseHandler,
        ):
            raise TypeError("approval_handler must implement ApprovalPauseHandler")
        if (
            isinstance(lock_timeout_seconds, bool)
            or not isinstance(lock_timeout_seconds, (int, float))
            or not math.isfinite(lock_timeout_seconds)
            or lock_timeout_seconds < 0
        ):
            raise ValueError("lock_timeout_seconds must be finite and non-negative")
        self._storage = storage
        self._executors = executors
        self._resume_enabled = resume_enabled
        self._approval_handler = approval_handler
        self._lock_timeout_seconds = float(lock_timeout_seconds)
        self._clock = clock or (lambda: datetime.now(UTC))
        self._event_id_factory = event_id_factory or (
            lambda: f"event-{uuid.uuid4().hex}"
        )
        self._owner_id_factory = owner_id_factory or (
            lambda: f"graph-executor-{uuid.uuid4().hex}"
        )

    def preflight(
        self,
        artifact: CompiledGraphArtifact,
        initial_input: dict[str, object],
        *,
        execution_id: str = "execution-preflight",
    ) -> None:
        """Validate the entrypoint, initial payload, and executor without mutation."""
        detached = self._detach_artifact(artifact, execution_id=execution_id)
        try:
            payload = _copy_json_object(initial_input, path="initial_input")
        except (TypeError, ValueError) as exc:
            raise NodeInputValidationError(
                "initial input must be a finite JSON object",
                execution_id=execution_id,
            ) from exc
        nodes = {node.id: node for node in detached.graph.nodes}
        entrypoint = detached.graph.graph.entrypoint
        node = nodes.get(entrypoint)
        if node is None:
            raise UnknownCurrentNodeError(
                "graph entrypoint is not an executable node",
                execution_id=execution_id,
                node_id=entrypoint,
            )
        self._validate_node_input(detached, node, payload, execution_id)
        if not (
            isinstance(node, HumanApprovalNodeSpec)
            and self._approval_handler is not None
        ):
            self._executors.select(node).ensure_available()

    def execute(
        self,
        artifact: CompiledGraphArtifact,
        execution_id: str,
        initial_input: dict[str, object],
        *,
        defer_completion: bool = False,
    ) -> GraphExecutionResult | GraphExecutionPausedResult:
        """Traverse from the persisted current node under one execution lock."""
        if type(defer_completion) is not bool:
            raise TypeError("defer_completion must be a bool")
        detached_artifact = self._detach_artifact(artifact, execution_id=execution_id)
        try:
            current_payload = _copy_json_object(initial_input, path="initial_input")
        except (TypeError, ValueError) as exc:
            raise NodeInputValidationError(
                "initial input must be a finite JSON object",
                execution_id=execution_id,
            ) from exc

        lock = self._storage.acquire_execution_lock(
            execution_id,
            self._owner_id_factory(),
            timeout_seconds=self._lock_timeout_seconds,
        )
        try:
            return self._execute_locked(
                detached_artifact,
                execution_id,
                current_payload,
                lock,
                resume_mode=False,
                defer_completion=defer_completion,
            )
        finally:
            self._storage.release_execution_lock(lock)

    def resume(
        self,
        artifact: CompiledGraphArtifact,
        execution_id: str,
        *,
        defer_completion: bool = False,
    ) -> GraphExecutionResult | GraphExecutionPausedResult:
        """Recover durable node progress and continue without caller payload."""
        if type(defer_completion) is not bool:
            raise TypeError("defer_completion must be a bool")
        if not self._resume_enabled:
            raise InterruptedNodeExecutionError(
                "graph executor was not configured for resume",
                execution_id=execution_id,
            )
        detached_artifact = self._detach_artifact(artifact, execution_id=execution_id)
        lock = self._storage.acquire_execution_lock(
            execution_id,
            self._owner_id_factory(),
            timeout_seconds=self._lock_timeout_seconds,
        )
        try:
            return self._execute_locked(
                detached_artifact,
                execution_id,
                {},
                lock,
                resume_mode=True,
                defer_completion=defer_completion,
            )
        finally:
            self._storage.release_execution_lock(lock)

    def retry_from_verification(
        self,
        artifact: CompiledGraphArtifact,
        execution_id: str,
        request: VerificationRepairRequest,
        *,
        defer_completion: bool = True,
    ) -> GraphExecutionResult | GraphExecutionPausedResult:
        """Schedule one canonical external verification repair and traverse it."""

        if not isinstance(request, VerificationRepairRequest):
            raise TypeError("request must be a VerificationRepairRequest")
        if type(defer_completion) is not bool:
            raise TypeError("defer_completion must be a bool")
        if not self._resume_enabled:
            raise InterruptedNodeExecutionError(
                "verification repair requires resume-enabled graph execution",
                execution_id=execution_id,
            )
        if not isinstance(self._storage, ResumeStateStorageProvider):
            raise InterruptedNodeExecutionError(
                "verification repair payload storage is unavailable",
                execution_id=execution_id,
            )
        detached_artifact = self._detach_artifact(artifact, execution_id=execution_id)
        lock = self._storage.acquire_execution_lock(
            execution_id,
            self._owner_id_factory(),
            timeout_seconds=self._lock_timeout_seconds,
        )
        try:
            nodes = {node.id: node for node in detached_artifact.graph.nodes}
            terminals = {
                terminal.id: terminal
                for terminal in detached_artifact.graph.terminal_states
            }
            origin = nodes.get(request.origin_node_id)
            target = nodes.get(request.target_node_id)
            if (
                origin is None
                or target is None
                or origin.on_failure != target.id
                or target.retry_policy is None
            ):
                raise RetryContextIntegrityError(
                    "verification repair does not follow a bounded compiled failure edge",
                    execution_id=execution_id,
                    node_id=request.target_node_id,
                )

            record = self._storage.load_execution(execution_id, lock=lock)
            self._validate_execution_identity(record, detached_artifact)
            state_machine = EventSourcedStateMachine(
                self._storage,
                execution_id,
                lock_timeout_seconds=self._lock_timeout_seconds,
                clock=self._clock,
                event_id_factory=self._event_id_factory,
                owner_id_factory=self._owner_id_factory,
                lock=lock,
            )
            record = state_machine.recover(lock=lock)
            if record.current_state != ExecutionState.VERIFYING:
                raise InterruptedExecutionError(
                    "verification repair requires the VERIFYING state",
                    execution_id=execution_id,
                )
            terminal = terminals.get(record.current_node_id)
            if terminal is None or terminal.outcome != "success":
                raise InterruptedExecutionError(
                    "verification repair requires a successful graph terminal",
                    execution_id=execution_id,
                )

            self._recover_resume_payload(
                detached_artifact,
                record,
                nodes=nodes,
                terminals=terminals,
                lock=lock,
            )
            next_node_attempt = record.attempt_by_node.get(target.id, 0) + 1
            if request.retry_context.current_attempt != next_node_attempt:
                raise RetryContextIntegrityError(
                    "verification retry context attempt diverges from the node journal",
                    execution_id=execution_id,
                    node_id=target.id,
                )
            if next_node_attempt > target.retry_policy.max_iterations:
                state_machine.transition_to(
                    ExecutionState.FAILED_RETRY_EXHAUSTED,
                    node_id=target.id,
                    attempt=record.attempt_by_node.get(target.id, 0),
                    reason="verification_node_retry_exhausted",
                    lock=lock,
                )
                raise RetryExhaustedError(
                    "verification correction node retry limit was exhausted",
                    execution_id=execution_id,
                    node_id=target.id,
                )

            events = self._storage.load_events(execution_id, lock=lock)
            schedules = tuple(
                event
                for event in events
                if event.event_type == VERIFICATION_REPAIR_SCHEDULED
            )
            if request.repair_attempt != len(schedules) + 1:
                raise RetryContextIntegrityError(
                    "verification repair attempt is duplicated or non-sequential",
                    execution_id=execution_id,
                    node_id=target.id,
                )
            latest_suite = next(
                (
                    event
                    for event in reversed(events)
                    if event.event_type == "VERIFICATION_SUITE_RECORDED"
                ),
                None,
            )
            if (
                latest_suite is None
                or latest_suite.payload.get("attempt")
                != request.source_verification_attempt
                or latest_suite.payload.get("result_digest")
                != request.source_suite_digest
                or latest_suite.payload.get("verified_commit_sha")
                != request.source_verified_commit_sha
                or latest_suite.payload.get("all_passed") is not False
            ):
                raise RetryContextIntegrityError(
                    "verification repair source is not the latest failed canonical suite",
                    execution_id=execution_id,
                    node_id=origin.id,
                )
            self._storage.load_payload(
                execution_id,
                request.source_suite_digest,
                lock=lock,
            )
            input_digest = self._latest_node_input_digest(
                events,
                target_node_id=target.id,
                execution_id=execution_id,
            )
            self._storage.load_payload(execution_id, input_digest, lock=lock)
            context_digest = self._store_retry_context(
                execution_id,
                request.retry_context,
                lock=lock,
            )
            if context_digest is None:
                raise RetryContextIntegrityError(
                    "verification retry context was not persisted",
                    execution_id=execution_id,
                    node_id=target.id,
                )
            record = state_machine.transition_to(
                ExecutionState.EXECUTING,
                node_id=target.id,
                attempt=next_node_attempt,
                reason="verification_repair_scheduled",
                lock=lock,
            )
            events = self._storage.load_events(execution_id, lock=lock)
            minimum = max(record.updated_at, events[-1].timestamp)
            scheduled_at = self._next_timestamp(
                minimum,
                execution_id=execution_id,
                node_id=target.id,
            )
            deadline_at = request.deadline_at.astimezone(UTC)
            if deadline_at <= scheduled_at:
                state_machine.transition_to(
                    ExecutionState.FAILED_RETRY_EXHAUSTED,
                    node_id=target.id,
                    attempt=record.attempt_by_node.get(target.id, 0),
                    reason="verification_time_budget_exhausted",
                    lock=lock,
                )
                raise RetryExhaustedError(
                    "verification retry deadline was exhausted before scheduling",
                    execution_id=execution_id,
                    node_id=target.id,
                )
            self._append_verification_repair_event(
                execution_id,
                request=request,
                input_digest=input_digest,
                retry_context_digest=context_digest,
                timestamp=scheduled_at,
                lock=lock,
                record_revision=record.revision + 1,
            )
            document = record.model_dump(mode="python")
            document.update(
                {
                    "revision": record.revision + 1,
                    "current_node_id": target.id,
                    "updated_at": scheduled_at,
                }
            )
            self._storage.compare_and_set_execution(
                execution_id,
                record.revision,
                ExecutionRecord.model_validate(document),
                lock=lock,
            )
            return self._execute_locked(
                detached_artifact,
                execution_id,
                {},
                lock,
                resume_mode=True,
                defer_completion=defer_completion,
            )
        finally:
            self._storage.release_execution_lock(lock)

    def _execute_locked(
        self,
        artifact: CompiledGraphArtifact,
        execution_id: str,
        initial_input: dict[str, object],
        lock: ExecutionLock,
        *,
        resume_mode: bool,
        defer_completion: bool,
    ) -> GraphExecutionResult | GraphExecutionPausedResult:
        nodes = {node.id: node for node in artifact.graph.nodes}
        terminals = {terminal.id: terminal for terminal in artifact.graph.terminal_states}
        record = self._storage.load_execution(execution_id, lock=lock)
        self._validate_execution_identity(record, artifact)
        state_machine = EventSourcedStateMachine(
            self._storage,
            execution_id,
            lock_timeout_seconds=self._lock_timeout_seconds,
            clock=self._clock,
            event_id_factory=self._event_id_factory,
            owner_id_factory=self._owner_id_factory,
            lock=lock,
        )
        record = state_machine.recover(lock=lock)
        if record.current_state == ExecutionState.FAILED_RETRY_EXHAUSTED:
            raise RetryExhaustedError(
                "execution retry budget is already exhausted",
                execution_id=execution_id,
                node_id=record.current_node_id,
            )

        if resume_mode:
            (
                current_payload,
                retry_context,
                retry_context_digest,
            ) = self._recover_resume_payload(
                artifact,
                record,
                nodes=nodes,
                terminals=terminals,
                lock=lock,
            )
            record = self._storage.load_execution(execution_id, lock=lock)
        else:
            current_payload = initial_input
            retry_context = None
            retry_context_digest = None
        visited: set[str] = set()
        executed_node_ids: list[str] = []
        last_failure: NodeExecutionFailure | None = None

        initial_id = record.current_node_id
        initial_terminal = terminals.get(initial_id)
        if initial_terminal is not None:
            expected_state = self._terminal_execution_state(
                initial_terminal,
                defer_completion=defer_completion,
            )
            pending_terminal_transition = (
                resume_mode and record.current_state == ExecutionState.EXECUTING
            )
            if record.current_state != expected_state and not pending_terminal_transition:
                raise StateReplayError(
                    "terminal node and execution snapshot state diverge",
                    execution_id=execution_id,
                )
            return self._resolve_terminal(
                artifact,
                record,
                initial_terminal,
                current_payload,
                (),
                None,
                lock,
                state_machine=state_machine if pending_terminal_transition else None,
                defer_completion=defer_completion,
            )

        initial_node = nodes.get(initial_id)
        if initial_node is None:
            raise UnknownCurrentNodeError(
                f"current node {initial_id!r} is not declared by the artifact",
                execution_id=execution_id,
                node_id=initial_id,
            )
        self._validate_node_input(
            artifact,
            initial_node,
            current_payload,
            execution_id,
        )
        initial_executor = self._executors.select(initial_node)
        if not (
            isinstance(initial_node, HumanApprovalNodeSpec)
            and self._approval_handler is not None
        ):
            initial_executor.ensure_available()
        if resume_mode:
            if record.current_state != ExecutionState.EXECUTING:
                raise InterruptedExecutionError(
                    "resumable nonterminal execution must be EXECUTING",
                    execution_id=execution_id,
                )
        else:
            if (
                record.current_state
                not in {ExecutionState.INITIATED, ExecutionState.PLANNING}
                or initial_id != artifact.graph.graph.entrypoint
            ):
                raise InterruptedExecutionError(
                    "nonterminal execution requires the F2.5 resume contract",
                    execution_id=execution_id,
                )
            initial_attempt = record.attempt_by_node.get(initial_id, 0) + 1
            record = state_machine.transition_to(
                ExecutionState.EXECUTING,
                node_id=initial_id,
                attempt=initial_attempt,
                reason="graph_execution_started",
                lock=lock,
            )

        while True:
            current_id = record.current_node_id
            terminal = terminals.get(current_id)
            if terminal is not None:
                return self._resolve_terminal(
                    artifact,
                    record,
                    terminal,
                    current_payload,
                    tuple(executed_node_ids),
                    last_failure,
                    lock,
                    state_machine=state_machine,
                    defer_completion=defer_completion,
                )

            node = nodes.get(current_id)
            if node is None:
                raise UnknownCurrentNodeError(
                    f"current node {current_id!r} is not declared by the artifact",
                    execution_id=execution_id,
                    node_id=current_id,
                )
            previous_attempts = record.attempt_by_node.get(current_id, 0)
            attempt = previous_attempts + 1
            revisited = previous_attempts > 0 or current_id in visited
            if revisited and (
                retry_context is None or node.retry_policy is None
            ):
                raise GraphCycleExecutionError(
                    "node revisit requires an active bounded retry context",
                    execution_id=execution_id,
                    node_id=current_id,
                )
            if retry_context is not None:
                if retry_context.current_attempt != attempt:
                    raise RetryContextIntegrityError(
                        "retry context attempt does not match the execution record",
                        execution_id=execution_id,
                        node_id=current_id,
                    )
                if (
                    node.retry_policy is not None
                    and attempt > node.retry_policy.max_iterations
                ):
                    state_machine.transition_to(
                        ExecutionState.FAILED_RETRY_EXHAUSTED,
                        node_id=current_id,
                        attempt=previous_attempts,
                        reason="node_retry_exhausted",
                        lock=lock,
                    )
                    raise RetryExhaustedError(
                        "node retry limit was exhausted",
                        execution_id=execution_id,
                        node_id=current_id,
                    )
            if (
                self._resume_enabled
                and (retry_context is None) != (retry_context_digest is None)
            ):
                raise RetryContextIntegrityError(
                    "retry context and durable digest presence diverge",
                    execution_id=execution_id,
                    node_id=current_id,
                )

            self._validate_node_input(artifact, node, current_payload, execution_id)
            executor = self._executors.select(node)
            input_digest = self._store_payload(
                execution_id,
                current_payload,
                lock=lock,
            )
            approval_granted = False
            if isinstance(node, HumanApprovalNodeSpec) and self._approval_handler is not None:
                if input_digest is None:
                    raise GraphExecutionError(
                        "approval pause requires durable payload storage",
                        execution_id=execution_id,
                        node_id=node.id,
                    )
                approval_granted = self._approval_handler.is_approval_granted(
                    record=record,
                    node=node,
                    input_digest=input_digest,
                    lock=lock,
                )
            if (
                isinstance(node, HumanApprovalNodeSpec)
                and self._approval_handler is not None
                and not approval_granted
            ):
                if input_digest is None:
                    raise GraphExecutionError(
                        "approval pause requires durable payload storage",
                        execution_id=execution_id,
                        node_id=node.id,
                    )
                return self._approval_handler.pause_for_approval(
                    artifact=artifact,
                    record=record,
                    node=node,
                    input_digest=input_digest,
                    executed_node_ids=tuple(executed_node_ids),
                    lock=lock,
                )
            skip_human_backend = (
                isinstance(node, HumanApprovalNodeSpec)
                and self._approval_handler is not None
                and approval_granted
            )
            if not skip_human_backend:
                executor.ensure_available()
            started_at = self._next_timestamp(
                record.updated_at,
                execution_id=execution_id,
                node_id=current_id,
            )
            self._append_node_event(
                execution_id,
                node,
                "NODE_STARTED",
                attempt,
                lock,
                started_at,
                input_digest=input_digest,
                retry_context_digest=retry_context_digest,
            )
            tool_effect_recorder = _DurableToolEffectRecorder(
                owner=self,
                execution_id=execution_id,
                node=node,
                attempt=attempt,
                lock=lock,
                current_timestamp=started_at,
            )
            context = NodeExecutionContext(
                execution_id=execution_id,
                artifact=artifact,
                node=node,
                attempt=attempt,
                input_payload=current_payload,
                fencing_token=lock.fencing_token,
                retry_context=retry_context,
                tool_effect_recorder=tool_effect_recorder,
            )

            result = (
                NodeExecutionResult.completed(current_payload)
                if skip_human_backend
                else self._execute_node(executor, context)
            )
            if result.succeeded:
                try:
                    self._validate_node_output(
                        artifact,
                        node,
                        result.output,
                        execution_id,
                    )
                except NodeOutputValidationError:
                    result = NodeExecutionResult.failed(
                        {},
                        code="invalid_node_output",
                        message="node output did not satisfy its declared contract",
                        retryable=False,
                        model_calls=result.model_calls,
                        tool_executions=result.tool_executions,
                    )

            last_tool_event_at = tool_effect_recorder.finish(
                result.tool_executions
            )

            next_id = node.on_success if result.succeeded else node.on_failure
            next_retry_context = self._next_retry_context(
                result,
                node_id=current_id,
                next_id=next_id,
                attempt=attempt,
                record=record,
                nodes=nodes,
                current_context=retry_context,
                execution_id=execution_id,
            )
            next_retry_context_digest = self._store_retry_context(
                execution_id,
                next_retry_context,
                lock=lock,
            )
            outcome_type: Literal["NODE_COMPLETED", "NODE_FAILED"] = (
                "NODE_COMPLETED" if result.succeeded else "NODE_FAILED"
            )
            outcome_at = self._next_timestamp(
                last_tool_event_at,
                execution_id=execution_id,
                node_id=current_id,
            )
            output_digest = self._store_payload(
                execution_id,
                result.output,
                lock=lock,
            )
            self._append_node_event(
                execution_id,
                node,
                outcome_type,
                attempt,
                lock,
                outcome_at,
                next_id=next_id,
                failure=result.failure,
                input_digest=input_digest,
                output_digest=output_digest,
                record_revision=record.revision + 1,
                next_retry_context_digest=next_retry_context_digest,
                model_calls=result.model_calls,
            )

            replacement = self._next_record(
                record,
                next_id=next_id,
                node_id=current_id,
                attempt=attempt,
                updated_at=outcome_at,
            )
            record = self._storage.compare_and_set_execution(
                execution_id,
                record.revision,
                replacement,
                lock=lock,
            )
            visited.add(current_id)
            executed_node_ids.append(current_id)
            current_payload = result.output
            last_failure = result.failure
            retry_context = next_retry_context
            retry_context_digest = next_retry_context_digest

    def _resolve_terminal(
        self,
        artifact: CompiledGraphArtifact,
        record: ExecutionRecord,
        terminal: TerminalStateSpec,
        payload: dict[str, object],
        executed_node_ids: tuple[str, ...],
        last_failure: NodeExecutionFailure | None,
        lock: ExecutionLock,
        *,
        state_machine: EventSourcedStateMachine | None,
        defer_completion: bool,
    ) -> GraphExecutionResult:
        executor = self._executors.select(terminal)
        executor.ensure_available()
        terminal_result = executor.execute(
            NodeExecutionContext(
                execution_id=record.execution_id,
                artifact=artifact,
                node=terminal,
                attempt=0,
                input_payload=payload,
                fencing_token=lock.fencing_token,
            )
        )
        failure = None
        if terminal.outcome == "failure":
            failure = last_failure or terminal_result.failure
        final_record = record
        if state_machine is not None:
            final_state = self._terminal_execution_state(
                terminal,
                defer_completion=defer_completion,
            )
            final_record = state_machine.transition_to(
                final_state,
                node_id=terminal.id,
                attempt=0,
                reason={
                    ExecutionState.COMPLETED: "graph_completed",
                    ExecutionState.VERIFYING: "graph_ready_for_verification",
                    ExecutionState.FAILED: "graph_failed",
                }[final_state],
                lock=lock,
            )
        return GraphExecutionResult(
            execution_id=record.execution_id,
            terminal_id=terminal.id,
            outcome=terminal.outcome,
            output=terminal_result.output,
            executed_node_ids=executed_node_ids,
            final_revision=final_record.revision,
            fencing_token=lock.fencing_token,
            failure=failure,
        )

    @staticmethod
    def _terminal_execution_state(
        terminal: TerminalStateSpec,
        *,
        defer_completion: bool,
    ) -> ExecutionState:
        if terminal.outcome == "success":
            return (
                ExecutionState.VERIFYING
                if defer_completion
                else ExecutionState.COMPLETED
            )
        return ExecutionState.FAILED

    @staticmethod
    def _execute_node(
        executor: NodeExecutor,
        context: NodeExecutionContext,
    ) -> NodeExecutionResult:
        try:
            result = executor.execute(context)
        except NodeBackendError as exc:
            return NodeExecutionResult.failed(
                {},
                code=exc.code,
                message=exc.message,
                retryable=exc.retryable,
                retry_evidence=exc.retry_evidence,
            )
        except NodeExecutorResultError as exc:
            return NodeExecutionResult.failed(
                {},
                code="invalid_node_result",
                message=str(exc),
                retryable=False,
            )
        except NodeExecutorError:
            raise
        if not isinstance(result, NodeExecutionResult):
            return NodeExecutionResult.failed(
                {},
                code="invalid_node_result",
                message="node executor returned an invalid result",
                retryable=False,
            )
        return result

    def _next_retry_context(
        self,
        result: NodeExecutionResult,
        *,
        node_id: str,
        next_id: str,
        attempt: int,
        record: ExecutionRecord,
        nodes: Mapping[str, NodeSpec],
        current_context: RetryContext | None,
        execution_id: str,
    ) -> RetryContext | None:
        if not result.succeeded:
            failure = result.failure
            if failure is None:
                raise RetryContextIntegrityError(
                    "failed node result is missing failure details",
                    execution_id=execution_id,
                    node_id=node_id,
                )
            if not failure.retryable or next_id not in nodes:
                return None
            if failure.retry_evidence is None:
                raise RetryContextIntegrityError(
                    "retryable failure is missing retry evidence",
                    execution_id=execution_id,
                    node_id=node_id,
                )
            return self._build_retry_context(
                failure.retry_evidence,
                origin_node_id=node_id,
                current_attempt=self._next_attempt(
                    record,
                    next_id=next_id,
                    current_node_id=node_id,
                    current_attempt=attempt,
                ),
            )

        if current_context is None or node_id == current_context.origin_node_id:
            return None
        if next_id not in nodes:
            return None
        return current_context.model_copy(
            update={
                "current_attempt": self._next_attempt(
                    record,
                    next_id=next_id,
                    current_node_id=node_id,
                    current_attempt=attempt,
                )
            }
        )

    @staticmethod
    def _next_attempt(
        record: ExecutionRecord,
        *,
        next_id: str,
        current_node_id: str,
        current_attempt: int,
    ) -> int:
        previous_attempts = (
            current_attempt
            if next_id == current_node_id
            else record.attempt_by_node.get(next_id, 0)
        )
        return previous_attempts + 1

    @staticmethod
    def _build_retry_context(
        evidence: RetryEvidence,
        *,
        origin_node_id: str,
        current_attempt: int,
    ) -> RetryContext:
        failed_tool_call = evidence.failed_tool_call
        redacted_tool_call = None
        if failed_tool_call is not None:
            redacted_tool_call = FailedToolCall(
                tool_name=Redactor.redact_text(failed_tool_call.tool_name),
                call_id=(
                    Redactor.redact_text(failed_tool_call.call_id)
                    if failed_tool_call.call_id is not None
                    else None
                ),
                arguments_digest=failed_tool_call.arguments_digest,
                error_code=(
                    Redactor.redact_text(failed_tool_call.error_code)
                    if failed_tool_call.error_code is not None
                    else None
                ),
            )
        return RetryContext(
            origin_node_id=origin_node_id,
            current_attempt=current_attempt,
            model_error=(
                Redactor.redact_text(evidence.model_error)
                if evidence.model_error is not None
                else None
            ),
            failed_tool_call=redacted_tool_call,
            redacted_stdout=Redactor.redact_text(evidence.stdout),
            redacted_stderr=Redactor.redact_text(evidence.stderr),
            failed_gates=tuple(
                Redactor.redact_text(gate) for gate in evidence.failed_gates
            ),
            current_diff=Redactor.redact_text(evidence.current_diff),
            remaining_budget=evidence.remaining_budget,
            correction_instruction=Redactor.redact_text(
                evidence.correction_instruction
            ),
        )

    def _store_retry_context(
        self,
        execution_id: str,
        context: RetryContext | None,
        *,
        lock: ExecutionLock,
    ) -> str | None:
        if context is None or not self._resume_enabled:
            return None
        if not isinstance(self._storage, ResumeStateStorageProvider):
            raise RetryContextIntegrityError(
                "retry context storage is unavailable",
                execution_id=execution_id,
            )
        return self._storage.store_payload(
            execution_id,
            context.model_dump(mode="json"),
            lock=lock,
        )

    def _append_node_event(
        self,
        execution_id: str,
        node: NodeSpec,
        event_type: Literal["NODE_STARTED", "NODE_COMPLETED", "NODE_FAILED"],
        attempt: int,
        lock: ExecutionLock,
        timestamp: datetime,
        *,
        next_id: str | None = None,
        failure: NodeExecutionFailure | None = None,
        input_digest: str | None = None,
        output_digest: str | None = None,
        record_revision: int | None = None,
        retry_context_digest: str | None = None,
        next_retry_context_digest: str | None = None,
        model_calls: tuple[ModelCallMetadata, ...] = (),
    ) -> None:
        payload: dict[str, object] = {
            "attempt": attempt,
            "fencing_token": lock.fencing_token,
            "node_id": node.id,
            "node_type": node.type,
        }
        if next_id is not None:
            payload["next_id"] = next_id
        if input_digest is not None:
            payload["input_digest"] = input_digest
        if output_digest is not None:
            payload["output_digest"] = output_digest
        if record_revision is not None:
            payload["record_revision"] = record_revision
        if retry_context_digest is not None:
            payload["retry_context_digest"] = retry_context_digest
        if next_retry_context_digest is not None:
            payload["next_retry_context_digest"] = next_retry_context_digest
        if failure is not None:
            payload["error_code"] = failure.code
            payload["retryable"] = failure.retryable
        if model_calls:
            payload["model_calls"] = [
                model_call.model_dump(mode="json") for model_call in model_calls
            ]
        try:
            event = ExecutionEvent(
                event_id=self._event_id_factory(),
                execution_id=execution_id,
                event_type=event_type,
                timestamp=timestamp,
                payload=payload,
            )
        except (TypeError, ValueError, ValidationError) as exc:
            raise GraphEventConstructionError(
                "cannot construct a canonical node event",
                execution_id=execution_id,
                node_id=node.id,
            ) from exc
        self._storage.append_event(execution_id, event, lock=lock)

    def _append_verification_repair_event(
        self,
        execution_id: str,
        *,
        request: VerificationRepairRequest,
        input_digest: str,
        retry_context_digest: str,
        timestamp: datetime,
        lock: ExecutionLock,
        record_revision: int,
    ) -> None:
        budget = request.retry_context.remaining_budget
        payload: dict[str, object] = {
            "repair_attempt": request.repair_attempt,
            "source_verification_attempt": request.source_verification_attempt,
            "source_result_digest": request.source_suite_digest,
            "source_verified_commit_sha": request.source_verified_commit_sha,
            "origin_node_id": request.origin_node_id,
            "target_node_id": request.target_node_id,
            "input_digest": input_digest,
            "retry_context_digest": retry_context_digest,
            "retry_policy_digest": request.retry_policy_digest,
            "remaining_tokens": budget.remaining_tokens,
            "remaining_cost_usd": budget.remaining_cost_usd,
            "remaining_time_seconds": budget.remaining_time_seconds,
            "deadline_at": request.deadline_at.astimezone(UTC).isoformat(),
            "fencing_token": lock.fencing_token,
            "record_revision": record_revision,
        }
        try:
            event = ExecutionEvent(
                event_id=self._event_id_factory(),
                execution_id=execution_id,
                event_type=VERIFICATION_REPAIR_SCHEDULED,
                timestamp=timestamp,
                payload=payload,
            )
        except (TypeError, ValueError, ValidationError) as exc:
            raise GraphEventConstructionError(
                "cannot construct a canonical verification repair event",
                execution_id=execution_id,
                node_id=request.target_node_id,
            ) from exc
        self._storage.append_event(execution_id, event, lock=lock)

    def _append_tool_event(
        self,
        execution_id: str,
        node: NodeSpec,
        attempt: int,
        lock: ExecutionLock,
        timestamp: datetime,
        event_type: Literal["TOOL_CALLED", "TOOL_COMPLETED", "TOOL_FAILED"],
        record: ToolCallIntent | ToolExecutionRecord,
    ) -> None:
        payload: dict[str, object] = {
            "attempt": attempt,
            "fencing_token": lock.fencing_token,
            "node_id": node.id,
            "step": record.step,
            "call_id": record.call_id,
            "tool_name": record.tool_name,
            "arguments_digest": record.arguments_digest,
        }
        if event_type == "TOOL_CALLED":
            if not isinstance(record, ToolCallIntent):
                raise GraphEventConstructionError(
                    "tool write-ahead requires a call intent",
                    execution_id=execution_id,
                    node_id=node.id,
                )
            payload["policy_decision"] = record.policy_decision.model_dump(mode="json")
        else:
            if not isinstance(record, ToolExecutionRecord):
                raise GraphEventConstructionError(
                    "tool outcome requires a completed execution record",
                    execution_id=execution_id,
                    node_id=node.id,
                )
            payload["result_digest"] = record.result_digest
            payload["redacted_result"] = record.redacted_result
            payload["policy_decision_digest"] = record.policy_decision_digest
            if record.error_code is not None:
                payload["error_code"] = record.error_code
        try:
            event = ExecutionEvent(
                event_id=self._event_id_factory(),
                execution_id=execution_id,
                event_type=event_type,
                timestamp=timestamp,
                payload=payload,
            )
        except (TypeError, ValueError, ValidationError) as exc:
            raise GraphEventConstructionError(
                "cannot construct a canonical tool event",
                execution_id=execution_id,
                node_id=node.id,
            ) from exc
        self._storage.append_event(execution_id, event, lock=lock)

    def _store_payload(
        self,
        execution_id: str,
        payload: dict[str, object],
        *,
        lock: ExecutionLock,
    ) -> str | None:
        if not self._resume_enabled:
            return None
        if not isinstance(self._storage, ResumeStateStorageProvider):
            raise GraphExecutionError(
                "resume payload storage is unavailable",
                execution_id=execution_id,
            )
        return self._storage.store_payload(execution_id, payload, lock=lock)

    def _recover_resume_payload(
        self,
        artifact: CompiledGraphArtifact,
        record: ExecutionRecord,
        *,
        nodes: Mapping[str, NodeSpec],
        terminals: Mapping[str, TerminalStateSpec],
        lock: ExecutionLock,
    ) -> tuple[dict[str, object], RetryContext | None, str | None]:
        if not isinstance(self._storage, ResumeStateStorageProvider):
            raise InterruptedNodeExecutionError(
                "resume bundle storage is unavailable",
                execution_id=record.execution_id,
            )
        bundle = self._storage.load_execution_bundle(record.execution_id, lock=lock)
        if (
            bundle.artifact_digest != record.artifact_digest
            or bundle.configuration_digest != record.configuration_digest
            or bundle.execution_id != record.execution_id
        ):
            raise ArtifactExecutionMismatchError(
                "resume bundle does not match immutable execution identity",
                execution_id=record.execution_id,
            )
        artifact_digest = "sha256:" + hashlib.sha256(
            artifact.canonical_json().encode("utf-8")
        ).hexdigest()
        if artifact_digest != bundle.artifact_digest:
            raise ArtifactExecutionMismatchError(
                "resume artifact does not match the stored bundle",
                execution_id=record.execution_id,
            )

        expected_node_id = artifact.graph.graph.entrypoint
        expected_payload_digest = bundle.initial_input_digest
        expected_retry_context: RetryContext | None = None
        expected_retry_context_digest: str | None = None
        attempts: dict[str, int] = {}
        open_started: tuple[
            str,
            int,
            str,
            str,
            int,
            str | None,
            RetryContext | None,
        ] | None = None
        open_tool: tuple[str, int, int, str, str, str, int, str | None] | None = None
        next_tool_step = 1
        pending: tuple[ExecutionEvent, str, int, str] | None = None
        pending_repair: tuple[ExecutionEvent, str] | None = None
        last_record_revision = -1
        last_fencing_token = 0
        last_timestamp: datetime | None = None
        last_mutation_revision = 0
        last_global_fencing_token = 0
        last_verification_suite: tuple[int, str, str, bool] | None = None
        repair_attempts = 0
        last_input_digest_by_node: dict[str, str] = {}

        for event in self._storage.load_events(record.execution_id, lock=lock):
            payload = event.payload
            if "record_revision" in payload:
                mutation_revision = self._ledger_integer(
                    payload["record_revision"],
                    field="record_revision",
                    minimum=1,
                )
                if mutation_revision != last_mutation_revision + 1:
                    raise InterruptedNodeExecutionError(
                        "durable mutation revisions contain a duplicate or gap",
                        execution_id=record.execution_id,
                    )
                if mutation_revision > record.revision + 1:
                    raise InterruptedNodeExecutionError(
                        "durable mutation revision is beyond recoverable state",
                        execution_id=record.execution_id,
                    )
                last_mutation_revision = mutation_revision
            if "fencing_token" in payload:
                global_fencing_token = self._ledger_integer(
                    payload["fencing_token"],
                    field="fencing_token",
                    minimum=1,
                )
                if global_fencing_token < last_global_fencing_token:
                    raise InterruptedNodeExecutionError(
                        "durable event fencing token regressed",
                        execution_id=record.execution_id,
                    )
                last_global_fencing_token = global_fencing_token
            if event.event_type == "VERIFICATION_SUITE_RECORDED":
                attempt = self._ledger_integer(
                    payload.get("attempt"), field="attempt", minimum=1
                )
                result_digest = self._ledger_digest(payload.get("result_digest"))
                verified_commit_sha = self._ledger_string(
                    payload.get("verified_commit_sha"),
                    field="verified_commit_sha",
                )
                all_passed = payload.get("all_passed")
                if (
                    len(verified_commit_sha) != 40
                    or verified_commit_sha.lower() != verified_commit_sha
                    or type(all_passed) is not bool
                ):
                    raise InterruptedNodeExecutionError(
                        "verification suite identity is invalid",
                        execution_id=record.execution_id,
                    )
                self._storage.load_payload(
                    record.execution_id,
                    result_digest,
                    lock=lock,
                )
                last_verification_suite = (
                    attempt,
                    result_digest,
                    verified_commit_sha,
                    all_passed,
                )
                continue

            if event.event_type == VERIFICATION_REPAIR_SCHEDULED:
                expected_keys = {
                    "repair_attempt",
                    "source_verification_attempt",
                    "source_result_digest",
                    "source_verified_commit_sha",
                    "origin_node_id",
                    "target_node_id",
                    "input_digest",
                    "retry_context_digest",
                    "retry_policy_digest",
                    "remaining_tokens",
                    "remaining_cost_usd",
                    "remaining_time_seconds",
                    "deadline_at",
                    "fencing_token",
                    "record_revision",
                }
                if set(payload) != expected_keys or open_started is not None:
                    raise InterruptedNodeExecutionError(
                        "verification repair schedule is malformed or overlaps a node",
                        execution_id=record.execution_id,
                    )
                if last_timestamp is not None and event.timestamp < last_timestamp:
                    raise InterruptedNodeExecutionError(
                        "verification repair timestamp regressed",
                        execution_id=record.execution_id,
                    )
                repair_attempt = self._ledger_integer(
                    payload["repair_attempt"],
                    field="repair_attempt",
                    minimum=1,
                )
                if repair_attempt != repair_attempts + 1:
                    raise InterruptedNodeExecutionError(
                        "verification repair attempts are non-sequential",
                        execution_id=record.execution_id,
                    )
                source_attempt = self._ledger_integer(
                    payload["source_verification_attempt"],
                    field="source_verification_attempt",
                    minimum=1,
                )
                source_digest = self._ledger_digest(payload["source_result_digest"])
                source_commit = self._ledger_string(
                    payload["source_verified_commit_sha"],
                    field="source_verified_commit_sha",
                )
                if last_verification_suite != (
                    source_attempt,
                    source_digest,
                    source_commit,
                    False,
                ):
                    raise InterruptedNodeExecutionError(
                        "verification repair does not consume the latest failed suite",
                        execution_id=record.execution_id,
                    )
                terminal = terminals.get(expected_node_id)
                if terminal is None or terminal.outcome != "success":
                    raise InterruptedNodeExecutionError(
                        "verification repair did not start from a successful terminal",
                        execution_id=record.execution_id,
                    )
                origin_node_id = self._ledger_string(
                    payload["origin_node_id"], field="origin_node_id"
                )
                target_node_id = self._ledger_string(
                    payload["target_node_id"], field="target_node_id"
                )
                origin = nodes.get(origin_node_id)
                target = nodes.get(target_node_id)
                if (
                    origin is None
                    or target is None
                    or origin.on_failure != target_node_id
                    or target.retry_policy is None
                ):
                    raise InterruptedNodeExecutionError(
                        "verification repair edge is absent or unbounded",
                        execution_id=record.execution_id,
                        node_id=target_node_id,
                    )
                input_digest = self._ledger_digest(payload["input_digest"])
                if last_input_digest_by_node.get(target_node_id) != input_digest:
                    raise InterruptedNodeExecutionError(
                        "verification repair input is not the latest durable node input",
                        execution_id=record.execution_id,
                        node_id=target_node_id,
                    )
                self._storage.load_payload(
                    record.execution_id,
                    input_digest,
                    lock=lock,
                )
                context_digest = self._ledger_digest(
                    payload["retry_context_digest"]
                )
                context = self._load_retry_context(
                    record.execution_id,
                    context_digest,
                    nodes=nodes,
                    lock=lock,
                )
                next_attempt = attempts.get(target_node_id, 0) + 1
                remaining_tokens = self._ledger_integer(
                    payload["remaining_tokens"],
                    field="remaining_tokens",
                    minimum=0,
                )
                remaining_cost = payload["remaining_cost_usd"]
                remaining_time = payload["remaining_time_seconds"]
                if (
                    type(remaining_cost) is not float
                    or not math.isfinite(remaining_cost)
                    or remaining_cost < 0
                    or type(remaining_time) is not float
                    or not math.isfinite(remaining_time)
                    or remaining_time <= 0
                    or context.origin_node_id != origin_node_id
                    or context.current_attempt != next_attempt
                    or context.failed_commit_sha != source_commit
                    or context.remaining_budget.remaining_tokens
                    != remaining_tokens
                    or context.remaining_budget.remaining_cost_usd
                    != remaining_cost
                    or context.remaining_budget.remaining_time_seconds
                    != remaining_time
                ):
                    raise RetryContextIntegrityError(
                        "verification repair context diverges from its durable budget",
                        execution_id=record.execution_id,
                        node_id=target_node_id,
                    )
                self._ledger_digest(payload["retry_policy_digest"])
                deadline_text = self._ledger_string(
                    payload["deadline_at"], field="deadline_at"
                )
                try:
                    deadline_at = datetime.fromisoformat(deadline_text)
                except ValueError as exc:
                    raise InterruptedNodeExecutionError(
                        "verification repair deadline is invalid",
                        execution_id=record.execution_id,
                    ) from exc
                if (
                    deadline_at.tzinfo is None
                    or deadline_at.utcoffset() is None
                    or deadline_at.astimezone(UTC) <= event.timestamp
                ):
                    raise InterruptedNodeExecutionError(
                        "verification repair deadline is already exhausted",
                        execution_id=record.execution_id,
                    )
                repair_revision = self._ledger_integer(
                    payload["record_revision"],
                    field="record_revision",
                    minimum=1,
                )
                if repair_revision > record.revision:
                    if (
                        pending_repair is not None
                        or repair_revision != record.revision + 1
                    ):
                        raise InterruptedNodeExecutionError(
                            "verification repair cursor has an invalid pending revision",
                            execution_id=record.execution_id,
                        )
                    pending_repair = (event, target_node_id)
                expected_node_id = target_node_id
                expected_payload_digest = input_digest
                expected_retry_context = context
                expected_retry_context_digest = context_digest
                repair_attempts = repair_attempt
                last_timestamp = event.timestamp
                continue

            if event.event_type not in {
                "NODE_STARTED",
                "NODE_COMPLETED",
                "NODE_FAILED",
                "TOOL_CALLED",
                "TOOL_COMPLETED",
                "TOOL_FAILED",
            }:
                continue
            if last_timestamp is not None and event.timestamp < last_timestamp:
                raise InterruptedNodeExecutionError(
                    "node event timestamps cannot regress",
                    execution_id=record.execution_id,
                )
            last_timestamp = event.timestamp
            if event.event_type == "NODE_STARTED":
                expected_keys = {
                    "attempt",
                    "fencing_token",
                    "input_digest",
                    "node_id",
                    "node_type",
                }
                if expected_retry_context_digest is not None:
                    expected_keys.add("retry_context_digest")
                if set(payload) != expected_keys or open_started is not None:
                    raise InterruptedNodeExecutionError(
                        "node start ledger is malformed or overlapping",
                        execution_id=record.execution_id,
                    )
                node_id = self._ledger_string(payload["node_id"], field="node_id")
                node = nodes.get(node_id)
                if node is None or node_id != expected_node_id:
                    raise InterruptedNodeExecutionError(
                        "node start does not follow the compiled graph",
                        execution_id=record.execution_id,
                        node_id=node_id,
                    )
                node_type = self._ledger_string(payload["node_type"], field="node_type")
                if node_type != node.type:
                    raise InterruptedNodeExecutionError(
                        "node start type does not match the artifact",
                        execution_id=record.execution_id,
                        node_id=node_id,
                    )
                attempt = self._ledger_integer(payload["attempt"], field="attempt", minimum=1)
                if attempt != attempts.get(node_id, 0) + 1:
                    raise InterruptedNodeExecutionError(
                        "node attempt is duplicated or non-sequential",
                        execution_id=record.execution_id,
                        node_id=node_id,
                    )
                observed_retry_context_digest = None
                consumed_retry_context = None
                if expected_retry_context_digest is not None:
                    observed_retry_context_digest = self._ledger_digest(
                        payload["retry_context_digest"]
                    )
                    if observed_retry_context_digest != expected_retry_context_digest:
                        raise RetryContextIntegrityError(
                            "node start retry context breaks the durable digest chain",
                            execution_id=record.execution_id,
                            node_id=node_id,
                        )
                    consumed_retry_context = expected_retry_context
                    if (
                        consumed_retry_context is None
                        or consumed_retry_context.current_attempt != attempt
                    ):
                        raise RetryContextIntegrityError(
                            "node start retry context attempt is divergent",
                            execution_id=record.execution_id,
                            node_id=node_id,
                        )
                fencing_token = self._ledger_integer(
                    payload["fencing_token"],
                    field="fencing_token",
                    minimum=1,
                )
                if fencing_token < last_fencing_token:
                    raise InterruptedNodeExecutionError(
                        "node fencing token regressed",
                        execution_id=record.execution_id,
                        node_id=node_id,
                    )
                input_digest = self._ledger_digest(payload["input_digest"])
                if input_digest != expected_payload_digest:
                    raise InterruptedNodeExecutionError(
                        "node input digest breaks the durable payload chain",
                        execution_id=record.execution_id,
                        node_id=node_id,
                    )
                self._storage.load_payload(
                    record.execution_id,
                    input_digest,
                    lock=lock,
                )
                open_started = (
                    node_id,
                    attempt,
                    input_digest,
                    node_type,
                    fencing_token,
                    observed_retry_context_digest,
                    consumed_retry_context,
                )
                last_input_digest_by_node[node_id] = input_digest
                open_tool = None
                next_tool_step = 1
                last_fencing_token = fencing_token
                continue

            if event.event_type in {"TOOL_CALLED", "TOOL_COMPLETED", "TOOL_FAILED"}:
                tool_base_keys = {
                    "attempt",
                    "fencing_token",
                    "node_id",
                    "step",
                    "call_id",
                    "tool_name",
                    "arguments_digest",
                }
                if event.event_type == "TOOL_CALLED":
                    observed_keys = set(payload)
                    legacy_keys = tool_base_keys
                    policy_keys = tool_base_keys | {"policy_decision"}
                    if (
                        observed_keys not in (legacy_keys, policy_keys)
                        or open_started is None
                        or open_tool is not None
                    ):
                        raise InterruptedNodeExecutionError(
                            "tool call ledger is malformed or overlapping",
                            execution_id=record.execution_id,
                        )
                    tool_node_id = self._ledger_string(
                        payload["node_id"], field="node_id"
                    )
                    tool_attempt = self._ledger_integer(
                        payload["attempt"], field="attempt", minimum=1
                    )
                    step = self._ledger_integer(payload["step"], field="step", minimum=1)
                    call_id = self._ledger_string(payload["call_id"], field="call_id")
                    tool_name = self._ledger_string(payload["tool_name"], field="tool_name")
                    arguments_digest = self._ledger_digest(payload["arguments_digest"])
                    tool_fencing = self._ledger_integer(
                        payload["fencing_token"], field="fencing_token", minimum=1
                    )
                    if (
                        tool_node_id != open_started[0]
                        or tool_attempt != open_started[1]
                        or tool_fencing != open_started[4]
                        or step != next_tool_step
                    ):
                        raise InterruptedNodeExecutionError(
                            "tool call does not match its open node attempt",
                            execution_id=record.execution_id,
                            node_id=tool_node_id,
                        )
                    policy_decision_digest: str | None = None
                    if "policy_decision" in payload:
                        try:
                            policy_decision = ToolPolicyDecision.model_validate(
                                payload["policy_decision"]
                            )
                        except (TypeError, ValueError, ValidationError) as exc:
                            raise InterruptedNodeExecutionError(
                                "tool policy decision is malformed",
                                execution_id=record.execution_id,
                                node_id=tool_node_id,
                            ) from exc
                        graph_node = nodes.get(tool_node_id)
                        if (
                            not policy_decision.allowed
                            or not isinstance(graph_node, AgentNodeSpec)
                            or policy_decision.request.node_id != tool_node_id
                            or policy_decision.request.role != graph_node.role
                            or policy_decision.request.workflow != artifact.graph.graph.name
                            or policy_decision.request.tool != tool_name
                        ):
                            raise InterruptedNodeExecutionError(
                                "tool policy decision diverges from the compiled node",
                                execution_id=record.execution_id,
                                node_id=tool_node_id,
                            )
                        policy_decision_digest = policy_decision.digest()
                    open_tool = (
                        tool_node_id,
                        tool_attempt,
                        step,
                        call_id,
                        tool_name,
                        arguments_digest,
                        tool_fencing,
                        policy_decision_digest,
                    )
                    continue

                expected_tool_outcome = tool_base_keys | {
                    "result_digest",
                    "redacted_result",
                }
                if event.event_type == "TOOL_FAILED":
                    expected_tool_outcome.add("error_code")
                if open_tool is not None and open_tool[7] is not None:
                    expected_tool_outcome.add("policy_decision_digest")
                if set(payload) != expected_tool_outcome or open_tool is None:
                    raise InterruptedNodeExecutionError(
                        "tool outcome ledger is malformed or has no matching call",
                        execution_id=record.execution_id,
                    )
                observed_tool = (
                    self._ledger_string(payload["node_id"], field="node_id"),
                    self._ledger_integer(payload["attempt"], field="attempt", minimum=1),
                    self._ledger_integer(payload["step"], field="step", minimum=1),
                    self._ledger_string(payload["call_id"], field="call_id"),
                    self._ledger_string(payload["tool_name"], field="tool_name"),
                    self._ledger_digest(payload["arguments_digest"]),
                    self._ledger_integer(
                        payload["fencing_token"], field="fencing_token", minimum=1
                    ),
                )
                if observed_tool != open_tool[:7]:
                    raise InterruptedNodeExecutionError(
                        "tool outcome does not match its call",
                        execution_id=record.execution_id,
                        node_id=observed_tool[0],
                    )
                self._ledger_digest(payload["result_digest"])
                if open_tool[7] is not None:
                    observed_decision_digest = self._ledger_digest(
                        payload["policy_decision_digest"]
                    )
                    if observed_decision_digest != open_tool[7]:
                        raise InterruptedNodeExecutionError(
                            "tool outcome policy decision does not match its call",
                            execution_id=record.execution_id,
                            node_id=observed_tool[0],
                        )
                redacted_result = payload["redacted_result"]
                if type(redacted_result) is not str or len(redacted_result) > 2_000:
                    raise InterruptedNodeExecutionError(
                        "redacted_result must be a bounded string",
                        execution_id=record.execution_id,
                    )
                if event.event_type == "TOOL_FAILED":
                    self._ledger_string(payload["error_code"], field="error_code")
                open_tool = None
                next_tool_step += 1
                continue

            failed = event.event_type == "NODE_FAILED"
            expected_keys = {
                "attempt",
                "fencing_token",
                "input_digest",
                "next_id",
                "node_id",
                "node_type",
                "output_digest",
                "record_revision",
            }
            if failed:
                expected_keys.update({"error_code", "retryable"})
            if "next_retry_context_digest" in payload:
                expected_keys.add("next_retry_context_digest")
            model_required_keys = {
                "model_provider",
                "model_name",
                "model_prompt_tokens",
                "model_completion_tokens",
                "model_total_tokens",
                "model_response_id",
            }
            model_optional_keys = {"model_request_id"}
            model_keys_present = set(payload) & (
                model_required_keys | model_optional_keys
            )
            has_model_calls = "model_calls" in payload
            if has_model_calls and model_keys_present:
                raise InterruptedNodeExecutionError(
                    "node outcome cannot mix legacy and canonical model call evidence",
                    execution_id=record.execution_id,
                )
            if model_keys_present:
                expected_keys.update(model_required_keys)
                if "model_request_id" in payload:
                    expected_keys.add("model_request_id")
            if has_model_calls:
                expected_keys.add("model_calls")
            if set(payload) != expected_keys or open_started is None or open_tool is not None:
                raise InterruptedNodeExecutionError(
                    "node outcome ledger is malformed or has no matching start",
                    execution_id=record.execution_id,
                )
            if has_model_calls:
                raw_model_calls = payload["model_calls"]
                if type(raw_model_calls) is not list or not raw_model_calls:
                    raise InterruptedNodeExecutionError(
                        "model_calls must be a non-empty list",
                        execution_id=record.execution_id,
                    )
                try:
                    model_calls = tuple(
                        ModelCallMetadata.model_validate(item)
                        for item in raw_model_calls
                    )
                except (TypeError, ValueError, ValidationError) as exc:
                    raise InterruptedNodeExecutionError(
                        "model_calls contains invalid metadata",
                        execution_id=record.execution_id,
                    ) from exc
                response_ids = tuple(call.response_id for call in model_calls)
                if len(set(response_ids)) != len(response_ids):
                    raise InterruptedNodeExecutionError(
                        "model_calls contains duplicate response IDs",
                        execution_id=record.execution_id,
                    )
            if model_keys_present:
                provider_id = self._ledger_string(
                    payload["model_provider"], field="model_provider"
                )
                model_name = self._ledger_string(payload["model_name"], field="model_name")
                prompt_tokens = self._ledger_integer(
                    payload["model_prompt_tokens"],
                    field="model_prompt_tokens",
                    minimum=0,
                )
                completion_tokens = self._ledger_integer(
                    payload["model_completion_tokens"],
                    field="model_completion_tokens",
                    minimum=0,
                )
                total_tokens = self._ledger_integer(
                    payload["model_total_tokens"],
                    field="model_total_tokens",
                    minimum=0,
                )
                response_id = self._ledger_string(
                    payload["model_response_id"],
                    field="model_response_id",
                )
                request_id = None
                if "model_request_id" in payload:
                    request_id = self._ledger_string(
                        payload["model_request_id"],
                        field="model_request_id",
                    )
                try:
                    ModelCallMetadata(
                        provider_id=provider_id,
                        model_name=model_name,
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        total_tokens=total_tokens,
                        request_id=request_id,
                        response_id=response_id,
                    )
                except (TypeError, ValueError, ValidationError) as exc:
                    raise InterruptedNodeExecutionError(
                        "legacy model call metadata is invalid",
                        execution_id=record.execution_id,
                    ) from exc
            node_id = self._ledger_string(payload["node_id"], field="node_id")
            attempt = self._ledger_integer(payload["attempt"], field="attempt", minimum=1)
            input_digest = self._ledger_digest(payload["input_digest"])
            node_type = self._ledger_string(payload["node_type"], field="node_type")
            fencing_token = self._ledger_integer(
                payload["fencing_token"],
                field="fencing_token",
                minimum=1,
            )
            if (
                node_id,
                attempt,
                input_digest,
                node_type,
                fencing_token,
            ) != open_started[:5]:
                raise InterruptedNodeExecutionError(
                    "node outcome does not match its start event",
                    execution_id=record.execution_id,
                    node_id=node_id,
                )
            next_id = self._ledger_string(payload["next_id"], field="next_id")
            node = nodes[node_id]
            required_next = node.on_failure if failed else node.on_success
            if next_id != required_next or (
                next_id not in nodes and next_id not in terminals
            ):
                raise InterruptedNodeExecutionError(
                    "node outcome does not follow its declared edge",
                    execution_id=record.execution_id,
                    node_id=node_id,
                )
            output_digest = self._ledger_digest(payload["output_digest"])
            self._storage.load_payload(
                record.execution_id,
                output_digest,
                lock=lock,
            )
            target_revision = self._ledger_integer(
                payload["record_revision"],
                field="record_revision",
                minimum=1,
            )
            if target_revision <= last_record_revision:
                raise InterruptedNodeExecutionError(
                    "node outcome revisions must increase strictly",
                    execution_id=record.execution_id,
                    node_id=node_id,
                )
            retryable = False
            if failed:
                self._ledger_string(payload["error_code"], field="error_code")
                if type(payload["retryable"]) is not bool:
                    raise InterruptedNodeExecutionError(
                        "retryable must be an exact bool",
                        execution_id=record.execution_id,
                        node_id=node_id,
                    )
                retryable = payload["retryable"]

            next_retry_context = None
            next_retry_context_digest = None
            if "next_retry_context_digest" in payload:
                next_retry_context_digest = self._ledger_digest(
                    payload["next_retry_context_digest"]
                )
                next_retry_context = self._load_retry_context(
                    record.execution_id,
                    next_retry_context_digest,
                    nodes=nodes,
                    lock=lock,
                )
            next_attempt = (
                attempt + 1
                if next_id == node_id
                else attempts.get(next_id, 0) + 1
            )
            consumed_retry_context = open_started[6]
            if failed and retryable and next_id in nodes:
                if (
                    next_retry_context is None
                    or next_retry_context.origin_node_id != node_id
                    or next_retry_context.current_attempt != next_attempt
                ):
                    raise RetryContextIntegrityError(
                        "retryable failure did not publish its exact next context",
                        execution_id=record.execution_id,
                        node_id=node_id,
                    )
            elif (
                not failed
                and consumed_retry_context is not None
                and node_id != consumed_retry_context.origin_node_id
                and next_id in nodes
            ):
                expected_propagated_context = consumed_retry_context.model_copy(
                    update={"current_attempt": next_attempt}
                )
                if next_retry_context != expected_propagated_context:
                    raise RetryContextIntegrityError(
                        "correction path did not propagate the exact retry context",
                        execution_id=record.execution_id,
                        node_id=node_id,
                    )
            elif next_retry_context is not None:
                raise RetryContextIntegrityError(
                    "node outcome published an unexpected retry context",
                    execution_id=record.execution_id,
                    node_id=node_id,
                )
            attempts[node_id] = attempt
            expected_node_id = next_id
            expected_payload_digest = output_digest
            expected_retry_context = next_retry_context
            expected_retry_context_digest = next_retry_context_digest
            last_record_revision = target_revision
            last_fencing_token = fencing_token
            open_started = None
            if target_revision > record.revision:
                if pending is not None or target_revision != record.revision + 1:
                    raise InterruptedNodeExecutionError(
                        "node ledger contains an invalid pending outcome",
                        execution_id=record.execution_id,
                        node_id=node_id,
                    )
                pending = (event, node_id, attempt, next_id)

        if open_started is not None:
            raise InterruptedNodeExecutionError(
                "node started without a durable outcome; intervention is required",
                execution_id=record.execution_id,
                node_id=open_started[0],
            )
        for node_id, attempt in attempts.items():
            recorded_attempt = record.attempt_by_node.get(node_id, 0)
            if pending is not None and node_id == pending[1]:
                if recorded_attempt not in {attempt - 1, attempt}:
                    raise InterruptedNodeExecutionError(
                        "pending node attempt diverges from the snapshot",
                        execution_id=record.execution_id,
                        node_id=node_id,
                    )
            elif recorded_attempt != attempt:
                raise InterruptedNodeExecutionError(
                    "committed node attempts diverge from the snapshot",
                    execution_id=record.execution_id,
                    node_id=node_id,
                )

        if pending_repair is not None:
            if pending is not None or record.current_state != ExecutionState.EXECUTING:
                raise InterruptedNodeExecutionError(
                    "pending verification repair conflicts with graph progress",
                    execution_id=record.execution_id,
                )
            event, target_node_id = pending_repair
            document = record.model_dump(mode="python")
            document.update(
                {
                    "revision": event.payload["record_revision"],
                    "current_node_id": target_node_id,
                    "updated_at": event.timestamp,
                }
            )
            record = self._storage.compare_and_set_execution(
                record.execution_id,
                record.revision,
                ExecutionRecord.model_validate(document),
                lock=lock,
            )

        if pending is not None:
            event, node_id, attempt, next_id = pending
            if record.current_node_id != node_id:
                raise InterruptedNodeExecutionError(
                    "pending outcome does not continue from the snapshot node",
                    execution_id=record.execution_id,
                    node_id=node_id,
                )
            replacement = self._next_record(
                record,
                next_id=next_id,
                node_id=node_id,
                attempt=attempt,
                updated_at=event.timestamp,
            )
            record = self._storage.compare_and_set_execution(
                record.execution_id,
                record.revision,
                replacement,
                lock=lock,
            )
        if record.current_node_id != expected_node_id:
            raise InterruptedNodeExecutionError(
                "node ledger does not reproduce the snapshot current node",
                execution_id=record.execution_id,
                node_id=record.current_node_id,
            )
        return (
            self._storage.load_payload(
                record.execution_id,
                expected_payload_digest,
                lock=lock,
            ),
            expected_retry_context,
            expected_retry_context_digest,
        )

    def _load_retry_context(
        self,
        execution_id: str,
        digest: str,
        *,
        nodes: Mapping[str, NodeSpec],
        lock: ExecutionLock,
    ) -> RetryContext:
        if not isinstance(self._storage, ResumeStateStorageProvider):
            raise RetryContextIntegrityError(
                "retry context storage is unavailable",
                execution_id=execution_id,
            )
        document = self._storage.load_payload(execution_id, digest, lock=lock)
        try:
            context = RetryContext.model_validate(document)
        except (TypeError, ValueError, ValidationError) as exc:
            raise RetryContextIntegrityError(
                "stored retry context violates its strict contract",
                execution_id=execution_id,
            ) from exc
        if context.origin_node_id not in nodes:
            raise RetryContextIntegrityError(
                "stored retry context origin is absent from the artifact",
                execution_id=execution_id,
                node_id=context.origin_node_id,
            )
        text_fields = [
            context.model_error,
            context.redacted_stdout,
            context.redacted_stderr,
            *context.failed_gates,
            context.current_diff,
            context.correction_instruction,
        ]
        if context.failed_tool_call is not None:
            text_fields.extend(
                [
                    context.failed_tool_call.tool_name,
                    context.failed_tool_call.call_id,
                    context.failed_tool_call.error_code,
                ]
            )
        if any(
            value is not None and Redactor.redact_text(value) != value
            for value in text_fields
        ):
            raise RetryContextIntegrityError(
                "stored retry context contains unredacted evidence",
                execution_id=execution_id,
                node_id=context.origin_node_id,
            )
        return context

    @staticmethod
    def _latest_node_input_digest(
        events: tuple[ExecutionEvent, ...],
        *,
        target_node_id: str,
        execution_id: str,
    ) -> str:
        for event in reversed(events):
            if (
                event.event_type == "NODE_STARTED"
                and event.payload.get("node_id") == target_node_id
            ):
                try:
                    return GraphExecutor._ledger_digest(event.payload.get("input_digest"))
                except InterruptedNodeExecutionError as exc:
                    raise RetryContextIntegrityError(
                        "correction node input digest is invalid",
                        execution_id=execution_id,
                        node_id=target_node_id,
                    ) from exc
        raise RetryContextIntegrityError(
            "correction node has no durable prior input",
            execution_id=execution_id,
            node_id=target_node_id,
        )

    @staticmethod
    def _ledger_string(value: object, *, field: str) -> str:
        if type(value) is not str or not value.strip() or value != value.strip():
            raise InterruptedNodeExecutionError(
                f"{field} must be a non-empty trimmed string"
            )
        return value

    @staticmethod
    def _ledger_integer(value: object, *, field: str, minimum: int) -> int:
        if type(value) is not int or value < minimum:
            raise InterruptedNodeExecutionError(
                f"{field} must be an integer greater than or equal to {minimum}"
            )
        return value

    @staticmethod
    def _ledger_digest(value: object) -> str:
        digest = GraphExecutor._ledger_string(value, field="digest")
        if len(digest) != 71 or not digest.startswith("sha256:"):
            raise InterruptedNodeExecutionError("digest must be sha256-prefixed")
        try:
            int(digest[7:], 16)
        except ValueError as exc:
            raise InterruptedNodeExecutionError(
                "digest must contain lowercase hexadecimal"
            ) from exc
        if digest[7:] != digest[7:].lower():
            raise InterruptedNodeExecutionError(
                "digest must contain lowercase hexadecimal"
            )
        return digest

    @staticmethod
    def _next_record(
        record: ExecutionRecord,
        *,
        next_id: str,
        node_id: str,
        attempt: int,
        updated_at: datetime,
    ) -> ExecutionRecord:
        attempts = dict(record.attempt_by_node)
        attempts[node_id] = attempt
        document = record.model_dump(mode="python")
        document.update(
            {
                "revision": record.revision + 1,
                "current_node_id": next_id,
                "attempt_by_node": attempts,
                "updated_at": updated_at,
            }
        )
        return ExecutionRecord.model_validate(document)

    @staticmethod
    def _validate_execution_identity(
        record: ExecutionRecord,
        artifact: CompiledGraphArtifact,
    ) -> None:
        artifact_digest = "sha256:" + hashlib.sha256(
            artifact.canonical_json().encode("utf-8")
        ).hexdigest()
        if (
            record.workflow_name != artifact.graph.graph.name
            or record.artifact_digest != artifact_digest
        ):
            raise ArtifactExecutionMismatchError(
                "execution record does not match the compiled artifact identity",
                execution_id=record.execution_id,
                node_id=record.current_node_id,
            )

    @staticmethod
    def _detach_artifact(
        artifact: CompiledGraphArtifact,
        *,
        execution_id: str,
    ) -> CompiledGraphArtifact:
        if not isinstance(artifact, CompiledGraphArtifact):
            raise ArtifactExecutionMismatchError(
                "artifact must be a CompiledGraphArtifact",
                execution_id=execution_id,
            )
        try:
            return CompiledGraphArtifact.model_validate_json(artifact.canonical_json())
        except (TypeError, ValueError, ValidationError) as exc:
            raise ArtifactExecutionMismatchError(
                "compiled artifact failed integrity validation",
                execution_id=execution_id,
            ) from exc

    def _next_timestamp(
        self,
        minimum: datetime,
        *,
        execution_id: str,
        node_id: str,
    ) -> datetime:
        observed = self._clock()
        if (
            not isinstance(observed, datetime)
            or observed.tzinfo is None
            or observed.utcoffset() is None
            or observed.utcoffset() != timedelta(0)
            or observed < minimum
        ):
            raise GraphClockError(
                "graph clock must be UTC and cannot regress durable time",
                execution_id=execution_id,
                node_id=node_id,
            )
        return observed.astimezone(UTC)

    def _validate_node_input(
        self,
        artifact: CompiledGraphArtifact,
        node: NodeSpec,
        payload: dict[str, object],
        execution_id: str,
    ) -> None:
        if not isinstance(node, AgentNodeSpec):
            return
        contract = self._contract_for(artifact, node.input_contract, execution_id, node.id)
        self._validate_schema(
            contract,
            payload,
            error_type=NodeInputValidationError,
            execution_id=execution_id,
            node_id=node.id,
        )

    def _validate_node_output(
        self,
        artifact: CompiledGraphArtifact,
        node: NodeSpec,
        payload: dict[str, object],
        execution_id: str,
    ) -> None:
        if not isinstance(node, AgentNodeSpec):
            return
        contract = self._contract_for(artifact, node.output_contract, execution_id, node.id)
        self._validate_schema(
            contract,
            payload,
            error_type=NodeOutputValidationError,
            execution_id=execution_id,
            node_id=node.id,
        )

    @staticmethod
    def _contract_for(
        artifact: CompiledGraphArtifact,
        reference: str,
        execution_id: str,
        node_id: str,
    ) -> ResolvedContractSpec:
        matches = tuple(
            contract
            for contract in artifact.resolved_contracts
            if contract.requested_reference == reference
        )
        if len(matches) != 1:
            raise NodeContractNotFoundError(
                f"contract reference {reference!r} is absent or ambiguous",
                execution_id=execution_id,
                node_id=node_id,
            )
        return matches[0]

    @staticmethod
    def _validate_schema(
        contract: ResolvedContractSpec,
        payload: Mapping[str, object],
        *,
        error_type: type[GraphExecutionError],
        execution_id: str,
        node_id: str,
    ) -> None:
        try:
            contract.verify_integrity()
            validate_json_schema(instance=payload, schema=contract.contract_schema)
        except (JsonSchemaError, JsonValidationError, ValueError) as exc:
            raise error_type(
                "node payload does not satisfy its declared contract",
                execution_id=execution_id,
                node_id=node_id,
            ) from exc


__all__ = [
    "VERIFICATION_REPAIR_SCHEDULED",
    "ApprovalPauseHandler",
    "ArtifactExecutionMismatchError",
    "GraphClockError",
    "GraphCycleExecutionError",
    "GraphEventConstructionError",
    "GraphExecutionError",
    "GraphExecutionPausedResult",
    "GraphExecutionResult",
    "GraphExecutor",
    "InterruptedNodeExecutionError",
    "NodeContractNotFoundError",
    "NodeInputValidationError",
    "NodeOutputValidationError",
    "RetryContextIntegrityError",
    "RetryExhaustedError",
    "UnknownCurrentNodeError",
    "VerificationRepairRequest",
]
