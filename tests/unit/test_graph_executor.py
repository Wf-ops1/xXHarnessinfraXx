"""Focused F2.3 tests for canonical graph traversal and fail-closed boundaries."""

from __future__ import annotations

import hashlib
import json
import multiprocessing
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from queue import Empty

import pytest

from ai_engineering_harness.contracts import (
    AgentNodeSpec,
    CompiledGraphArtifact,
    DeterministicNodeSpec,
    GraphSpec,
    HumanApprovalNodeSpec,
    ResolvedContractSpec,
    SourceManifestEntry,
    TerminalStateSpec,
)
from ai_engineering_harness.contracts.events import ExecutionEvent
from ai_engineering_harness.contracts.execution import (
    ApprovalStatus,
    ExecutionRecord,
    ExecutionState,
)
from ai_engineering_harness.governance import (
    PolicyEngine,
    ToolPolicyDecision,
    ToolPolicyRequest,
    ToolPolicyRule,
)
from ai_engineering_harness.persistence import (
    AtomicFileStateStorage,
    EventJournalStateStorageProvider,
    ExecutionBundle,
    ExecutionBundleIntegrityError,
    ExecutionLock,
    StateStorageProvider,
    StateWriteError,
    canonical_json_digest,
    canonical_json_object,
)
from ai_engineering_harness.runtime import (
    AgentNodeExecutor,
    ArtifactExecutionMismatchError,
    DeterministicNodeExecutor,
    EventSourcedStateMachine,
    FailedToolCall,
    GraphCycleExecutionError,
    GraphExecutor,
    HumanApprovalNodeExecutor,
    InterruptedExecutionError,
    InterruptedNodeExecutionError,
    KnowledgeSyncNodeExecutor,
    ModelCallMetadata,
    NodeBackendError,
    NodeExecutionContext,
    NodeExecutionResult,
    NodeExecutorRegistry,
    NodeExecutorUnavailableError,
    NodeInputValidationError,
    RetryBudget,
    RetryContext,
    RetryEvidence,
    RetryExhaustedError,
    StateReplayError,
    StateTransitionIntegrityError,
    TerminalNodeExecutor,
    ToolCallIntent,
    ToolEffectAmbiguousError,
    ToolEffectDurabilityError,
    ToolEffectIntegrityError,
    ToolExecutionRecord,
    UnknownCurrentNodeError,
)

_BASE_TIME = datetime(2020, 1, 1, 0, 0, tzinfo=UTC)
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
        return f"event-{self.value}"


@dataclass
class _TraceBackend:
    trace: list[str]
    fail_node: str | None = None
    invalid_output_node: str | None = None
    raise_node: str | None = None

    def execute(self, context: NodeExecutionContext) -> NodeExecutionResult:
        node_id = context.node.id
        self.trace.append(node_id)
        if node_id == self.raise_node:
            raise NodeBackendError(
                "backend_rejected",
                "backend rejected the node",
                retryable=False,
            )
        if node_id == self.invalid_output_node:
            return NodeExecutionResult.completed({"result": 42})
        previous = context.input_payload.get("trace", [])
        assert isinstance(previous, list)
        output = {"trace": [*previous, node_id]}
        if node_id == self.fail_node:
            return NodeExecutionResult.failed(
                output,
                code="controlled_failure",
                message="controlled node failure",
                retryable=False,
            )
        return NodeExecutionResult.completed(output)


_RETRY_SECRET = "token=f2-six-secret-value"


def _retry_evidence() -> RetryEvidence:
    return RetryEvidence(
        model_error=f"model rejected change with {_RETRY_SECRET}",
        failed_tool_call=FailedToolCall(
            tool_name="terminal",
            call_id="call-retry-1",
            arguments_digest=f"sha256:{'1' * 64}",
            error_code="exit-1",
        ),
        stdout=f"tests started {_RETRY_SECRET}",
        stderr=f"assertion failed {_RETRY_SECRET}",
        failed_gates=("pytest",),
        current_diff=f"+ leaked {_RETRY_SECRET}",
        remaining_budget=RetryBudget(
            remaining_tokens=900,
            remaining_cost_usd=4.5,
        ),
        correction_instruction=f"fix the failing assertion; remove {_RETRY_SECRET}",
    )


@dataclass
class _RetryBackend:
    trace: list[tuple[str, int, RetryContext | None]]
    fail_attempts: dict[str, set[int]]

    def execute(self, context: NodeExecutionContext) -> NodeExecutionResult:
        self.trace.append((context.node.id, context.attempt, context.retry_context))
        previous = context.input_payload.get("trace", [])
        assert isinstance(previous, list)
        output: dict[str, object] = {
            "trace": [*previous, f"{context.node.id}:{context.attempt}"]
        }
        if context.attempt in self.fail_attempts.get(context.node.id, set()):
            return NodeExecutionResult.failed(
                output,
                code="retryable_gate_failure",
                message="gate failed with redaction-safe summary",
                retryable=True,
                retry_evidence=_retry_evidence(),
            )
        return NodeExecutionResult.completed(output)


@dataclass
class _MarkerBackend:
    marker: Path

    def execute(self, context: NodeExecutionContext) -> NodeExecutionResult:
        with self.marker.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(f"{context.node.id}\n")
            stream.flush()
        return NodeExecutionResult.completed({"worker": context.node.id})


@dataclass
class _StaticBackend:
    result: object

    def execute(self, context: NodeExecutionContext) -> object:
        return self.result


@dataclass
class _DurableStaticBackend:
    result: NodeExecutionResult
    trace: list[str] | None = None
    executions: int = 0
    policy_decision: ToolPolicyDecision | None = None

    def execute(self, context: NodeExecutionContext) -> NodeExecutionResult:
        self.executions += 1
        recorder = context.tool_effect_recorder
        assert recorder is not None
        for record in self.result.tool_executions:
            decision = self.policy_decision or _allowed_tool_decision(context.artifact)
            recorder.record_call(
                ToolCallIntent(
                    step=record.step,
                    call_id=record.call_id,
                    tool_name=record.tool_name,
                    arguments_digest=record.arguments_digest,
                    policy_decision=decision,
                )
            )
            if self.trace is not None:
                self.trace.append("effect")
            recorder.record_outcome(record)
        return self.result


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
                "controlled node outcome CAS failure",
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
                "controlled node outcome append interruption",
                execution_id=execution_id,
            )
        return super().append_event(execution_id, event, lock=lock)


class _ModelEventShapeStorage(AtomicFileStateStorage):
    def __init__(self, project_root: Path, *, mode: str) -> None:
        super().__init__(project_root)
        self.mode = mode

    def append_event(
        self,
        execution_id: str,
        event: ExecutionEvent,
        *,
        lock: ExecutionLock | None = None,
    ) -> ExecutionEvent:
        model_calls = event.payload.get("model_calls")
        if event.event_type in {"NODE_COMPLETED", "NODE_FAILED"} and isinstance(
            model_calls, list
        ):
            assert len(model_calls) == 1
            call = model_calls[0]
            assert isinstance(call, dict)
            legacy = {
                "model_provider": call["provider_id"],
                "model_name": call["model_name"],
                "model_prompt_tokens": call["prompt_tokens"],
                "model_completion_tokens": call["completion_tokens"],
                "model_total_tokens": call["total_tokens"],
                "model_response_id": call["response_id"],
            }
            if call["request_id"] is not None:
                legacy["model_request_id"] = call["request_id"]
            payload = dict(event.payload)
            if self.mode == "legacy":
                payload.pop("model_calls")
            payload.update(legacy)
            event = ExecutionEvent.model_validate(
                {
                    **event.model_dump(),
                    "payload": payload,
                    "previous_hash": None,
                    "current_hash": None,
                }
            )
        return super().append_event(execution_id, event, lock=lock)


class _TamperedToolDecisionStorage(_FailOutcomeCasStorage):
    def append_event(
        self,
        execution_id: str,
        event: ExecutionEvent,
        *,
        lock: ExecutionLock | None = None,
    ) -> ExecutionEvent:
        if event.event_type == "TOOL_COMPLETED" and "policy_decision_digest" in event.payload:
            event = ExecutionEvent.model_validate(
                {
                    **event.model_dump(),
                    "payload": {
                        **event.payload,
                        "policy_decision_digest": f"sha256:{'f' * 64}",
                    },
                    "previous_hash": None,
                    "current_hash": None,
                }
            )
        return super().append_event(execution_id, event, lock=lock)


class _LegacyToolEventStorage(_FailOutcomeCasStorage):
    def append_event(
        self,
        execution_id: str,
        event: ExecutionEvent,
        *,
        lock: ExecutionLock | None = None,
    ) -> ExecutionEvent:
        payload = dict(event.payload)
        if event.event_type == "TOOL_CALLED":
            payload.pop("policy_decision")
        elif event.event_type in {"TOOL_COMPLETED", "TOOL_FAILED"}:
            payload.pop("policy_decision_digest")
        if payload != event.payload:
            event = ExecutionEvent.model_validate(
                {
                    **event.model_dump(),
                    "payload": payload,
                    "previous_hash": None,
                    "current_hash": None,
                }
            )
        return super().append_event(execution_id, event, lock=lock)


