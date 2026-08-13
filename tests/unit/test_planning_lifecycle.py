"""F4.4 lifecycle composition for durable planning before graph traversal."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ai_engineering_harness.compiler import GraphCompiler
from ai_engineering_harness.contracts.events import ExecutionEvent
from ai_engineering_harness.contracts.execution import ExecutionState
from ai_engineering_harness.contracts.planning import PlanDocument
from ai_engineering_harness.contracts.structural_index import StructuralSymbol
from ai_engineering_harness.indexer import SnapshotManager
from ai_engineering_harness.models import (
    LLMResponse,
    ModelRouter,
    ProviderTimeoutError,
)
from ai_engineering_harness.persistence import (
    AtomicFileStateStorage,
    ExecutionLock,
    StateWriteError,
    canonical_json_digest,
    canonical_json_object,
)
from ai_engineering_harness.runtime import (
    CONTEXT_EVALUATED,
    PLAN_GENERATED,
    PLAN_GENERATION_STARTED,
    DeterministicNodeExecutor,
    ExecutionBudgetExceededError,
    ExecutionLifecycleService,
    NodeExecutionContext,
    NodeExecutionResult,
    NodeExecutorRegistry,
    PlanningPrerequisiteError,
)

COMMIT_SHA = "b" * 40
_BASE_TIME = datetime(2026, 8, 10, 15, 0, tzinfo=UTC)


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
        return f"planning-lifecycle-event-{self.value}"


@dataclass
class _TraceBackend:
    calls: list[dict[str, object]]

    def execute(self, context: NodeExecutionContext) -> NodeExecutionResult:
        self.calls.append(context.input_payload)
        return NodeExecutionResult.completed({"executed": context.node.id})


class _PlanningProvider:
    provider_id = "test"

    def __init__(self, *, invalid: bool = False, fail: bool = False) -> None:
        self.invalid = invalid
        self.fail = fail
        self.calls = 0

    def structured_output(
        self,
        prompt: str,
        response_schema: dict[str, object],
        **_: object,
    ) -> LLMResponse:
        self.calls += 1
        if self.fail:
            raise ProviderTimeoutError("controlled planning timeout", provider_id="test")
        payload = json.loads(prompt.split("\n", 1)[1])
        constraints = payload["constraints"]
        evidence_refs = constraints["allowed_evidence_refs"]
        acceptance_ref = next(
            reference
            for reference in evidence_refs
            if reference.startswith("artifact:acceptance_criteria@")
        )
        symbol_ref = next(
            reference for reference in evidence_refs if reference.startswith("symbol:")
        )
        content: dict[str, object] = {
            "objective": "Implement logging from the validated requirement and symbol evidence",
            "acceptance_criteria": [
                {
                    "order": 1,
                    "criterion_id": "logging-works",
                    "description": "Logging behavior satisfies the acceptance evidence",
                    "evidence_refs": [acceptance_ref],
                }
            ],
            "targets": [
                {
                    "target_id": "logging-target",
                    "path": "src/logging.py",
                    "symbol": "logging",
                    "change_kind": "modify",
                    "evidence_refs": [symbol_ref],
                }
            ],
            "steps": [
                {
                    "order": 1,
                    "step_id": "implement-logging",
                    "description": "Modify the evidence-bound logging symbol",
                    "target_ids": ["logging-target"],
                    "tools": [],
                }
            ],
            "planned_tools": [],
            "risks": [
                {
                    "risk_id": "logging-regression",
                    "description": "Existing logging behavior may regress",
                    "mitigation": "Run every compiled verification gate",
                }
            ],
            "applicable_gates": constraints["applicable_gates"],
            "rollback_strategy": {
                "triggers": ["A compiled verification gate fails"],
                "actions": ["Revert only the evidence-bound target"],
                "verification": ["Repeat every compiled verification gate"],
            },
            "completion_conditions": [
                {
                    "condition_id": "logging-complete",
                    "criterion_id": "logging-works",
                    "description": "The acceptance criterion is demonstrably satisfied",
                }
            ],
            "remaining_gaps": [],
        }
        if self.invalid:
            content["applicable_gates"] = ["invented-gate"]
        return LLMResponse(
            content="",
            provider="test",
            model_name="planning-test-model",
            prompt_tokens=11,
            completion_tokens=9,
            total_tokens=20,
            request_id="planning-request",
            response_id="planning-response",
            structured_output=content,
        )


class _Registry:
    def __init__(self, provider: _PlanningProvider) -> None:
        self.provider = provider

    def is_configured(self, provider_id: str) -> bool:
        return provider_id == "test"

    def create_provider(self, provider_id: str) -> _PlanningProvider:
        assert provider_id == "test"
        return self.provider


class _InterruptGraphAfterPlanStorage(AtomicFileStateStorage):
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
            and event.payload.get("from_state") == ExecutionState.PLANNING.value
            and event.payload.get("to_state") == ExecutionState.EXECUTING.value
        ):
            self.failure_pending = False
            raise StateWriteError("controlled post-plan interruption", execution_id=execution_id)
        return super().append_event(execution_id, event, lock=lock)


class _TamperPlanOnResumeStorage(_InterruptGraphAfterPlanStorage):
    def __init__(self, project_root: Path) -> None:
        super().__init__(project_root)
        self.tamper_plan = False

    def load_payload(
        self,
        execution_id: str,
        digest: str,
        *,
        lock: ExecutionLock | None = None,
    ) -> dict[str, object]:
        payload = super().load_payload(execution_id, digest, lock=lock)
        if self.tamper_plan and "objective" in payload:
            return {**payload, "context_digest": "sha256:" + "0" * 64}
        return payload


class _InterruptPlanningBlockStorage(AtomicFileStateStorage):
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
            and event.payload.get("from_state") == ExecutionState.PLANNING.value
            and event.payload.get("to_state") == ExecutionState.BLOCKED_PREREQUISITE.value
        ):
            self.failure_pending = False
            raise StateWriteError("controlled planning block interruption", execution_id=execution_id)
        return super().append_event(execution_id, event, lock=lock)


class _FailPlanPayloadStorage(AtomicFileStateStorage):
    def __init__(self, project_root: Path) -> None:
        super().__init__(project_root)
        self.payload_calls = 0

    def store_payload(
        self,
        execution_id: str,
        payload: dict[str, object],
        *,
        lock: ExecutionLock | None = None,
    ) -> str:
        self.payload_calls += 1
        if self.payload_calls == 2:
            raise StateWriteError("controlled plan payload failure", execution_id=execution_id)
        return super().store_payload(execution_id, payload, lock=lock)


def _compiled_graph(project_root: Path, *, include_planning_policies: bool = True) -> Path:
    planning_policies = (
        "  - policies/tool_policy.yaml\n  - policies/verification_policy.yaml\n"
        if include_planning_policies
        else ""
    )
    spec = project_root / "new-feature.yaml"
    spec.write_text(
        f"""graph:
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
{planning_policies}contracts: []
""",
        encoding="utf-8",
    )
    return GraphCompiler(project_root).compile_graph(spec, "new-feature")


def _prepare_evidence(project_root: Path) -> None:
    SnapshotManager(project_root).save_snapshot(
        COMMIT_SHA,
        [
            StructuralSymbol(
                kind="function",
                name="logging",
                qualified_name="logging",
                path="src/logging.py",
                line_start=8,
                line_end=12,
            )
        ],
    )
    root = project_root / ".harness" / "knowledge" / "artifacts"
    root.mkdir(parents=True, exist_ok=True)
    for artifact_id in (
        "prd",
        "domain_model",
        "non_functional_requirements",
        "acceptance_criteria",
        "architecture",
    ):
        (root / f"{artifact_id}.md").write_text(
            f"# {artifact_id}\n\nValidated logging requirement.\n",
            encoding="utf-8",
        )


def _envelope() -> dict[str, object]:
    return {
        "context_request": {
            "requirement_id": "req-logging",
            "graph_type": "new_feature",
            "query": "Add logging",
        },
        "graph_input": {"intent": "deliver", "value": 7},
    }


def _service(
    project_root: Path,
    provider: _PlanningProvider,
    *,
    storage: AtomicFileStateStorage | None = None,
) -> tuple[ExecutionLifecycleService, AtomicFileStateStorage, list[dict[str, object]]]:
    selected_storage = storage or AtomicFileStateStorage(project_root)
    calls: list[dict[str, object]] = []
    registry = _Registry(provider)

    def model_router_factory(_: object) -> ModelRouter:
        return ModelRouter(
            allowed_providers=("test",),
            provider_registry=registry,  # type: ignore[arg-type]
        )

    service = ExecutionLifecycleService(
        project_root,
        selected_storage,
        NodeExecutorRegistry(
            deterministic=DeterministicNodeExecutor(_TraceBackend(calls)),
        ),
        clock=_Clock(),
        event_id_factory=_Ids(),
        owner_id_factory=lambda: "planning-lifecycle-owner",
        git_identity_provider=lambda: (COMMIT_SHA, "task/f4.4-planning"),
        model_router_factory=model_router_factory,  # type: ignore[arg-type]
    )
    return service, selected_storage, calls


def _planning_events(storage: AtomicFileStateStorage, execution_id: str):
    return tuple(
        event
        for event in storage.load_events(execution_id)
        if event.event_type in {PLAN_GENERATION_STARTED, PLAN_GENERATED}
    )


def test_sufficient_context_persists_plan_before_first_node(tmp_path: Path) -> None:
    artifact = _compiled_graph(tmp_path)
    _prepare_evidence(tmp_path)
    provider = _PlanningProvider()
    service, storage, calls = _service(tmp_path, provider)

    service.start(
        artifact,
        execution_id="exec-plan-success",
        initial_input=_envelope(),
        configuration={},
    )

    events = storage.load_events("exec-plan-success")
    event_types = tuple(event.event_type for event in events)
    assert event_types.index(CONTEXT_EVALUATED) < event_types.index(PLAN_GENERATION_STARTED)
    assert event_types.index(PLAN_GENERATION_STARTED) < event_types.index(PLAN_GENERATED)
    assert event_types.index(PLAN_GENERATED) < event_types.index("NODE_STARTED")
    planning_events = _planning_events(storage, "exec-plan-success")
    generated = planning_events[1]
    document = PlanDocument.model_validate(
        storage.load_payload("exec-plan-success", generated.payload["plan_digest"])
    )
    expected_input_digest = canonical_json_digest(
        canonical_json_object(_envelope()["graph_input"])
    )
    assert document.graph_input_digest == expected_input_digest
    assert generated.payload["graph_input_digest"] == expected_input_digest
    assert generated.payload["context_digest"] == planning_events[0].payload["context_digest"]
    assert json.loads(
        (tmp_path / ".harness/state/executions/exec-plan-success/plan.json").read_text(
            encoding="utf-8"
        )
    ) == document.model_dump(mode="json")
    assert calls == [_envelope()["graph_input"]]
    assert provider.calls == 1


def test_resume_recovers_generated_plan_without_second_provider_call(tmp_path: Path) -> None:
    artifact = _compiled_graph(tmp_path)
    _prepare_evidence(tmp_path)
    provider = _PlanningProvider()
    storage = _InterruptGraphAfterPlanStorage(tmp_path)
    service, _, calls = _service(tmp_path, provider, storage=storage)

    with pytest.raises(StateWriteError, match="post-plan interruption"):
        service.start(
            artifact,
            execution_id="exec-plan-resume",
            initial_input=_envelope(),
            configuration={},
        )
    assert storage.load_execution("exec-plan-resume").current_state == ExecutionState.PLANNING
    projection = tmp_path / ".harness/state/executions/exec-plan-resume/plan.json"
    projection.unlink()

    service.resume("exec-plan-resume")

    assert projection.is_file()
    assert provider.calls == 1
    assert calls == [_envelope()["graph_input"]]
    assert len(_planning_events(storage, "exec-plan-resume")) == 2


def test_tampered_plan_identity_on_resume_blocks_without_node_or_provider(
    tmp_path: Path,
) -> None:
    artifact = _compiled_graph(tmp_path)
    _prepare_evidence(tmp_path)
    provider = _PlanningProvider()
    storage = _TamperPlanOnResumeStorage(tmp_path)
    service, _, calls = _service(tmp_path, provider, storage=storage)

    with pytest.raises(StateWriteError, match="post-plan interruption"):
        service.start(
            artifact,
            execution_id="exec-plan-tamper",
            initial_input=_envelope(),
            configuration={},
        )
    storage.tamper_plan = True

    with pytest.raises(PlanningPrerequisiteError):
        service.resume("exec-plan-tamper")

    assert storage.load_execution("exec-plan-tamper").current_state == (
        ExecutionState.BLOCKED_PREREQUISITE
    )
    assert provider.calls == 1
    assert calls == []


def test_duplicate_generated_event_on_resume_blocks_without_second_provider(
    tmp_path: Path,
) -> None:
    artifact = _compiled_graph(tmp_path)
    _prepare_evidence(tmp_path)
    provider = _PlanningProvider()
    storage = _InterruptGraphAfterPlanStorage(tmp_path)
    service, _, calls = _service(tmp_path, provider, storage=storage)

    with pytest.raises(StateWriteError, match="post-plan interruption"):
        service.start(
            artifact,
            execution_id="exec-plan-duplicate",
            initial_input=_envelope(),
            configuration={},
        )
    generated = _planning_events(storage, "exec-plan-duplicate")[1]
    lock = storage.acquire_execution_lock(
        "exec-plan-duplicate",
        "duplicate-event-test",
        timeout_seconds=1,
    )
    try:
        storage.append_event(
            "exec-plan-duplicate",
            ExecutionEvent(
                event_id="duplicate-plan-generated",
                execution_id="exec-plan-duplicate",
                event_type=PLAN_GENERATED,
                timestamp=generated.timestamp + timedelta(seconds=1),
                payload=dict(generated.payload),
            ),
            lock=lock,
        )
    finally:
        storage.release_execution_lock(lock)

    with pytest.raises(PlanningPrerequisiteError):
        service.resume("exec-plan-duplicate")

    assert storage.load_execution("exec-plan-duplicate").current_state == (
        ExecutionState.BLOCKED_PREREQUISITE
    )
    assert provider.calls == 1
    assert calls == []


def test_ambiguous_started_event_blocks_resume_without_second_provider_call(
    tmp_path: Path,
) -> None:
    artifact = _compiled_graph(tmp_path)
    _prepare_evidence(tmp_path)
    provider = _PlanningProvider(fail=True)
    storage = _InterruptPlanningBlockStorage(tmp_path)
    service, _, calls = _service(tmp_path, provider, storage=storage)

    with pytest.raises(StateWriteError, match="planning block interruption"):
        service.start(
            artifact,
            execution_id="exec-plan-ambiguous",
            initial_input=_envelope(),
            configuration={},
        )
    assert storage.load_execution("exec-plan-ambiguous").current_state == ExecutionState.PLANNING
    assert tuple(event.event_type for event in _planning_events(storage, "exec-plan-ambiguous")) == (
        PLAN_GENERATION_STARTED,
    )

    with pytest.raises(PlanningPrerequisiteError):
        service.resume("exec-plan-ambiguous")

    assert storage.load_execution("exec-plan-ambiguous").current_state == (
        ExecutionState.BLOCKED_PREREQUISITE
    )
    assert provider.calls == 1
    assert calls == []


def test_invalid_provider_plan_blocks_before_first_node(tmp_path: Path) -> None:
    artifact = _compiled_graph(tmp_path)
    _prepare_evidence(tmp_path)
    provider = _PlanningProvider(invalid=True)
    service, storage, calls = _service(tmp_path, provider)

    with pytest.raises(PlanningPrerequisiteError):
        service.start(
            artifact,
            execution_id="exec-plan-invalid",
            initial_input=_envelope(),
            configuration={},
        )

    assert storage.load_execution("exec-plan-invalid").current_state == (
        ExecutionState.BLOCKED_PREREQUISITE
    )
    assert calls == []
    assert tuple(event.event_type for event in _planning_events(storage, "exec-plan-invalid")) == (
        PLAN_GENERATION_STARTED,
    )


def test_plan_payload_persistence_failure_blocks_before_first_node(tmp_path: Path) -> None:
    artifact = _compiled_graph(tmp_path)
    _prepare_evidence(tmp_path)
    provider = _PlanningProvider()
    storage = _FailPlanPayloadStorage(tmp_path)
    service, _, calls = _service(tmp_path, provider, storage=storage)

    with pytest.raises(PlanningPrerequisiteError):
        service.start(
            artifact,
            execution_id="exec-plan-persistence",
            initial_input=_envelope(),
            configuration={},
        )

    assert storage.load_execution("exec-plan-persistence").current_state == (
        ExecutionState.BLOCKED_PREREQUISITE
    )
    assert calls == []
    assert provider.calls == 1


def test_missing_compiled_planning_policy_blocks_before_provider_and_node(
    tmp_path: Path,
) -> None:
    artifact = _compiled_graph(tmp_path, include_planning_policies=False)
    _prepare_evidence(tmp_path)
    provider = _PlanningProvider()
    service, storage, calls = _service(tmp_path, provider)

    with pytest.raises(PlanningPrerequisiteError):
        service.start(
            artifact,
            execution_id="exec-plan-missing-policy",
            initial_input=_envelope(),
            configuration={},
        )

    assert storage.load_execution("exec-plan-missing-policy").current_state == (
        ExecutionState.BLOCKED_PREREQUISITE
    )
    assert provider.calls == 0
    assert calls == []


def test_planning_budget_denial_is_terminal_and_resume_has_no_provider_effect(
    tmp_path: Path,
) -> None:
    artifact = _compiled_graph(tmp_path)
    _prepare_evidence(tmp_path)
    provider = _PlanningProvider()
    service, storage, calls = _service(tmp_path, provider)
    execution_id = "exec-plan-budget-denied"

    with pytest.raises(ExecutionBudgetExceededError):
        service.start(
            artifact,
            execution_id=execution_id,
            initial_input=_envelope(),
            configuration={
                "budget": {
                    "max_tokens": 5,
                    "max_prompt_tokens": 5,
                    "max_completion_tokens": 5,
                }
            },
        )

    assert provider.calls == 0
    assert calls == []
    assert storage.load_execution(execution_id).current_state == (
        ExecutionState.FAILED_BUDGET_EXCEEDED
    )
    status = service.status(execution_id)
    inspection = service.inspect(execution_id)
    assert status.budget is not None and status.budget.is_exceeded
    assert inspection.status.budget == status.budget
    with pytest.raises(ExecutionBudgetExceededError):
        service.resume(execution_id)
    assert provider.calls == 0
