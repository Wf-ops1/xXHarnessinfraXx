"""Focused F3.3 tests for the compiled-policy model tool loop."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from ai_engineering_harness.contracts import (
    ApprovalStatus,
    CompiledGraphArtifact,
    ContractRegistry,
    GraphSpec,
    PolicyRegistry,
    SourceManifestEntry,
)
from ai_engineering_harness.contracts.execution import ExecutionRecord, ExecutionState
from ai_engineering_harness.governance import (
    BudgetLedger,
    BudgetLimits,
    BudgetTracker,
    JournalBudgetBoundary,
)
from ai_engineering_harness.models import (
    CancellationToken,
    LLMResponse,
    ModelRouter,
    ModelToolConversation,
    ProviderTimeoutError,
    ToolCall,
)
from ai_engineering_harness.persistence import AtomicFileStateStorage
from ai_engineering_harness.runtime import (
    EffectiveToolPolicy,
    ToolApprovalRequiredError,
    ToolCallIntent,
    ToolEffectDurabilityError,
    ToolExecutionRecord,
    ToolLoopCancelledError,
    ToolLoopError,
    ToolLoopExecutionError,
    ToolLoopExecutor,
    ToolPolicyConfigurationError,
    ToolStepLimitExceededError,
)
from ai_engineering_harness.runtime.agent_executor import AgentExecutor
from ai_engineering_harness.tools import (
    ToolDefinition,
    ToolRegistration,
    ToolRouter,
    ToolUnauthorizedError,
    ToolUnavailableError,
)
from ai_engineering_harness.tools.adapters import CommandCancelledError, CommandResult

_CONTRACT = "ai_engineering_harness.contracts.nodes.context_sufficiency.RetrievalRequest"


class _ToolProvider:
    def __init__(self, provider_id: str, outcomes: list[LLMResponse | Exception]) -> None:
        self.provider_id = provider_id
        self.model_name = f"{provider_id}-model"
        self.outcomes = outcomes
        self.prompts: list[str] = []
        self.conversations: list[ModelToolConversation] = []
        self.schemas: list[list[dict[str, Any]]] = []

    def call_tools(
        self,
        prompt: str,
        tools: list[dict[str, Any]],
        **_: object,
    ) -> LLMResponse:
        self.prompts.append(prompt)
        self.schemas.append(tools)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def continue_tools(
        self,
        conversation: ModelToolConversation,
        tools: list[dict[str, Any]],
        **_: object,
    ) -> LLMResponse:
        self.conversations.append(conversation)
        self.schemas.append(tools)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class _Registry:
    def __init__(self, providers: dict[str, _ToolProvider]) -> None:
        self.providers = providers
        self.created: list[str] = []

    def is_configured(self, provider_id: str) -> bool:
        return provider_id in self.providers

    def create_provider(self, provider_id: str) -> _ToolProvider:
        self.created.append(provider_id)
        return self.providers[provider_id]

    def configured_model(self, provider_id: str) -> str:
        return self.providers[provider_id].model_name


class _MemoryRecorder:
    def __init__(self, trace: list[str] | None = None) -> None:
        self.intents: list[ToolCallIntent] = []
        self.outcomes: list[ToolExecutionRecord] = []
        self.trace = trace

    def record_call(self, intent: ToolCallIntent) -> None:
        self.intents.append(intent)
        if self.trace is not None:
            self.trace.append("called")

    def record_outcome(self, record: ToolExecutionRecord) -> None:
        self.outcomes.append(record)
        if self.trace is not None:
            self.trace.append("outcome")


def _response(
    *,
    provider: str = "local",
    content: str = "",
    calls: tuple[ToolCall, ...] = (),
    total_tokens: int = 3,
    index: int = 1,
) -> LLMResponse:
    return LLMResponse(
        content=content,
        provider=provider,
        model_name=f"{provider}-model",
        tool_calls=calls,
        prompt_tokens=2,
        completion_tokens=1,
        total_tokens=total_tokens,
        request_id=f"req-{index}",
        response_id=f"resp-{index}",
    )


def _call(
    *,
    call_id: str = "call-1",
    name: str = "knowledge_retriever",
    query: object = "routing",
) -> ToolCall:
    return ToolCall(call_id=call_id, name=name, arguments={"query": query})


def _artifact(*, allow_tool: bool = True) -> CompiledGraphArtifact:
    graph = GraphSpec.model_validate(
        {
            "graph": {
                "name": "tool-loop",
                "graph_schema_version": "1.0",
                "definition_version": "3.2.0",
                "entrypoint": "agent",
                "status": "stable",
            },
            "policies": ["policies/tool_policy.yaml"],
            "nodes": [
                {
                    "id": "agent",
                    "type": "agent",
                    "role": "requirement_analyst",
                    "input_contract": _CONTRACT,
                    "output_contract": _CONTRACT,
                    "tool_permissions": (
                        [{"tool": "knowledge_retriever", "effect": "allow"}]
                        if allow_tool
                        else []
                    ),
                    "on_success": "completed",
                    "on_failure": "failed",
                }
            ],
            "terminal_states": [
                {"id": "completed", "outcome": "success"},
                {"id": "failed", "outcome": "failure"},
            ],
        }
    )
    return CompiledGraphArtifact.build(
        graph=graph,
        resolved_contracts=ContractRegistry().resolve_many([_CONTRACT]),
        resolved_policies=PolicyRegistry().resolve_graph(graph),
        source_manifest=(
            SourceManifestEntry(
                source_kind="graph",
                source_id="project://tool-loop.yaml",
                content_digest=f"sha256:{'0' * 64}",
            ),
        ),
    )


def _tool_router(handler) -> ToolRouter:
    definition = ToolDefinition(
        name="knowledge_retriever",
        description="Retrieve deterministic test knowledge.",
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additionalProperties": False,
        },
    )
    return ToolRouter(
        allowed_tools=("knowledge_retriever",),
        registrations={
            "knowledge_retriever": ToolRegistration(
                definition=definition,
                handler=handler,
            )
        },
    )


def _loop(
    provider: _ToolProvider,
    tool_router: ToolRouter,
    *,
    max_steps: int = 3,
    budget: BudgetTracker | None = None,
) -> tuple[ToolLoopExecutor, ModelRouter]:
    registry = _Registry({"local": provider})
    router = ModelRouter(
        allowed_providers=("local",),
        provider_registry=registry,  # type: ignore[arg-type]
        budget_tracker=budget,
        default_primary_provider="local",
    )
    return (
        ToolLoopExecutor(router, tool_router, max_tool_steps=max_steps),
        router,
    )


def _execute(loop: ToolLoopExecutor, tool_router: ToolRouter, **kwargs):
    policy = EffectiveToolPolicy.from_artifact(_artifact(), "agent")
    kwargs.setdefault("tool_effect_recorder", _MemoryRecorder())
    return loop.execute(
        "system and user prompt",
        policy=policy,
        tool_schemas=tool_router.prepare(
            policy.allowed_tools,
            effective_denied_tools=policy.denied_tools,
        ),
        model_candidates=("local",),
        **kwargs,
    )


class _BudgetTicks:
    def __init__(self) -> None:
        self.value = 10.0

    def __call__(self) -> float:
        self.value += 0.001
        return self.value


class _BudgetEventIds:
    def __init__(self) -> None:
        self.value = 0

    def __call__(self) -> str:
        self.value += 1
        return f"tool-budget-event-{self.value}"


def _durable_boundary(tmp_path):
    execution_id = "exec-tool-budget"
    timestamp = datetime(2026, 8, 13, 21, 0, tzinfo=UTC)
    storage = AtomicFileStateStorage(tmp_path)
    storage.create_execution(
        ExecutionRecord(
            record_schema_version="1.0",
            revision=0,
            execution_id=execution_id,
            workflow_name="tool-loop",
            artifact_digest=f"sha256:{'0' * 64}",
            base_commit_sha="a" * 40,
            original_branch="test",
            worktree_path=None,
            current_node_id="agent",
            current_state=ExecutionState.EXECUTING,
            attempt_by_node={},
            created_at=timestamp,
            updated_at=timestamp,
            configuration_digest=f"sha256:{'1' * 64}",
            approval_status=ApprovalStatus.NOT_REQUIRED,
            candidate_commit_sha=None,
            promotion_commit_sha=None,
            failure=None,
        )
    )
    lock = storage.acquire_execution_lock(
        execution_id,
        "tool-budget-test",
        timeout_seconds=1,
    )
    limits = BudgetLimits.from_effective_config(
        {
            "budget": {
                "max_tokens": 1_000,
                "max_prompt_tokens": 1_000,
                "max_completion_tokens": 1_000,
                "max_tool_calls": 3,
                "max_duration_ms": 1_000,
                "max_attempts": 3,
                "max_completion_tokens_per_call": 5,
                "default_node_limits": {},
                "node_limits": {},
                "model_prices": {
                    "local:local-model": {
                        "prompt_per_million_usd": "1",
                        "completion_per_million_usd": "2",
                    }
                },
                "tool_prices_usd": {"knowledge_retriever": "0.01"},
            }
        }
    )
    clock_value = timestamp

    def clock() -> datetime:
        nonlocal clock_value
        clock_value += timedelta(microseconds=1)
        return clock_value

    boundary = JournalBudgetBoundary(
        storage=storage,
        lock=lock,
        execution_id=execution_id,
        graph_name="tool-loop",
        node_id="agent",
        attempt=1,
        limits=limits,
        event_id_factory=_BudgetEventIds(),
        clock=clock,
        monotonic=_BudgetTicks(),
    )
    return storage, lock, limits, boundary


def test_durable_boundary_covers_model_tool_and_continuation_in_one_ledger(
    tmp_path,
) -> None:
    effects: list[dict[str, object]] = []

    def handler(payload):
        effects.append(payload)
        return {"matches": ["F5.4"]}

    tool_router = _tool_router(handler)
    provider = _ToolProvider(
        "local",
        [
            _response(calls=(_call(),), index=1),
            _response(content="final", index=2),
        ],
    )
    storage, lock, limits, boundary = _durable_boundary(tmp_path)
    try:
        router = ModelRouter(
            allowed_providers=("local",),
            provider_registry=_Registry({"local": provider}),  # type: ignore[arg-type]
            budget_boundary=boundary,
            default_primary_provider="local",
        )
        loop = ToolLoopExecutor(router, tool_router, max_tool_steps=3)
        result = _execute(
            loop,
            tool_router,
            budget_boundary=boundary,
            tool_effect_recorder=_MemoryRecorder(),
        )

        assert effects == [{"query": "routing"}]
        assert result.model_calls == 2
        assert result.tool_executions[0].duration_ms == 1
        assert result.tool_executions[0].estimated_cost_usd == "0.01"
        snapshot = BudgetLedger.replay(
            "exec-tool-budget",
            limits,
            storage.load_events("exec-tool-budget", lock=lock),
        ).snapshot()
        assert snapshot.usage.total_tokens == 6
        assert snapshot.usage.tool_calls == 1
        assert snapshot.nodes["agent"].usage == snapshot.usage
        assert tuple(
            event.event_type
            for event in storage.load_events("exec-tool-budget", lock=lock)
        ) == (
            "BUDGET_RESERVED",
            "BUDGET_COMMITTED",
            "BUDGET_RESERVED",
            "BUDGET_COMMITTED",
            "BUDGET_RESERVED",
            "BUDGET_COMMITTED",
        )
    finally:
        storage.release_execution_lock(lock)


def test_compiled_policy_tool_result_returns_to_model_and_final_response_stops() -> None:
    effects: list[dict[str, object]] = []

    def handler(payload):
        effects.append(payload)
        return {"matches": ["F3.3"]}

    tool_router = _tool_router(handler)
    provider = _ToolProvider(
        "local",
        [
            _response(calls=(_call(),), index=1),
            _response(content="final answer", index=2),
        ],
    )
    loop, router = _loop(provider, tool_router)

    result = _execute(loop, tool_router)

    assert effects == [{"query": "routing"}]
    assert result.final_response.content == "final answer"
    assert result.model_calls == 2
    assert result.model_call.response_id == "resp-2"
    assert [call.response_id for call in result.model_call_records] == [
        "resp-1",
        "resp-2",
    ]
    assert router.budget_tracker.consumed_tokens == 6
    assert provider.schemas[0][0]["name"] == "knowledge_retriever"
    assert provider.prompts == ["system and user prompt"]
    assert len(provider.conversations) == 1
    continuation = provider.conversations[0]
    assert continuation.initial_prompt == "system and user prompt"
    assert continuation.turns[0].response.response_id == "resp-1"
    assert continuation.turns[0].tool_results[0].model_dump(mode="json") == {
        "call_id": "call-1",
        "name": "knowledge_retriever",
        "result": {"matches": ["F3.3"]},
    }
    assert result.tool_executions[0].arguments_digest.startswith("sha256:")
    assert result.tool_executions[0].redacted_result == '{"matches":["F3.3"]}'
    assert result.tool_executions[0].policy_decision_digest is not None


def test_durable_recorder_wraps_handler_in_write_ahead_order() -> None:
    trace: list[str] = []
    recorder = _MemoryRecorder(trace)

    def handler(payload):
        trace.append("handler")
        return payload

    tool_router = _tool_router(handler)
    provider = _ToolProvider(
        "local",
        [
            _response(calls=(_call(),), index=1),
            _response(content="done", index=2),
        ],
    )
    loop, _ = _loop(provider, tool_router)

    _execute(loop, tool_router, tool_effect_recorder=recorder)

    assert trace == ["called", "handler", "outcome"]
    assert (
        recorder.intents[0].arguments_digest
        == recorder.outcomes[0].arguments_digest
    )
    decision = recorder.intents[0].policy_decision
    assert decision is not None
    assert decision.allowed is True
    assert decision.rule_id.endswith(":allow:knowledge_retriever")
    assert decision.request.model_dump(mode="json") == {
        "role": "requirement_analyst",
        "node_id": "agent",
        "workflow": "tool-loop",
        "trust_mode": "restricted",
        "tool": "knowledge_retriever",
        "operation": "invoke",
        "path": None,
        "approval_granted": False,
    }
    assert recorder.outcomes[0].policy_decision_digest == decision.digest()


def test_missing_durable_recorder_blocks_handler() -> None:
    effects: list[object] = []
    tool_router = _tool_router(lambda payload: effects.append(payload))
    provider = _ToolProvider("local", [_response(calls=(_call(),))])
    loop, _ = _loop(provider, tool_router)
    policy = EffectiveToolPolicy.from_artifact(_artifact(), "agent")

    with pytest.raises(ToolEffectDurabilityError):
        loop.execute(
            "prompt",
            policy=policy,
            tool_schemas=tool_router.prepare(policy.allowed_tools),
            model_candidates=("local",),
        )

    assert effects == []


def test_policy_deny_overlap_and_human_approval_fail_closed() -> None:
    tool_router = _tool_router(lambda payload: payload)
    with pytest.raises(ToolUnauthorizedError):
        tool_router.prepare(
            ("knowledge_retriever",),
            effective_denied_tools=("knowledge_retriever",),
        )

    provider = _ToolProvider("local", [_response(content="must not run")])
    loop, _ = _loop(provider, tool_router)
    policy = EffectiveToolPolicy.from_artifact(_artifact(), "agent").model_copy(
        update={"human_approval_required": True}
    )
    with pytest.raises(ToolApprovalRequiredError):
        loop.execute(
            "prompt",
            policy=policy,
            tool_schemas=tool_router.prepare(policy.allowed_tools),
            model_candidates=("local",),
            tool_effect_recorder=_MemoryRecorder(),
        )
    assert provider.prompts == []


def test_router_without_registrations_has_no_synthetic_operational_tools() -> None:
    router = ToolRouter(allowed_tools=("serena_edit",))
    assert router.registered_tools == ()


def test_transient_model_failure_falls_back_within_one_tool_turn() -> None:
    primary = _ToolProvider(
        "openai",
        [ProviderTimeoutError("timeout", provider_id="openai")],
    )
    fallback = _ToolProvider("local", [_response(content="done")])
    registry = _Registry({"openai": primary, "local": fallback})
    router = ModelRouter(
        allowed_providers=("openai", "local"),
        provider_registry=registry,  # type: ignore[arg-type]
        default_primary_provider="openai",
        default_fallback_providers=("local",),
    )
    tool_router = _tool_router(lambda payload: payload)
    loop = ToolLoopExecutor(router, tool_router, max_tool_steps=1)
    policy = EffectiveToolPolicy.from_artifact(_artifact(), "agent")

    result = loop.execute(
        "prompt",
        policy=policy,
        tool_schemas=tool_router.prepare(policy.allowed_tools),
        model_candidates=("openai", "local"),
    )

    assert result.final_response.provider == "local"
    assert registry.created == ["openai", "local"]


def test_continuation_failure_preserves_completed_model_call_evidence() -> None:
    tool_router = _tool_router(lambda payload: payload)
    provider = _ToolProvider(
        "local",
        [
            _response(calls=(_call(),), index=1),
            ProviderTimeoutError("timeout", provider_id="local"),
        ],
    )
    loop, _ = _loop(provider, tool_router)

    with pytest.raises(ToolLoopError) as captured:
        _execute(loop, tool_router)

    assert [call.response_id for call in captured.value.model_call_records] == [
        "resp-1"
    ]
    assert len(captured.value.tool_executions) == 1
    assert provider.prompts == ["system and user prompt"]
    assert len(provider.conversations) == 1


def test_cancel_after_continuation_response_preserves_both_model_calls() -> None:
    token = CancellationToken()

    class _CancelAfterContinuationProvider(_ToolProvider):
        def continue_tools(
            self,
            conversation: ModelToolConversation,
            tools: list[dict[str, Any]],
            **kwargs: object,
        ) -> LLMResponse:
            response = super().continue_tools(conversation, tools, **kwargs)
            token.cancel()
            return response

    tool_router = _tool_router(lambda payload: payload)
    provider = _CancelAfterContinuationProvider(
        "local",
        [
            _response(calls=(_call(),), index=1),
            _response(content="cancelled final", index=2),
        ],
    )
    loop, router = _loop(provider, tool_router)

    with pytest.raises(ToolLoopError) as captured:
        _execute(loop, tool_router, cancellation_token=token)

    assert [call.response_id for call in captured.value.model_call_records] == [
        "resp-1",
        "resp-2",
    ]
    assert len(captured.value.tool_executions) == 1
    assert router.budget_tracker.consumed_tokens == 3


@pytest.mark.parametrize(
    "calls",
    [
        (_call(name="terminal_executor"),),
        (_call(query=7),),
        (_call(call_id="same"), _call(call_id="same")),
    ],
)
def test_unauthorized_schema_or_duplicate_batch_has_zero_effect(calls) -> None:
    effects: list[object] = []
    tool_router = _tool_router(lambda payload: effects.append(payload))
    provider = _ToolProvider("local", [_response(calls=calls)])
    loop, _ = _loop(provider, tool_router)

    with pytest.raises(ToolLoopError):
        _execute(loop, tool_router)

    assert effects == []
    assert len(provider.prompts) == 1


def test_default_denied_call_rejects_whole_valid_batch_before_first_effect() -> None:
    effects: list[str] = []
    schema = {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
        "additionalProperties": False,
    }
    tool_router = ToolRouter(
        allowed_tools=("knowledge_retriever", "unplanned_tool"),
        registrations={
            name: ToolRegistration(
                definition=ToolDefinition(
                    name=name,
                    description=f"test {name}",
                    parameters=schema,
                ),
                handler=lambda _payload, selected=name: effects.append(selected),
            )
            for name in ("knowledge_retriever", "unplanned_tool")
        },
    )
    provider = _ToolProvider(
        "local",
        [
            _response(
                calls=(
                    _call(call_id="allowed"),
                    _call(call_id="denied", name="unplanned_tool"),
                )
            )
        ],
    )
    loop, _ = _loop(provider, tool_router)

    with pytest.raises(ToolLoopError, match="preflight") as captured:
        _execute(loop, tool_router)

    assert effects == []
    assert isinstance(captured.value.__cause__, PermissionError)


def test_unregistered_compiled_capability_fails_before_model_call() -> None:
    provider = _ToolProvider("local", [_response(content="must not run")])
    empty_router = ToolRouter(allowed_tools=("knowledge_retriever",), registrations={})
    _loop(provider, empty_router)
    policy = EffectiveToolPolicy.from_artifact(_artifact(), "agent")

    with pytest.raises(ToolUnavailableError):
        empty_router.prepare(policy.allowed_tools)

    assert provider.prompts == []


def test_agent_preflight_rejects_unregistered_tool_before_composing_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _ToolProvider("local", [_response(content="must not run")])
    registry = _Registry({"local": provider})
    model_router = ModelRouter(
        allowed_providers=("local",),
        provider_registry=registry,  # type: ignore[arg-type]
    )
    empty_router = ToolRouter(allowed_tools=("knowledge_retriever",), registrations={})
    executor = AgentExecutor("Sally", model_router, tool_router=empty_router)
    composed = False

    def compose(_: str) -> str:
        nonlocal composed
        composed = True
        return "must-not-compose"

    monkeypatch.setattr(executor, "_compose_prompt", compose)

    with pytest.raises(ToolUnavailableError):
        executor.execute_tool_loop(
            "sensitive",
            artifact=_artifact(),
            node_id="agent",
            max_tool_steps=1,
        )

    assert composed is False
    assert provider.prompts == []


def test_limit_rejects_whole_batch_before_first_effect() -> None:
    effects: list[object] = []
    tool_router = _tool_router(lambda payload: effects.append(payload))
    provider = _ToolProvider(
        "local",
        [_response(calls=(_call(call_id="one"), _call(call_id="two")))],
    )
    loop, _ = _loop(provider, tool_router, max_steps=1)

    with pytest.raises(ToolStepLimitExceededError):
        _execute(loop, tool_router)

    assert effects == []


def test_budget_exhaustion_after_model_response_blocks_tool_effect() -> None:
    effects: list[object] = []
    tool_router = _tool_router(lambda payload: effects.append(payload))
    provider = _ToolProvider("local", [_response(calls=(_call(),), total_tokens=3)])
    loop, _ = _loop(provider, tool_router, budget=BudgetTracker(max_tokens=3))

    with pytest.raises(RuntimeError, match="BUDGET EXCEEDED"):
        _execute(loop, tool_router)

    assert effects == []


def test_budget_is_rechecked_before_each_dispatch_in_batch() -> None:
    effects: list[object] = []
    budget = BudgetTracker(max_tokens=10)

    def handler(payload):
        effects.append(payload)
        budget.add_tokens(7)
        return payload

    tool_router = _tool_router(handler)
    provider = _ToolProvider(
        "local",
        [
            _response(
                calls=(
                    _call(call_id="one"),
                    _call(call_id="two"),
                ),
                total_tokens=3,
            )
        ],
    )
    loop, _ = _loop(provider, tool_router, budget=budget)

    with pytest.raises(ToolLoopError, match="BUDGET EXCEEDED"):
        _execute(loop, tool_router)

    assert effects == [{"query": "routing"}]


def test_cancel_before_first_model_call_has_no_effect() -> None:
    effects: list[object] = []
    tool_router = _tool_router(lambda payload: effects.append(payload))
    provider = _ToolProvider("local", [_response(content="must not run")])
    loop, _ = _loop(provider, tool_router)
    token = CancellationToken()
    token.cancel()

    with pytest.raises(ToolLoopCancelledError):
        _execute(loop, tool_router, cancellation_token=token)

    assert provider.prompts == []
    assert effects == []


def test_cancellation_is_rechecked_before_each_dispatch_in_batch() -> None:
    effects: list[object] = []
    token = CancellationToken()

    def handler(payload):
        effects.append(payload)
        token.cancel()
        return payload

    tool_router = _tool_router(handler)
    provider = _ToolProvider(
        "local",
        [
            _response(
                calls=(
                    _call(call_id="one"),
                    _call(call_id="two"),
                )
            )
        ],
    )
    loop, _ = _loop(provider, tool_router)

    with pytest.raises(ToolLoopCancelledError):
        _execute(loop, tool_router, cancellation_token=token)

    assert effects == [{"query": "routing"}]


def test_cancelled_terminal_handler_records_failure_before_loop_cancellation() -> None:
    def cancelled(_: object) -> object:
        raise CommandCancelledError(
            CommandResult(
                argv=("python", "-V"),
                cwd_relative=".",
                exit_code=1,
                stdout="bounded evidence",
                stderr="",
                timed_out=False,
                cancelled=True,
                stdout_truncated=False,
                stderr_truncated=False,
            )
        )

    tool_router = _tool_router(cancelled)
    provider = _ToolProvider("local", [_response(calls=(_call(),))])
    loop, _ = _loop(provider, tool_router)
    recorder = _MemoryRecorder()

    with pytest.raises(ToolLoopCancelledError) as captured:
        _execute(loop, tool_router, tool_effect_recorder=recorder)

    assert len(captured.value.tool_executions) == 1
    failure = captured.value.tool_executions[0]
    assert not failure.succeeded
    assert failure.error_code == "ToolExecutionCancelledError"
    assert recorder.outcomes == [failure]
    assert len(provider.prompts) == 1
    assert provider.conversations == []


def test_tool_error_stops_without_another_model_call_and_carries_failed_record() -> None:
    def fail(_: object) -> object:
        raise OSError("token=must-not-persist")

    tool_router = _tool_router(fail)
    provider = _ToolProvider("local", [_response(calls=(_call(),))])
    loop, _ = _loop(provider, tool_router)

    with pytest.raises(ToolLoopExecutionError) as captured:
        _execute(loop, tool_router)

    assert len(provider.prompts) == 1
    assert len(captured.value.tool_executions) == 1
    assert [call.response_id for call in captured.value.model_call_records] == [
        "resp-1"
    ]
    record = captured.value.tool_executions[0]
    assert record.succeeded is False
    assert record.error_code == "ToolExecutionError"
    assert "must-not-persist" not in record.redacted_result


def test_policy_extraction_rejects_non_agent_or_missing_decision() -> None:
    with pytest.raises(ToolPolicyConfigurationError):
        EffectiveToolPolicy.from_artifact(_artifact(), "missing")

    denied = EffectiveToolPolicy.from_artifact(_artifact(allow_tool=False), "agent")
    assert denied.allowed_tools == ()