class _FailToolOutcomeAppendStorage(AtomicFileStateStorage):
    def append_event(
        self,
        execution_id: str,
        event: ExecutionEvent,
        *,
        lock: ExecutionLock | None = None,
    ) -> ExecutionEvent:
        if event.event_type == "TOOL_COMPLETED":
            raise StateWriteError(
                "controlled tool outcome append interruption",
                execution_id=execution_id,
            )
        return super().append_event(execution_id, event, lock=lock)


class _FailToolCallAppendStorage(AtomicFileStateStorage):
    def append_event(
        self,
        execution_id: str,
        event: ExecutionEvent,
        *,
        lock: ExecutionLock | None = None,
    ) -> ExecutionEvent:
        if event.event_type == "TOOL_CALLED":
            raise StateWriteError(
                "controlled tool call append interruption",
                execution_id=execution_id,
            )
        return super().append_event(execution_id, event, lock=lock)


class _TracingToolStorage(AtomicFileStateStorage):
    def __init__(self, project_root: Path, trace: list[str]) -> None:
        super().__init__(project_root)
        self.trace = trace

    def append_event(
        self,
        execution_id: str,
        event: ExecutionEvent,
        *,
        lock: ExecutionLock | None = None,
    ) -> ExecutionEvent:
        if event.event_type.startswith("TOOL_"):
            self.trace.append(event.event_type)
        return super().append_event(execution_id, event, lock=lock)


class _FailSecondNodeStartStorage(AtomicFileStateStorage):
    def __init__(self, project_root: Path) -> None:
        super().__init__(project_root)
        self.started_count = 0
        self.fail_second_start = True

    def append_event(
        self,
        execution_id: str,
        event: ExecutionEvent,
        *,
        lock: ExecutionLock | None = None,
    ) -> ExecutionEvent:
        if event.event_type == "NODE_STARTED":
            self.started_count += 1
            if self.fail_second_start and self.started_count == 2:
                self.fail_second_start = False
                raise StateWriteError(
                    "controlled interruption before retry start",
                    execution_id=execution_id,
                )
        return super().append_event(execution_id, event, lock=lock)


class _FailingStorage:
    def __init__(
        self,
        inner: AtomicFileStateStorage,
        *,
        fail_append_number: int | None = None,
        fail_cas: bool = False,
    ) -> None:
        self.inner = inner
        self.fail_append_number = fail_append_number
        self.fail_cas = fail_cas
        self.append_count = 0

    def create_execution(self, record: ExecutionRecord) -> ExecutionRecord:
        return self.inner.create_execution(record)

    def load_execution(
        self,
        execution_id: str,
        *,
        lock: ExecutionLock | None = None,
    ) -> ExecutionRecord:
        return self.inner.load_execution(execution_id, lock=lock)

    def compare_and_set_execution(
        self,
        execution_id: str,
        expected_revision: int,
        replacement: ExecutionRecord,
        *,
        lock: ExecutionLock | None = None,
    ) -> ExecutionRecord:
        if self.fail_cas:
            raise StateWriteError("controlled CAS failure", execution_id=execution_id)
        return self.inner.compare_and_set_execution(
            execution_id,
            expected_revision,
            replacement,
            lock=lock,
        )

    def append_event(
        self,
        execution_id: str,
        event: ExecutionEvent,
        *,
        lock: ExecutionLock | None = None,
    ) -> ExecutionEvent:
        self.append_count += 1
        if self.append_count == self.fail_append_number:
            raise StateWriteError("controlled append failure", execution_id=execution_id)
        return self.inner.append_event(execution_id, event, lock=lock)

    def load_events(
        self,
        execution_id: str,
        *,
        lock: ExecutionLock | None = None,
    ) -> tuple[ExecutionEvent, ...]:
        return self.inner.load_events(execution_id, lock=lock)

    def list_executions(self) -> tuple[ExecutionRecord, ...]:
        return self.inner.list_executions()

    def acquire_execution_lock(
        self,
        execution_id: str,
        owner_id: str,
        *,
        timeout_seconds: float,
    ) -> ExecutionLock:
        return self.inner.acquire_execution_lock(
            execution_id,
            owner_id,
            timeout_seconds=timeout_seconds,
        )

    def release_execution_lock(self, lock: ExecutionLock) -> None:
        self.inner.release_execution_lock(lock)


def _artifact(
    nodes: list[dict[str, object]],
    *,
    name: str = "test-graph",
    entrypoint: str | None = None,
    contracts: tuple[ResolvedContractSpec, ...] = (),
) -> CompiledGraphArtifact:
    graph = GraphSpec.model_validate(
        {
            "graph": {
                "name": name,
                "graph_schema_version": "1.0",
                "definition_version": "1.0.0",
                "entrypoint": entrypoint or str(nodes[0]["id"]),
                "status": "stable",
            },
            "nodes": nodes,
            "terminal_states": [
                {"id": "completed", "outcome": "success"},
                {"id": "failed", "outcome": "failure"},
            ],
            "policies": [],
            "contracts": [],
        }
    )
    return CompiledGraphArtifact.build(
        graph=graph,
        resolved_contracts=contracts,
        resolved_policies=(),
        source_manifest=(
            SourceManifestEntry(
                source_kind="graph",
                source_id="project://graph.yaml",
                content_digest=_ZERO_DIGEST,
            ),
        ),
    )


def _deterministic_node(
    node_id: str,
    on_success: str,
    *,
    on_failure: str = "failed",
    retry_policy: dict[str, object] | None = None,
) -> dict[str, object]:
    node: dict[str, object] = {
        "id": node_id,
        "type": "deterministic",
        "executor": "deterministic_gate",
        "gate_name": node_id,
        "on_success": on_success,
        "on_failure": on_failure,
    }
    if retry_policy is not None:
        node["retry_policy"] = retry_policy
    return node


def _resolved_contract(reference: str, schema: dict[str, object]) -> ResolvedContractSpec:
    canonical = json.dumps(
        schema,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return ResolvedContractSpec(
        canonical_name=reference,
        requested_reference=reference,
        source="json_schema",
        contract_schema=schema,
        digest=f"sha256:{hashlib.sha256(canonical).hexdigest()}",
    )


def _agent_artifact() -> CompiledGraphArtifact:
    input_ref = "jsonschema:input.json"
    output_ref = "jsonschema:output.json"
    return _artifact(
        [
            {
                "id": "agent",
                "type": "agent",
                "role": "code_agent",
                "input_contract": input_ref,
                "output_contract": output_ref,
                "on_success": "completed",
                "on_failure": "failed",
            }
        ],
        contracts=(
            _resolved_contract(
                input_ref,
                {
                    "$schema": "https://json-schema.org/draft/2020-12/schema",
                    "type": "object",
                    "properties": {"value": {"type": "integer"}},
                    "required": ["value"],
                    "additionalProperties": False,
                },
            ),
            _resolved_contract(
                output_ref,
                {
                    "$schema": "https://json-schema.org/draft/2020-12/schema",
                    "type": "object",
                    "properties": {"result": {"type": "string"}},
                    "required": ["result"],
                    "additionalProperties": False,
                },
            ),
        ),
    )


def _allowed_tool_decision(artifact: CompiledGraphArtifact) -> ToolPolicyDecision:
    request = ToolPolicyRequest(
        role="code_agent",
        node_id="agent",
        workflow=artifact.graph.graph.name,
        trust_mode="restricted",
        tool="knowledge_retriever",
        operation="read",
        path="docs/context.json",
    )
    engine = PolicyEngine(
        rules=(
            ToolPolicyRule(
                rule_id="compiled:test-agent:knowledge_retriever",
                effect="allow",
                roles=(request.role,),
                node_ids=(request.node_id,),
                workflows=(request.workflow,),
                trust_modes=(request.trust_mode,),
                tools=(request.tool,),
                operations=(request.operation,),
                path_patterns=("docs/*",),
            ),
        )
    )
    return engine.evaluate(request)


def _record(
    artifact: CompiledGraphArtifact,
    execution_id: str,
    *,
    current_node_id: str | None = None,
    artifact_digest: str | None = None,
) -> ExecutionRecord:
    digest = artifact_digest or (
        "sha256:"
        + hashlib.sha256(artifact.canonical_json().encode("utf-8")).hexdigest()
    )
    return ExecutionRecord(
        record_schema_version="1.0",
        revision=0,
        execution_id=execution_id,
        workflow_name=artifact.graph.graph.name,
        artifact_digest=digest,
        base_commit_sha="a" * 40,
        original_branch="test",
        worktree_path=None,
        current_node_id=current_node_id or artifact.graph.graph.entrypoint,
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


def _executor(
    storage: EventJournalStateStorageProvider,
    registry: NodeExecutorRegistry,
) -> GraphExecutor:
    return GraphExecutor(
        storage,
        registry,
        lock_timeout_seconds=5,
        clock=_Clock(),
        event_id_factory=_EventIds(),
        owner_id_factory=lambda: "unit-test-worker",
    )


def _resume_executor(
    storage: AtomicFileStateStorage,
    registry: NodeExecutorRegistry,
) -> GraphExecutor:
    return GraphExecutor(
        storage,
        registry,
        resume_enabled=True,
        lock_timeout_seconds=5,
        clock=_Clock(),
        event_id_factory=_EventIds(),
        owner_id_factory=lambda: "resume-unit-test-worker",
    )


def _create_resume_execution(
    storage: AtomicFileStateStorage,
    artifact: CompiledGraphArtifact,
    execution_id: str,
    initial_input: dict[str, object],
) -> None:
    artifact_json = artifact.canonical_json()
    configuration_json = canonical_json_object({})
    initial_json = canonical_json_object(initial_input)
    bundle = ExecutionBundle(
        bundle_schema_version="1.0",
        execution_id=execution_id,
        artifact_digest=canonical_json_digest(artifact_json),
        configuration_digest=canonical_json_digest(configuration_json),
        initial_input_digest=canonical_json_digest(initial_json),
        artifact_json=artifact_json,
        configuration_json=configuration_json,
    )
    storage.create_execution_bundle(bundle, initial_input=initial_input)
    record = _record(artifact, execution_id).model_copy(
        update={"configuration_digest": bundle.configuration_digest}
    )
    storage.create_execution(record)


def _journal(root: Path, execution_id: str) -> list[dict[str, object]]:
    path = (
        root
        / ".harness"
        / "state"
        / "executions"
        / execution_id
        / "event-journal.jsonl"
    )
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _multiprocess_execute(
    project_root: str,
    artifact_json: str,
    execution_id: str,
    marker: str,
    start_event: object,
    result_queue: object,
) -> None:
    start_event.wait(10)
    artifact = CompiledGraphArtifact.model_validate_json(artifact_json)
    storage = AtomicFileStateStorage(Path(project_root))
    backend = _MarkerBackend(Path(marker))
    executor = GraphExecutor(
        storage,
        NodeExecutorRegistry(
            deterministic=DeterministicNodeExecutor(backend),
        ),
        lock_timeout_seconds=10,
    )
    result = executor.execute(artifact, execution_id, {"worker": "ready"})
    result_queue.put(("ok", result.executed_node_ids, result.fencing_token))


def test_dispatch_selects_all_five_executor_variants() -> None:
    registry = NodeExecutorRegistry()
    agent = AgentNodeSpec(
        id="agent",
        type="agent",
        role="code_agent",
        input_contract="Input",
        output_contract="Output",
        on_success="completed",
        on_failure="failed",
    )
    knowledge = agent.model_copy(update={"id": "knowledge", "role": "knowledge_updater"})
    deterministic = DeterministicNodeSpec(
        id="gate",
        type="deterministic",
        executor="deterministic_gate",
        gate_name="quality",
        on_success="completed",
        on_failure="failed",
    )
    approval = HumanApprovalNodeSpec(
        id="approval",
        type="human_approval",
        approval_strategy="explicit",
        on_success="completed",
        on_failure="failed",
    )
    terminal = TerminalStateSpec(id="completed", outcome="success")

    assert isinstance(registry.select(agent), AgentNodeExecutor)
    assert isinstance(registry.select(knowledge), KnowledgeSyncNodeExecutor)
    assert isinstance(registry.select(deterministic), DeterministicNodeExecutor)
    assert isinstance(registry.select(approval), HumanApprovalNodeExecutor)
    assert isinstance(registry.select(terminal), TerminalNodeExecutor)


def test_linear_execution_persists_events_cas_terminal_and_fencing(tmp_path: Path) -> None:
    artifact = _artifact(
        [
            _deterministic_node("first", "second"),
            _deterministic_node("second", "completed"),
        ]
    )
    storage = AtomicFileStateStorage(tmp_path)
    storage.create_execution(_record(artifact, "exec-linear"))
    trace: list[str] = []
    result = _executor(
        storage,
        NodeExecutorRegistry(
            deterministic=DeterministicNodeExecutor(_TraceBackend(trace)),
        ),
    ).execute(artifact, "exec-linear", {"trace": []})

    assert trace == ["first", "second"]
    assert result.outcome == "success"
    assert result.terminal_id == "completed"
    assert result.executed_node_ids == ("first", "second")
    assert result.final_revision == 4
    assert result.output == {"trace": ["first", "second"]}
    persisted = storage.load_execution("exec-linear")
    assert persisted.current_node_id == "completed"
    assert persisted.revision == 4
    assert persisted.current_state == ExecutionState.COMPLETED
    assert persisted.attempt_by_node == {"first": 1, "second": 1}
    events = _journal(tmp_path, "exec-linear")
    assert [event["event_type"] for event in events] == [
        "STATE_TRANSITIONED",
        "NODE_STARTED",
        "NODE_COMPLETED",
        "NODE_STARTED",
        "NODE_COMPLETED",
        "STATE_TRANSITIONED",
    ]
    assert all(event["payload"]["fencing_token"] == result.fencing_token for event in events)
    assert [event["payload"].get("next_id") for event in events[1:-1]] == [
        None,
        "second",
        None,
        "completed",
    ]
    assert events[0]["payload"]["to_state"] == "EXECUTING"
    assert events[-1]["payload"]["to_state"] == "COMPLETED"


def test_lifecycle_can_defer_success_terminal_to_verifying(tmp_path: Path) -> None:
    artifact = _artifact([_deterministic_node("first", "completed")])
    storage = AtomicFileStateStorage(tmp_path)
    storage.create_execution(_record(artifact, "exec-deferred-verification"))

    result = _executor(
        storage,
        NodeExecutorRegistry(
            deterministic=DeterministicNodeExecutor(_TraceBackend([])),
        ),
    ).execute(
        artifact,
        "exec-deferred-verification",
        {"trace": []},
        defer_completion=True,
    )

    assert result.outcome == "success"
    assert storage.load_execution("exec-deferred-verification").current_state == (
        ExecutionState.VERIFYING
    )
    assert _journal(tmp_path, "exec-deferred-verification")[-1]["payload"] == {
        "attempt": 0,
        "fencing_token": result.fencing_token,
        "from_state": "EXECUTING",
        "node_id": "completed",
        "reason": "graph_ready_for_verification",
        "record_revision": result.final_revision,
        "to_state": "VERIFYING",
    }


def test_valid_input_contract_and_output_contract_complete(tmp_path: Path) -> None:
    artifact = _agent_artifact()
    storage = AtomicFileStateStorage(tmp_path)
    storage.create_execution(_record(artifact, "exec-valid-contracts"))
    result = _executor(
        storage,
        NodeExecutorRegistry(
            agent=AgentNodeExecutor(
                _StaticBackend(NodeExecutionResult.completed({"result": "ok"}))
            )
        ),
    ).execute(artifact, "exec-valid-contracts", {"value": 1})

    assert result.outcome == "success"
    assert result.output == {"result": "ok"}
    assert [event["event_type"] for event in _journal(tmp_path, "exec-valid-contracts")] == [
        "STATE_TRANSITIONED",
        "NODE_STARTED",
        "NODE_COMPLETED",
        "STATE_TRANSITIONED",
    ]


def test_model_metadata_and_usage_are_journaled_only_on_node_outcome(
    tmp_path: Path,
) -> None:
    artifact = _agent_artifact()
    storage = AtomicFileStateStorage(tmp_path)
    execution_id = "exec-model-metadata"
    storage.create_execution(_record(artifact, execution_id))
    metadata = ModelCallMetadata(
        provider_id="openai",
        model_name="server-model",
        prompt_tokens=11,
        completion_tokens=7,
        total_tokens=18,
        request_id="req-123",
        response_id="resp-123",
    )

    _executor(
        storage,
        NodeExecutorRegistry(
            agent=AgentNodeExecutor(
                _StaticBackend(
                    NodeExecutionResult.completed(
                        {"result": "ok"},
                        model_call=metadata,
                    )
                )
            )
        ),
    ).execute(artifact, execution_id, {"value": 1})

    events = _journal(tmp_path, execution_id)
    started = next(event for event in events if event["event_type"] == "NODE_STARTED")
    outcome = next(event for event in events if event["event_type"] == "NODE_COMPLETED")
    assert not any(key.startswith("model_") for key in started["payload"])
    assert {
        key: value
        for key, value in outcome["payload"].items()
        if key.startswith("model_")
    } == {
        "model_calls": [
            {
                "provider_id": "openai",
                "model_name": "server-model",
                "prompt_tokens": 11,
                "completion_tokens": 7,
                "total_tokens": 18,
                "request_id": "req-123",
                "response_id": "resp-123",
            }
        ]
    }
    assert "sensitive prompt" not in json.dumps(events)


def test_all_model_calls_are_journaled_in_order_and_replayed(tmp_path: Path) -> None:
    artifact = _agent_artifact()
    storage = _FailOutcomeCasStorage(tmp_path)
    execution_id = "exec-multi-model-metadata"
    initial_input = {"value": 1}
    _create_resume_execution(storage, artifact, execution_id, initial_input)
    calls = (
        ModelCallMetadata(
            provider_id="openai",
            model_name="model-a",
            prompt_tokens=3,
            completion_tokens=2,
            total_tokens=5,
            request_id="req-a",
            response_id="resp-a",
        ),
        ModelCallMetadata(
            provider_id="local",
            model_name="model-b",
            prompt_tokens=4,
            completion_tokens=1,
            total_tokens=5,
            response_id="resp-b",
        ),
    )
    executor = _resume_executor(
        storage,
        NodeExecutorRegistry(
            agent=AgentNodeExecutor(
                _StaticBackend(
                    NodeExecutionResult.completed(
                        {"result": "ok"},
                        model_calls=calls,
                    )
                )
            )
        ),
    )

    with pytest.raises(StateWriteError, match="outcome CAS"):
        executor.execute(artifact, execution_id, initial_input)
    result = executor.resume(artifact, execution_id)

    assert result.outcome == "success"
    outcome = next(
        event
        for event in storage.load_events(execution_id)
        if event.event_type == "NODE_COMPLETED"
    )
    assert [item["response_id"] for item in outcome.payload["model_calls"]] == [
        "resp-a",
        "resp-b",
    ]


def test_legacy_single_model_call_event_remains_replay_compatible(
    tmp_path: Path,
) -> None:
    artifact = _agent_artifact()
    storage = _ModelEventShapeStorage(tmp_path, mode="legacy")
    execution_id = "exec-legacy-model-metadata"
    initial_input = {"value": 1}
    _create_resume_execution(storage, artifact, execution_id, initial_input)
    metadata = ModelCallMetadata(
        provider_id="openai",
        model_name="legacy-model",
        prompt_tokens=2,
        completion_tokens=1,
        total_tokens=3,
        response_id="legacy-response",
    )
    executor = _resume_executor(
        storage,
        NodeExecutorRegistry(
            agent=AgentNodeExecutor(
                _StaticBackend(
                    NodeExecutionResult.completed(
                        {"result": "ok"},
                        model_call=metadata,
                    )
                )
            )
        ),
    )

    executor.execute(artifact, execution_id, initial_input)
    result = executor.resume(artifact, execution_id)

    assert result.outcome == "success"
    outcome = next(
        event
        for event in storage.load_events(execution_id)
        if event.event_type == "NODE_COMPLETED"
    )
    assert "model_calls" not in outcome.payload
    assert outcome.payload["model_response_id"] == "legacy-response"


def test_replay_rejects_mixed_legacy_and_canonical_model_call_evidence(
    tmp_path: Path,
) -> None:
    artifact = _agent_artifact()
    storage = _ModelEventShapeStorage(tmp_path, mode="mixed")
    execution_id = "exec-mixed-model-metadata"
    initial_input = {"value": 1}
    _create_resume_execution(storage, artifact, execution_id, initial_input)
    metadata = ModelCallMetadata(
        provider_id="openai",
        model_name="mixed-model",
        prompt_tokens=2,
        completion_tokens=1,
        total_tokens=3,
        response_id="mixed-response",
    )
    executor = _resume_executor(
        storage,
        NodeExecutorRegistry(
            agent=AgentNodeExecutor(
                _StaticBackend(
                    NodeExecutionResult.completed(
                        {"result": "ok"},
                        model_call=metadata,
                    )
                )
            )
        ),
    )

    executor.execute(artifact, execution_id, initial_input)
    journal_before = storage.load_events(execution_id)
    with pytest.raises(InterruptedNodeExecutionError, match="cannot mix"):
        executor.resume(artifact, execution_id)

    assert storage.load_events(execution_id) == journal_before


def test_tool_events_are_paired_redacted_and_precede_node_outcome(tmp_path: Path) -> None:
    artifact = _agent_artifact()
    storage = AtomicFileStateStorage(tmp_path)
    execution_id = "exec-tool-events"
    storage.create_execution(_record(artifact, execution_id))
    tool_record = ToolExecutionRecord(
        step=1,
        call_id="call-1",
        tool_name="knowledge_retriever",
        arguments_digest=f"sha256:{'1' * 64}",
        succeeded=True,
        result_digest=f"sha256:{'2' * 64}",
        redacted_result='{"token":"[REDACTED_SECRET]"}',
        policy_decision_digest=_allowed_tool_decision(artifact).digest(),
    )

    _executor(
        storage,
        NodeExecutorRegistry(
            agent=AgentNodeExecutor(
                _DurableStaticBackend(
                    NodeExecutionResult.completed(
                        {"result": "ok"},
                        tool_executions=(tool_record,),
                    )
                )
            )
        ),
    ).execute(artifact, execution_id, {"value": 1})

    events = _journal(tmp_path, execution_id)
    event_types = [event["event_type"] for event in events]
    assert event_types == [
        "STATE_TRANSITIONED",
        "NODE_STARTED",
        "TOOL_CALLED",
        "TOOL_COMPLETED",
        "NODE_COMPLETED",
        "STATE_TRANSITIONED",
    ]
    called = events[2]["payload"]
    completed = events[3]["payload"]
    assert called["arguments_digest"] == f"sha256:{'1' * 64}"
    assert "arguments" not in called
    assert completed["redacted_result"] == '{"token":"[REDACTED_SECRET]"}'
    assert "raw-secret" not in json.dumps(events)


def test_graph_write_ahead_is_persisted_before_effect_and_outcome_after(
    tmp_path: Path,
) -> None:
    artifact = _agent_artifact()
    trace: list[str] = []
    storage = _TracingToolStorage(tmp_path, trace)
    execution_id = "exec-tool-write-ahead-order"
    storage.create_execution(_record(artifact, execution_id))
    tool_record = ToolExecutionRecord(
        step=1,
        call_id="call-order",
        tool_name="knowledge_retriever",
        arguments_digest=f"sha256:{'a' * 64}",
        succeeded=True,
        result_digest=f"sha256:{'b' * 64}",
        redacted_result="ok",
        policy_decision_digest=_allowed_tool_decision(artifact).digest(),
    )
    backend = _DurableStaticBackend(
        NodeExecutionResult.completed(
            {"result": "ok"},
            tool_executions=(tool_record,),
        ),
        trace=trace,
    )

    _executor(
        storage,
        NodeExecutorRegistry(agent=AgentNodeExecutor(backend)),
    ).execute(artifact, execution_id, {"value": 1})

    assert trace == ["TOOL_CALLED", "effect", "TOOL_COMPLETED"]


def test_tool_call_journal_failure_blocks_effect_before_handler(tmp_path: Path) -> None:
    artifact = _agent_artifact()
    trace: list[str] = []
    storage = _FailToolCallAppendStorage(tmp_path)
    execution_id = "exec-tool-call-write-failure"
    storage.create_execution(_record(artifact, execution_id))
    tool_record = ToolExecutionRecord(
        step=1,
        call_id="call-blocked",
        tool_name="knowledge_retriever",
        arguments_digest=f"sha256:{'c' * 64}",
        succeeded=True,
        result_digest=f"sha256:{'d' * 64}",
        redacted_result="must-not-run",
        policy_decision_digest=_allowed_tool_decision(artifact).digest(),
    )
    backend = _DurableStaticBackend(
        NodeExecutionResult.completed(
            {"result": "must-not-run"},
            tool_executions=(tool_record,),
        ),
        trace=trace,
    )

    with pytest.raises(ToolEffectDurabilityError, match="write-ahead"):
        _executor(
            storage,
            NodeExecutorRegistry(agent=AgentNodeExecutor(backend)),
        ).execute(artifact, execution_id, {"value": 1})

    assert trace == []
    assert not any(
        event.event_type.startswith("TOOL_")
        for event in storage.load_events(execution_id)
    )


def test_backend_cannot_claim_tool_effect_without_durable_records(tmp_path: Path) -> None:
    artifact = _agent_artifact()
    storage = AtomicFileStateStorage(tmp_path)
    execution_id = "exec-tool-evidence-mismatch"
    storage.create_execution(_record(artifact, execution_id))
    tool_record = ToolExecutionRecord(
        step=1,
        call_id="call-unrecorded",
        tool_name="knowledge_retriever",
        arguments_digest=f"sha256:{'e' * 64}",
        succeeded=True,
        result_digest=f"sha256:{'f' * 64}",
        redacted_result="untrusted",
        policy_decision_digest=_allowed_tool_decision(artifact).digest(),
    )

    with pytest.raises(ToolEffectIntegrityError, match="diverges"):
        _executor(
            storage,
            NodeExecutorRegistry(
                agent=AgentNodeExecutor(
                    _StaticBackend(
                        NodeExecutionResult.completed(
                            {"result": "untrusted"},
                            tool_executions=(tool_record,),
                        )
                    )
                )
            ),
        ).execute(artifact, execution_id, {"value": 1})


def test_tool_record_replay_accepts_complete_pair_without_reexecution(
    tmp_path: Path,
) -> None:
    artifact = _agent_artifact()
    storage = _LegacyToolEventStorage(tmp_path)
    execution_id = "exec-tool-record-resume"
    initial_input = {"value": 1}
    _create_resume_execution(storage, artifact, execution_id, initial_input)
    tool_record = ToolExecutionRecord(
        step=1,
        call_id="call-resume",
        tool_name="knowledge_retriever",
        arguments_digest=f"sha256:{'3' * 64}",
        succeeded=True,
        result_digest=f"sha256:{'4' * 64}",
        redacted_result="ok",
        policy_decision_digest=_allowed_tool_decision(artifact).digest(),
    )
    backend = _DurableStaticBackend(
        NodeExecutionResult.completed(
            {"result": "ok"},
            tool_executions=(tool_record,),
        )
    )
    executor = _resume_executor(
        storage,
        NodeExecutorRegistry(agent=AgentNodeExecutor(backend)),
    )

    with pytest.raises(StateWriteError, match="outcome CAS"):
        executor.execute(artifact, execution_id, initial_input)
    result = executor.resume(artifact, execution_id)

    assert result.outcome == "success"
    assert [
        event.event_type
        for event in storage.load_events(execution_id)
        if event.event_type.startswith("TOOL_")
    ] == ["TOOL_CALLED", "TOOL_COMPLETED"]
    assert backend.executions == 1


def test_policy_decision_is_persisted_before_effect_and_bound_to_outcome(
    tmp_path: Path,
) -> None:
    artifact = _agent_artifact()
    decision = _allowed_tool_decision(artifact)
    storage = _FailOutcomeCasStorage(tmp_path)
    execution_id = "exec-policy-decision-resume"
    initial_input = {"value": 1}
    _create_resume_execution(storage, artifact, execution_id, initial_input)
    tool_record = ToolExecutionRecord(
        step=1,
        call_id="call-policy",
        tool_name="knowledge_retriever",
        arguments_digest=f"sha256:{'9' * 64}",
        succeeded=True,
        result_digest=f"sha256:{'a' * 64}",
        redacted_result="ok",
        policy_decision_digest=decision.digest(),
    )
    backend = _DurableStaticBackend(
        NodeExecutionResult.completed(
            {"result": "ok"},
            tool_executions=(tool_record,),
        ),
        policy_decision=decision,
    )
    executor = _resume_executor(
        storage,
        NodeExecutorRegistry(agent=AgentNodeExecutor(backend)),
    )

    with pytest.raises(StateWriteError, match="outcome CAS"):
        executor.execute(artifact, execution_id, initial_input)
    events = storage.load_events(execution_id)
    called = next(event for event in events if event.event_type == "TOOL_CALLED")
    completed = next(event for event in events if event.event_type == "TOOL_COMPLETED")

    assert called.payload["policy_decision"] == decision.model_dump(mode="json")
    assert "arguments" not in called.payload
    assert completed.payload["policy_decision_digest"] == decision.digest()
    assert executor.resume(artifact, execution_id).outcome == "success"
    assert backend.executions == 1


def test_replay_rejects_tampered_policy_decision_digest(tmp_path: Path) -> None:
    artifact = _agent_artifact()
    decision = _allowed_tool_decision(artifact)
    storage = _TamperedToolDecisionStorage(tmp_path)
    execution_id = "exec-policy-decision-tampered"
    initial_input = {"value": 1}
    _create_resume_execution(storage, artifact, execution_id, initial_input)
    tool_record = ToolExecutionRecord(
        step=1,
        call_id="call-policy-tampered",
        tool_name="knowledge_retriever",
        arguments_digest=f"sha256:{'b' * 64}",
        succeeded=True,
        result_digest=f"sha256:{'c' * 64}",
        redacted_result="ok",
        policy_decision_digest=decision.digest(),
    )
    executor = _resume_executor(
        storage,
        NodeExecutorRegistry(
            agent=AgentNodeExecutor(
                _DurableStaticBackend(
                    NodeExecutionResult.completed(
                        {"result": "ok"},
                        tool_executions=(tool_record,),
                    ),
                    policy_decision=decision,
                )
            )
        ),
    )

    with pytest.raises(StateWriteError, match="outcome CAS"):
        executor.execute(artifact, execution_id, initial_input)
    journal_before = storage.load_events(execution_id)
    with pytest.raises(InterruptedNodeExecutionError, match="policy decision"):
        executor.resume(artifact, execution_id)

    assert storage.load_events(execution_id) == journal_before


def test_tool_event_replay_rejects_partial_pair_without_backend(tmp_path: Path) -> None:
    artifact = _agent_artifact()
    storage = _FailToolOutcomeAppendStorage(tmp_path)
    execution_id = "exec-tool-event-partial"
    initial_input = {"value": 1}
    _create_resume_execution(storage, artifact, execution_id, initial_input)
    tool_record = ToolExecutionRecord(
        step=1,
        call_id="call-partial",
        tool_name="knowledge_retriever",
        arguments_digest=f"sha256:{'5' * 64}",
        succeeded=True,
        result_digest=f"sha256:{'6' * 64}",
        redacted_result="ok",
        policy_decision_digest=_allowed_tool_decision(artifact).digest(),
    )
    executor = _resume_executor(
        storage,
        NodeExecutorRegistry(
            agent=AgentNodeExecutor(
                _DurableStaticBackend(
                    NodeExecutionResult.completed(
                        {"result": "ok"},
                        tool_executions=(tool_record,),
                    )
                )
            )
        ),
    )

    with pytest.raises(ToolEffectAmbiguousError, match="durable outcome"):
        executor.execute(artifact, execution_id, initial_input)
    journal_before = storage.load_events(execution_id)
    with pytest.raises(InterruptedNodeExecutionError):
        executor.resume(artifact, execution_id)

    assert storage.load_events(execution_id) == journal_before


def test_tool_event_replay_rejects_adulterated_extra_outcome(tmp_path: Path) -> None:
    artifact = _agent_artifact()
    storage = AtomicFileStateStorage(tmp_path)
    execution_id = "exec-tool-event-adulterated"
    initial_input = {"value": 1}
    _create_resume_execution(storage, artifact, execution_id, initial_input)
    tool_record = ToolExecutionRecord(
        step=1,
        call_id="call-original",
        tool_name="knowledge_retriever",
        arguments_digest=f"sha256:{'7' * 64}",
        succeeded=True,
        result_digest=f"sha256:{'8' * 64}",
        redacted_result="ok",
        policy_decision_digest=_allowed_tool_decision(artifact).digest(),
    )
    executor = _resume_executor(
        storage,
        NodeExecutorRegistry(
            agent=AgentNodeExecutor(
                _DurableStaticBackend(
                    NodeExecutionResult.completed(
                        {"result": "ok"},
                        tool_executions=(tool_record,),
                    )
                )
            )
        ),
    )
    executor.execute(artifact, execution_id, initial_input)
    outcome = next(
        event
        for event in storage.load_events(execution_id)
        if event.event_type == "TOOL_COMPLETED"
    )
    adulterated = ExecutionEvent.model_validate(
        {
            **outcome.model_dump(),
            "event_id": "adulterated-tool-outcome",
            "timestamp": outcome.timestamp + timedelta(seconds=10),
            "payload": {**outcome.payload, "call_id": "call-adulterated"},
            "previous_hash": None,
            "current_hash": None,
        }
    )
    storage.append_event(execution_id, adulterated)
    journal_before = storage.load_events(execution_id)

    with pytest.raises(InterruptedNodeExecutionError, match="tool outcome ledger"):
        executor.resume(artifact, execution_id)

    assert storage.load_events(execution_id) == journal_before


def test_invalid_input_contract_rejection_is_side_effect_free(tmp_path: Path) -> None:
    artifact = _agent_artifact()
    storage = AtomicFileStateStorage(tmp_path)
    storage.create_execution(_record(artifact, "exec-invalid-input"))
    trace: list[str] = []
    executor = _executor(
        storage,
        NodeExecutorRegistry(agent=AgentNodeExecutor(_TraceBackend(trace))),
    )

    with pytest.raises(NodeInputValidationError):
        executor.execute(artifact, "exec-invalid-input", {"value": "not-an-int"})

    assert trace == []
    assert _journal(tmp_path, "exec-invalid-input") == []
    assert storage.load_execution("exec-invalid-input").revision == 0


def test_invalid_output_follows_failure_edge(tmp_path: Path) -> None:
    artifact = _agent_artifact()
    storage = AtomicFileStateStorage(tmp_path)
    storage.create_execution(_record(artifact, "exec-invalid-output"))
    trace: list[str] = []
    result = _executor(
        storage,
        NodeExecutorRegistry(
            agent=AgentNodeExecutor(
                _TraceBackend(trace, invalid_output_node="agent")
            )
        ),
    ).execute(artifact, "exec-invalid-output", {"value": 1})

    assert result.outcome == "failure"
    assert result.terminal_id == "failed"
    assert result.failure is not None
    assert result.failure.code == "invalid_node_output"
    assert storage.load_execution("exec-invalid-output").current_node_id == "failed"
    events = _journal(tmp_path, "exec-invalid-output")
    assert [event["event_type"] for event in events] == [
        "STATE_TRANSITIONED",
        "NODE_STARTED",
        "NODE_FAILED",
        "STATE_TRANSITIONED",
    ]
    assert events[-2]["payload"]["error_code"] == "invalid_node_output"
    assert events[-1]["payload"]["to_state"] == "FAILED"


def test_backend_failure_follows_only_failure_edge(tmp_path: Path) -> None:
    artifact = _artifact([_deterministic_node("gate", "completed")])
    storage = AtomicFileStateStorage(tmp_path)
    storage.create_execution(_record(artifact, "exec-backend-failure"))
    result = _executor(
        storage,
        NodeExecutorRegistry(
            deterministic=DeterministicNodeExecutor(
                _TraceBackend([], raise_node="gate")
            )
        ),
    ).execute(artifact, "exec-backend-failure", {})

    assert result.outcome == "failure"
    assert result.failure is not None
    assert result.failure.code == "backend_rejected"
    assert storage.load_execution("exec-backend-failure").current_node_id == "failed"


def test_malformed_backend_result_follows_failure_edge(tmp_path: Path) -> None:
    artifact = _artifact([_deterministic_node("gate", "completed")])
    storage = AtomicFileStateStorage(tmp_path)
    storage.create_execution(_record(artifact, "exec-malformed"))
    result = _executor(
        storage,
        NodeExecutorRegistry(
            deterministic=DeterministicNodeExecutor(_StaticBackend({"not": "typed"})),
        ),
    ).execute(artifact, "exec-malformed", {})

    assert result.outcome == "failure"
    assert result.failure is not None
    assert result.failure.code == "invalid_node_result"
    assert _journal(tmp_path, "exec-malformed")[-2]["event_type"] == "NODE_FAILED"


def test_invalid_event_id_prevents_backend_and_cas(tmp_path: Path) -> None:
    artifact = _artifact([_deterministic_node("gate", "completed")])
    storage = AtomicFileStateStorage(tmp_path)
    storage.create_execution(_record(artifact, "exec-invalid-event"))
    trace: list[str] = []
    executor = GraphExecutor(
        storage,
        NodeExecutorRegistry(
            deterministic=DeterministicNodeExecutor(_TraceBackend(trace)),
        ),
        clock=_Clock(),
        event_id_factory=lambda: "invalid event id",
        owner_id_factory=lambda: "unit-test-worker",
    )

    with pytest.raises(StateTransitionIntegrityError):
        executor.execute(artifact, "exec-invalid-event", {})

    assert trace == []
    assert storage.load_execution("exec-invalid-event").revision == 0
    assert _journal(tmp_path, "exec-invalid-event") == []


@pytest.mark.parametrize(
    ("case", "record_kwargs", "error_type"),
    [
        ("unknown", {"current_node_id": "missing"}, UnknownCurrentNodeError),
        (
            "mismatch",
            {"artifact_digest": f"sha256:{'f' * 64}"},
            ArtifactExecutionMismatchError,
        ),
    ],
)
def test_unknown_or_artifact_mismatch_is_side_effect_free(
    tmp_path: Path,
    case: str,
    record_kwargs: dict[str, str],
    error_type: type[Exception],
) -> None:
    artifact = _artifact([_deterministic_node("gate", "completed")])
    execution_id = f"exec-{case}"
    storage = AtomicFileStateStorage(tmp_path)
    storage.create_execution(_record(artifact, execution_id, **record_kwargs))
    executor = _executor(
        storage,
        NodeExecutorRegistry(
            deterministic=DeterministicNodeExecutor(_TraceBackend([])),
        ),
    )

    with pytest.raises(error_type):
        executor.execute(artifact, execution_id, {})

    assert _journal(tmp_path, execution_id) == []
    assert storage.load_execution(execution_id).revision == 0


def test_unavailable_executor_is_side_effect_free(tmp_path: Path) -> None:
    artifact = _artifact([_deterministic_node("gate", "completed")])
    storage = AtomicFileStateStorage(tmp_path)
    storage.create_execution(_record(artifact, "exec-unavailable"))

    with pytest.raises(NodeExecutorUnavailableError):
        _executor(storage, NodeExecutorRegistry()).execute(
            artifact,
            "exec-unavailable",
            {},
        )

    assert _journal(tmp_path, "exec-unavailable") == []
    assert storage.load_execution("exec-unavailable").revision == 0


def test_cycle_revisit_is_rejected_before_second_execution(tmp_path: Path) -> None:
    artifact = _artifact(
        [
            _deterministic_node(
                "loop",
                "loop",
                retry_policy={"max_iterations": 2, "exit_condition": "later"},
            )
        ]
    )
    storage = AtomicFileStateStorage(tmp_path)
    storage.create_execution(_record(artifact, "exec-cycle"))
    trace: list[str] = []
    executor = _executor(
        storage,
        NodeExecutorRegistry(
            deterministic=DeterministicNodeExecutor(_TraceBackend(trace)),
        ),
    )

    with pytest.raises(GraphCycleExecutionError):
        executor.execute(artifact, "exec-cycle", {"trace": []})

    assert trace == ["loop"]
    assert storage.load_execution("exec-cycle").revision == 2
    assert len(_journal(tmp_path, "exec-cycle")) == 3


def test_retryable_failure_requires_actionable_evidence() -> None:
    with pytest.raises(ValueError, match="requires retry evidence"):
        NodeExecutionResult.failed(
            {},
            code="missing_retry_evidence",
            message="retry was requested without failure evidence",
            retryable=True,
        )


def test_retry_context_corrects_on_second_attempt_and_is_redacted(
    tmp_path: Path,
) -> None:
    retry_policy = {"max_iterations": 2, "exit_condition": "gates_pass"}
    artifact = _artifact(
        [
            _deterministic_node(
                "code",
                "verify",
                on_failure="code",
                retry_policy=retry_policy,
            ),
            _deterministic_node(
                "verify",
                "completed",
                on_failure="code",
                retry_policy=retry_policy,
            ),
        ]
    )
    execution_id = "exec-retry-corrects"
    storage = AtomicFileStateStorage(tmp_path)
    _create_resume_execution(storage, artifact, execution_id, {"trace": []})
    trace: list[tuple[str, int, RetryContext | None]] = []
    result = _resume_executor(
        storage,
        NodeExecutorRegistry(
            deterministic=DeterministicNodeExecutor(
                _RetryBackend(trace, {"verify": {1}})
            ),
        ),
    ).execute(artifact, execution_id, {"trace": []})

    assert result.outcome == "success"
    assert result.executed_node_ids == ("code", "verify", "code", "verify")
    assert [(node, attempt) for node, attempt, _ in trace] == [
        ("code", 1),
        ("verify", 1),
        ("code", 2),
        ("verify", 2),
    ]
    assert [context is not None for _, _, context in trace] == [
        False,
        False,
        True,
        True,
    ]
    code_retry = trace[2][2]
    verify_retry = trace[3][2]
    assert code_retry is not None
    assert verify_retry is not None
    assert code_retry.origin_node_id == "verify"
    assert verify_retry.origin_node_id == "verify"
    assert code_retry.current_attempt == 2
    assert verify_retry.current_attempt == 2
    assert code_retry.failed_gates == ("pytest",)
    assert code_retry.remaining_budget.remaining_tokens == 900
    assert _RETRY_SECRET not in code_retry.model_dump_json()
    assert "[REDACTED_SECRET]" in code_retry.model_dump_json()

    events = _journal(tmp_path, execution_id)
    starts = [event for event in events if event["event_type"] == "NODE_STARTED"]
    outcomes = [
        event
        for event in events
        if event["event_type"] in {"NODE_COMPLETED", "NODE_FAILED"}
    ]
    assert ["retry_context_digest" in event["payload"] for event in starts] == [
        False,
        False,
        True,
        True,
    ]
    assert [
        "next_retry_context_digest" in event["payload"] for event in outcomes
    ] == [False, True, True, False]
    assert storage.load_execution(execution_id).attempt_by_node == {
        "code": 2,
        "verify": 2,
    }
    secret_bytes = _RETRY_SECRET.encode("utf-8")
    assert all(
        secret_bytes not in path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    )


def test_retry_exhausted_stops_before_extra_effect_and_resume_is_idempotent(
    tmp_path: Path,
) -> None:
    artifact = _artifact(
        [
            _deterministic_node(
                "loop",
                "completed",
                on_failure="loop",
                retry_policy={"max_iterations": 2, "exit_condition": "gate_passes"},
            )
        ]
    )
    execution_id = "exec-retry-exhausted"
    storage = AtomicFileStateStorage(tmp_path)
    _create_resume_execution(storage, artifact, execution_id, {"trace": []})
    trace: list[tuple[str, int, RetryContext | None]] = []
    executor = _resume_executor(
        storage,
        NodeExecutorRegistry(
            deterministic=DeterministicNodeExecutor(
                _RetryBackend(trace, {"loop": {1, 2, 3}})
            ),
        ),
    )

    with pytest.raises(RetryExhaustedError) as captured:
        executor.execute(artifact, execution_id, {"trace": []})

    assert captured.value.classification == "retry_exhausted"
    assert [(node, attempt) for node, attempt, _ in trace] == [
        ("loop", 1),
        ("loop", 2),
    ]
    assert trace[0][2] is None
    assert trace[1][2] is not None
    record = storage.load_execution(execution_id)
    assert record.current_state == ExecutionState.FAILED_RETRY_EXHAUSTED
    assert record.attempt_by_node == {"loop": 2}
    journal_before = storage.load_events(execution_id)
    assert [event.event_type for event in journal_before].count("NODE_STARTED") == 2
    assert journal_before[-1].event_type == "STATE_TRANSITIONED"
    assert journal_before[-1].payload["reason"] == "node_retry_exhausted"

    with pytest.raises(RetryExhaustedError):
        executor.resume(artifact, execution_id)

    assert len(trace) == 2
    assert storage.load_execution(execution_id) == record
    assert storage.load_events(execution_id) == journal_before


def test_resume_rejects_tampered_retry_context_before_backend(
    tmp_path: Path,
) -> None:
    artifact = _artifact(
        [
            _deterministic_node(
                "loop",
                "completed",
                on_failure="loop",
                retry_policy={"max_iterations": 2, "exit_condition": "gate_passes"},
            )
        ]
    )
    execution_id = "exec-retry-context-tamper"
    storage = _FailSecondNodeStartStorage(tmp_path)
    _create_resume_execution(storage, artifact, execution_id, {"trace": []})
    trace: list[tuple[str, int, RetryContext | None]] = []
    executor = _resume_executor(
        storage,
        NodeExecutorRegistry(
            deterministic=DeterministicNodeExecutor(
                _RetryBackend(trace, {"loop": {1}})
            ),
        ),
    )
    with pytest.raises(StateWriteError, match="before retry start"):
        executor.execute(artifact, execution_id, {"trace": []})

    failed_event = next(
        event
        for event in storage.load_events(execution_id)
        if event.event_type == "NODE_FAILED"
    )
    digest = failed_event.payload["next_retry_context_digest"]
    assert isinstance(digest, str)
    context_path = (
        tmp_path
        / ".harness"
        / "artifacts"
        / "executions"
        / execution_id
        / "payloads"
        / f"{digest.removeprefix('sha256:')}.json"
    )
    context_path.write_bytes(b'{"tampered":true}\n')
    record_before = storage.load_execution(execution_id)
    journal_before = storage.load_events(execution_id)

    with pytest.raises(ExecutionBundleIntegrityError):
        executor.resume(artifact, execution_id)

    assert [(node, attempt) for node, attempt, _ in trace] == [("loop", 1)]
    assert storage.load_execution(execution_id) == record_before
    assert storage.load_events(execution_id) == journal_before


def test_append_failure_prevents_backend_and_cas(tmp_path: Path) -> None:
    artifact = _artifact([_deterministic_node("gate", "completed")])
    inner = AtomicFileStateStorage(tmp_path)
    inner.create_execution(_record(artifact, "exec-append-failure"))
    storage = _FailingStorage(inner, fail_append_number=1)
    assert isinstance(storage, StateStorageProvider)
    assert isinstance(storage, EventJournalStateStorageProvider)
    trace: list[str] = []

    with pytest.raises(StateWriteError):
        _executor(
            storage,
            NodeExecutorRegistry(
                deterministic=DeterministicNodeExecutor(_TraceBackend(trace)),
            ),
        ).execute(artifact, "exec-append-failure", {})

    assert trace == []
    assert inner.load_execution("exec-append-failure").revision == 0
    assert _journal(tmp_path, "exec-append-failure") == []


def test_cas_failure_is_not_masked_and_preserves_events(tmp_path: Path) -> None:
    artifact = _artifact([_deterministic_node("gate", "completed")])
    inner = AtomicFileStateStorage(tmp_path)
    inner.create_execution(_record(artifact, "exec-cas-failure"))
    storage = _FailingStorage(inner, fail_cas=True)

    with pytest.raises(StateWriteError):
        _executor(
            storage,
            NodeExecutorRegistry(
                deterministic=DeterministicNodeExecutor(_TraceBackend([])),
            ),
        ).execute(artifact, "exec-cas-failure", {})

    assert inner.load_execution("exec-cas-failure").revision == 0
    assert [event["event_type"] for event in _journal(tmp_path, "exec-cas-failure")] == [
        "STATE_TRANSITIONED",
    ]


def test_terminal_worker_does_not_reexecute_node(tmp_path: Path) -> None:
    artifact = _artifact([_deterministic_node("gate", "completed")])
    storage = AtomicFileStateStorage(tmp_path)
    storage.create_execution(_record(artifact, "exec-terminal-worker"))
    trace: list[str] = []
    executor = _executor(
        storage,
        NodeExecutorRegistry(
            deterministic=DeterministicNodeExecutor(_TraceBackend(trace)),
        ),
    )
    first = executor.execute(artifact, "exec-terminal-worker", {})
    journal_before = _journal(tmp_path, "exec-terminal-worker")
    result = executor.execute(
        artifact,
        "exec-terminal-worker",
        {"preserved": True},
    )

    assert first.executed_node_ids == ("gate",)
    assert result.outcome == "success"
    assert result.executed_node_ids == ()
    assert result.final_revision == 3
    assert trace == ["gate"]
    assert _journal(tmp_path, "exec-terminal-worker") == journal_before


def test_terminal_snapshot_mismatch_is_side_effect_free(tmp_path: Path) -> None:
    artifact = _artifact([_deterministic_node("gate", "completed")])
    execution_id = "exec-terminal-mismatch"
    storage = AtomicFileStateStorage(tmp_path)
    storage.create_execution(
        _record(artifact, execution_id, current_node_id="completed")
    )

    with pytest.raises(StateReplayError, match="terminal node"):
        _executor(storage, NodeExecutorRegistry()).execute(
            artifact,
            execution_id,
            {},
        )

    assert storage.load_execution(execution_id).revision == 0
    assert _journal(tmp_path, execution_id) == []


def test_interrupted_execution_does_not_reexecute_backend(tmp_path: Path) -> None:
    artifact = _artifact(
        [
            _deterministic_node(
                "loop",
                "loop",
                retry_policy={"max_iterations": 2, "exit_condition": "later"},
            )
        ]
    )
    storage = AtomicFileStateStorage(tmp_path)
    storage.create_execution(_record(artifact, "exec-interrupted"))
    trace: list[str] = []
    executor = _executor(
        storage,
        NodeExecutorRegistry(
            deterministic=DeterministicNodeExecutor(_TraceBackend(trace)),
        ),
    )
    with pytest.raises(GraphCycleExecutionError):
        executor.execute(artifact, "exec-interrupted", {})
    journal_before = _journal(tmp_path, "exec-interrupted")

    with pytest.raises(InterruptedExecutionError):
        executor.execute(artifact, "exec-interrupted", {})

    assert trace == ["loop"]
    assert _journal(tmp_path, "exec-interrupted") == journal_before


def test_execute_accepts_planning_only_as_pre_graph_entry_state(tmp_path: Path) -> None:
    artifact = _artifact([_deterministic_node("gate", "completed")])
    execution_id = "exec-planning-entry"
    storage = AtomicFileStateStorage(tmp_path)
    storage.create_execution(_record(artifact, execution_id))
    EventSourcedStateMachine(storage, execution_id, clock=_Clock()).transition_to(
        ExecutionState.PLANNING,
        node_id="gate",
        attempt=0,
        reason="context_sufficient",
    )
    trace: list[str] = []

    result = _executor(
        storage,
        NodeExecutorRegistry(
            deterministic=DeterministicNodeExecutor(_TraceBackend(trace)),
        ),
    ).execute(artifact, execution_id, {})

    assert result.outcome == "success"
    assert trace == ["gate"]
    transitions = [
        event.payload
        for event in storage.load_events(execution_id)
        if event.event_type == "STATE_TRANSITIONED"
    ]
    assert any(
        payload["from_state"] == "PLANNING" and payload["to_state"] == "EXECUTING"
        for payload in transitions
    )


def test_resume_recovers_pending_outcome_without_reexecuting_completed_node(
    tmp_path: Path,
) -> None:
    artifact = _artifact([_deterministic_node("gate", "completed")])
    storage = _FailOutcomeCasStorage(tmp_path)
    execution_id = "exec-resume-pending-outcome"
    initial_input = {"trace": []}
    _create_resume_execution(storage, artifact, execution_id, initial_input)
    trace: list[str] = []
    registry = NodeExecutorRegistry(
        deterministic=DeterministicNodeExecutor(_TraceBackend(trace)),
    )
    executor = _resume_executor(storage, registry)

    with pytest.raises(StateWriteError, match="outcome CAS"):
        executor.execute(artifact, execution_id, initial_input)

    assert trace == ["gate"]
    assert storage.load_execution(execution_id).revision == 1
    outcome_count = [
        event.event_type for event in storage.load_events(execution_id)
    ].count("NODE_COMPLETED")
    result = executor.resume(artifact, execution_id)

    assert result.outcome == "success"
    assert result.executed_node_ids == ()
    assert trace == ["gate"]
    assert storage.load_execution(execution_id).current_state == ExecutionState.COMPLETED
    assert [
        event.event_type for event in storage.load_events(execution_id)
    ].count("NODE_COMPLETED") == outcome_count


def test_resume_started_without_outcome_requires_intervention_without_backend(
    tmp_path: Path,
) -> None:
    artifact = _artifact([_deterministic_node("gate", "completed")])
    storage = _FailOutcomeAppendStorage(tmp_path)
    execution_id = "exec-started-without-outcome"
    initial_input = {"trace": []}
    _create_resume_execution(storage, artifact, execution_id, initial_input)
    trace: list[str] = []
    executor = _resume_executor(
        storage,
        NodeExecutorRegistry(
            deterministic=DeterministicNodeExecutor(_TraceBackend(trace)),
        ),
    )

    with pytest.raises(StateWriteError, match="append interruption"):
        executor.execute(artifact, execution_id, initial_input)
    journal_before = storage.load_events(execution_id)
    with pytest.raises(InterruptedNodeExecutionError) as captured:
        executor.resume(artifact, execution_id)

    assert captured.value.classification == "requires_intervention"
    assert captured.value.node_id == "gate"
    assert trace == ["gate"]
    assert storage.load_events(execution_id) == journal_before


def test_resume_missing_payload_fails_without_backend_or_mutation(tmp_path: Path) -> None:
    artifact = _artifact([_deterministic_node("gate", "completed")])
    storage = AtomicFileStateStorage(tmp_path)
    execution_id = "exec-resume-missing-payload"
    initial_input = {"trace": []}
    _create_resume_execution(storage, artifact, execution_id, initial_input)
    trace: list[str] = []
    executor = _resume_executor(
        storage,
        NodeExecutorRegistry(
            deterministic=DeterministicNodeExecutor(_TraceBackend(trace)),
        ),
    )
    executor.execute(artifact, execution_id, initial_input)
    outcome = next(
        event
        for event in storage.load_events(execution_id)
        if event.event_type == "NODE_COMPLETED"
    )
    output_digest = outcome.payload["output_digest"]
    assert isinstance(output_digest, str)
    payload_path = (
        tmp_path
        / ".harness"
        / "artifacts"
        / "executions"
        / execution_id
        / "payloads"
        / f"{output_digest.removeprefix('sha256:')}.json"
    )
    payload_path.unlink()
    journal_before = storage.load_events(execution_id)
    record_before = storage.load_execution(execution_id)

    with pytest.raises(ExecutionBundleIntegrityError, match="missing"):
        executor.resume(artifact, execution_id)

    assert trace == ["gate"]
    assert storage.load_events(execution_id) == journal_before
    assert storage.load_execution(execution_id) == record_before


def test_resume_duplicate_outcome_is_rejected_without_backend(tmp_path: Path) -> None:
    artifact = _artifact([_deterministic_node("gate", "completed")])
    storage = AtomicFileStateStorage(tmp_path)
    execution_id = "exec-resume-duplicate-outcome"
    initial_input = {"trace": []}
    _create_resume_execution(storage, artifact, execution_id, initial_input)
    trace: list[str] = []
    executor = _resume_executor(
        storage,
        NodeExecutorRegistry(
            deterministic=DeterministicNodeExecutor(_TraceBackend(trace)),
        ),
    )
    executor.execute(artifact, execution_id, initial_input)
    outcome = next(
        event
        for event in storage.load_events(execution_id)
        if event.event_type == "NODE_COMPLETED"
    )
    duplicate = ExecutionEvent.model_validate(
        {
            **outcome.model_dump(),
            "event_id": "duplicate-outcome-event",
            "timestamp": outcome.timestamp + timedelta(seconds=1),
            "previous_hash": None,
            "current_hash": None,
        }
    )
    storage.append_event(execution_id, duplicate)
    journal_before = storage.load_events(execution_id)

    with pytest.raises(InterruptedNodeExecutionError, match="duplicate or gap"):
        executor.resume(artifact, execution_id)

    assert trace == ["gate"]
    assert storage.load_events(execution_id) == journal_before


@pytest.mark.parametrize(
    ("tamper", "message"),
    [
        ("attempt", "attempt"),
        ("next_id", "declared edge"),
        ("input_digest", "payload chain"),
        ("revision_gap", "duplicate or gap"),
    ],
)
def test_resume_tampered_ledger_attempt_next_digest_or_gap_fails_closed(
    tmp_path: Path,
    tamper: str,
    message: str,
) -> None:
    artifact = _artifact([_deterministic_node("gate", "completed")])
    storage = AtomicFileStateStorage(tmp_path)
    execution_id = f"exec-ledger-{tamper.replace('_', '-')}"
    initial_input = {"trace": []}
    _create_resume_execution(storage, artifact, execution_id, initial_input)
    machine = EventSourcedStateMachine(
        storage,
        execution_id,
        clock=_Clock(),
        event_id_factory=_EventIds(),
    )
    machine.transition_to(
        ExecutionState.EXECUTING,
        node_id="gate",
        attempt=1,
        reason="graph_execution_started",
    )
    bundle = storage.load_execution_bundle(execution_id)
    input_digest = bundle.initial_input_digest
    if tamper == "input_digest":
        input_digest = storage.store_payload(execution_id, {"different": True})
    output_digest = storage.store_payload(execution_id, {"trace": ["gate"]})
    state_event = storage.load_events(execution_id)[0]
    fencing_token = state_event.payload["fencing_token"]
    attempt = 2 if tamper == "attempt" else 1
    storage.append_event(
        execution_id,
        ExecutionEvent(
            event_id=f"started-{tamper}",
            execution_id=execution_id,
            event_type="NODE_STARTED",
            timestamp=_BASE_TIME + timedelta(seconds=2),
            payload={
                "attempt": attempt,
                "fencing_token": fencing_token,
                "input_digest": input_digest,
                "node_id": "gate",
                "node_type": "deterministic",
            },
        ),
    )
    storage.append_event(
        execution_id,
        ExecutionEvent(
            event_id=f"outcome-{tamper}",
            execution_id=execution_id,
            event_type="NODE_COMPLETED",
            timestamp=_BASE_TIME + timedelta(seconds=3),
            payload={
                "attempt": attempt,
                "fencing_token": fencing_token,
                "input_digest": input_digest,
                "next_id": "failed" if tamper == "next_id" else "completed",
                "node_id": "gate",
                "node_type": "deterministic",
                "output_digest": output_digest,
                "record_revision": 3 if tamper == "revision_gap" else 2,
            },
        ),
    )
    journal_before = storage.load_events(execution_id)
    record_before = storage.load_execution(execution_id)

    with pytest.raises(InterruptedNodeExecutionError, match=message):
        _resume_executor(storage, NodeExecutorRegistry()).resume(
            artifact,
            execution_id,
        )

    assert storage.load_events(execution_id) == journal_before
    assert storage.load_execution(execution_id) == record_before


def test_resume_rejects_partial_model_metadata_without_backend(tmp_path: Path) -> None:
    artifact = _artifact([_deterministic_node("gate", "completed")])
    storage = AtomicFileStateStorage(tmp_path)
    execution_id = "exec-ledger-partial-model-metadata"
    initial_input = {"trace": []}
    _create_resume_execution(storage, artifact, execution_id, initial_input)
    machine = EventSourcedStateMachine(
        storage,
        execution_id,
        clock=_Clock(),
        event_id_factory=_EventIds(),
    )
    machine.transition_to(
        ExecutionState.EXECUTING,
        node_id="gate",
        attempt=1,
        reason="graph_execution_started",
    )
    input_digest = storage.load_execution_bundle(execution_id).initial_input_digest
    output_digest = storage.store_payload(execution_id, {"trace": ["gate"]})
    fencing_token = storage.load_events(execution_id)[0].payload["fencing_token"]
    storage.append_event(
        execution_id,
        ExecutionEvent(
            event_id="started-partial-model-metadata",
            execution_id=execution_id,
            event_type="NODE_STARTED",
            timestamp=_BASE_TIME + timedelta(seconds=2),
            payload={
                "attempt": 1,
                "fencing_token": fencing_token,
                "input_digest": input_digest,
                "node_id": "gate",
                "node_type": "deterministic",
            },
        ),
    )
    storage.append_event(
        execution_id,
        ExecutionEvent(
            event_id="outcome-partial-model-metadata",
            execution_id=execution_id,
            event_type="NODE_COMPLETED",
            timestamp=_BASE_TIME + timedelta(seconds=3),
            payload={
                "attempt": 1,
                "fencing_token": fencing_token,
                "input_digest": input_digest,
                "next_id": "completed",
                "node_id": "gate",
                "node_type": "deterministic",
                "output_digest": output_digest,
                "record_revision": 2,
                "model_provider": "openai",
            },
        ),
    )
    journal_before = storage.load_events(execution_id)
    record_before = storage.load_execution(execution_id)

    with pytest.raises(InterruptedNodeExecutionError, match="outcome ledger is malformed"):
        _resume_executor(storage, NodeExecutorRegistry()).resume(artifact, execution_id)

    assert storage.load_events(execution_id) == journal_before
    assert storage.load_execution(execution_id) == record_before


def test_concurrent_workers_do_not_duplicate_effect(tmp_path: Path) -> None:
    artifact = _artifact([_deterministic_node("gate", "completed")])
    execution_id = "exec-concurrent"
    storage = AtomicFileStateStorage(tmp_path)
    storage.create_execution(_record(artifact, execution_id))
    marker = tmp_path / "effects.txt"
    context = multiprocessing.get_context("spawn")
    start_event = context.Event()
    result_queue = context.Queue()
    processes = [
        context.Process(
            target=_multiprocess_execute,
            args=(
                str(tmp_path),
                artifact.canonical_json(),
                execution_id,
                str(marker),
                start_event,
                result_queue,
            ),
        )
        for _ in range(2)
    ]
    for process in processes:
        process.start()
    start_event.set()
    for process in processes:
        process.join(20)
        assert process.exitcode == 0

    try:
        results = [result_queue.get(timeout=5) for _ in processes]
    except Empty as exc:
        pytest.fail(f"worker did not report a result: {exc}")
    assert all(result[0] == "ok" for result in results), results
    assert sorted(result[1] for result in results) == [(), ("gate",)]
    assert len({result[2] for result in results}) == 2
    assert marker.read_text(encoding="utf-8").splitlines() == ["gate"]
    persisted = storage.load_execution(execution_id)
    assert persisted.revision == 3
    assert persisted.current_state == ExecutionState.COMPLETED
