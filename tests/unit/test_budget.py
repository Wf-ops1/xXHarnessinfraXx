from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from ai_engineering_harness.contracts.events.execution_event import ExecutionEvent
from ai_engineering_harness.governance import (
    BUDGET_COMMITTED,
    BUDGET_EXCEEDED,
    BUDGET_RESERVED,
    BudgetIntegrityError,
    BudgetLedger,
    BudgetLimits,
    BudgetPriceUnavailableError,
    BudgetReservationAmbiguousError,
    BudgetTracker,
    DurableBudgetExceededError,
    JournalBudgetBoundary,
)
from ai_engineering_harness.models.provider import (
    CancellationToken,
    LLMResponse,
    ProviderTimeoutError,
)
from ai_engineering_harness.models.router import (
    ModelResponseBudgetExceededError,
    ModelRouter,
)
from ai_engineering_harness.persistence import ExecutionLock

_BASE_TIME = datetime(2026, 8, 13, 18, 0, tzinfo=UTC)


class _MemoryStorage:
    def __init__(self) -> None:
        self.events: list[ExecutionEvent] = []

    def load_events(self, execution_id: str, *, lock: ExecutionLock | None = None):
        del lock
        return tuple(event for event in self.events if event.execution_id == execution_id)

    def append_event(
        self,
        execution_id: str,
        event: ExecutionEvent,
        *,
        lock: ExecutionLock | None = None,
    ) -> ExecutionEvent:
        del lock
        assert event.execution_id == execution_id
        self.events.append(event)
        return event

    # The remaining methods make this sentinel satisfy the runtime-checkable
    # ResumeStateStorageProvider. These paths are deliberately not exercised.
    def create_execution(self, record: Any):  # pragma: no cover
        raise NotImplementedError

    def load_execution(self, execution_id: str, *, lock: Any = None):  # pragma: no cover
        raise NotImplementedError

    def compare_and_set_execution(self, *args: Any, **kwargs: Any):  # pragma: no cover
        raise NotImplementedError

    def list_executions(self):  # pragma: no cover
        raise NotImplementedError

    def acquire_execution_lock(self, *args: Any, **kwargs: Any):  # pragma: no cover
        raise NotImplementedError

    def release_execution_lock(self, lock: Any):  # pragma: no cover
        raise NotImplementedError

    def create_execution_bundle(self, *args: Any, **kwargs: Any):  # pragma: no cover
        raise NotImplementedError

    def load_execution_bundle(self, *args: Any, **kwargs: Any):  # pragma: no cover
        raise NotImplementedError

    def store_payload(self, *args: Any, **kwargs: Any):  # pragma: no cover
        raise NotImplementedError

    def load_payload(self, *args: Any, **kwargs: Any):  # pragma: no cover
        raise NotImplementedError


class _Ticks:
    def __init__(self, *values: float) -> None:
        self._values = iter(values)

    def __call__(self) -> float:
        return next(self._values)


class _EventIds:
    def __init__(self) -> None:
        self._value = 0

    def __call__(self) -> str:
        self._value += 1
        return f"budget-event-{self._value}"


def _config(
    *,
    max_tokens: int = 100,
    max_cost_usd: str | None = None,
    with_price: bool = True,
) -> dict[str, object]:
    return {
        "budget": {
            "max_tokens": max_tokens,
            "max_prompt_tokens": max_tokens,
            "max_completion_tokens": max_tokens,
            "max_tool_calls": 5,
            "max_duration_ms": 1_000,
            "max_attempts": 3,
            "max_cost_usd": max_cost_usd,
            "max_completion_tokens_per_call": 5,
            "default_node_limits": {},
            "node_limits": {},
            "model_prices": (
                {
                    "local:llama3": {
                        "prompt_per_million_usd": "1",
                        "completion_per_million_usd": "2",
                    }
                }
                if with_price
                else {}
            ),
            "tool_prices_usd": {"read_file": "0.01"},
        }
    }


def _lock() -> ExecutionLock:
    return ExecutionLock(
        lock_id="lock-1",
        execution_id="exec-budget",
        owner_id="unit-test",
        fencing_token=7,
        acquired_at=_BASE_TIME,
    )


def _boundary(
    storage: _MemoryStorage,
    limits: BudgetLimits,
    *,
    ticks: tuple[float, ...] = (10.0, 10.025),
) -> JournalBudgetBoundary:
    return JournalBudgetBoundary(
        storage=storage,  # type: ignore[arg-type]
        lock=_lock(),
        execution_id="exec-budget",
        node_id="node-a",
        attempt=1,
        limits=limits,
        event_id_factory=_EventIds(),
        clock=lambda: _BASE_TIME,
        monotonic=_Ticks(*ticks),
    )


def _response(*, prompt: int = 2, completion: int = 3) -> LLMResponse:
    return LLMResponse(
        content="ok",
        provider="local",
        model_name="llama3",
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=prompt + completion,
        response_id="response-1",
    )


def test_legacy_tracker_remains_compatible() -> None:
    tracker = BudgetTracker(max_tokens=5)
    tracker.add_tokens(3)
    assert tracker.remaining_tokens == 2
    assert tracker.consumed_tokens == 3


def test_limits_are_strict_frozen_and_decimal_canonical() -> None:
    limits = BudgetLimits.from_effective_config(_config(max_cost_usd="1.25"))
    assert limits.execution.max_cost_usd is not None
    assert limits.model_dump(mode="json")["execution"]["max_cost_usd"] == "1.25"
    assert limits.canonical_json() == limits.canonical_json()
    with pytest.raises(ValidationError):
        limits.execution.max_total_tokens = 1  # type: ignore[misc]


def test_model_reservation_commit_and_restart_reconstruct_same_balance() -> None:
    storage = _MemoryStorage()
    limits = BudgetLimits.from_effective_config(_config())
    boundary = _boundary(storage, limits)

    handle = boundary.reserve_model("local", "llama3", "abc")
    assert [event.event_type for event in storage.events] == [BUDGET_RESERVED]
    commit = boundary.commit_model(handle, _response())

    assert [event.event_type for event in storage.events] == [
        BUDGET_RESERVED,
        BUDGET_COMMITTED,
    ]
    assert commit.actual.duration_ms == 25
    assert commit.snapshot.usage.prompt_tokens == 2
    assert commit.snapshot.usage.completion_tokens == 3
    assert commit.snapshot.usage.total_tokens == 5
    assert commit.snapshot.usage.estimated_cost_usd is not None
    assert str(commit.snapshot.usage.estimated_cost_usd) == "0.000008"
    restarted = BudgetLedger.replay("exec-budget", limits, tuple(storage.events)).snapshot()
    assert restarted == commit.snapshot


def test_tool_dispatch_usage_has_count_duration_and_known_cost() -> None:
    storage = _MemoryStorage()
    limits = BudgetLimits.from_effective_config(_config())
    boundary = _boundary(storage, limits, ticks=(20.0, 20.004))
    handle = boundary.reserve_tool("read_file")
    commit = boundary.commit_tool(handle, succeeded=False)
    assert commit.actual.tool_calls == 1
    assert commit.actual.duration_ms == 4
    assert str(commit.snapshot.usage.estimated_cost_usd) == "0.01"


def test_conservative_estimate_denies_before_reservation() -> None:
    storage = _MemoryStorage()
    limits = BudgetLimits.from_effective_config(_config(max_tokens=5))
    boundary = _boundary(storage, limits, ticks=())
    with pytest.raises(DurableBudgetExceededError) as caught:
        boundary.reserve_model("local", "llama3", "abc")
    assert "total_tokens" in caught.value.dimensions
    assert [event.event_type for event in storage.events] == [BUDGET_EXCEEDED]


def test_monetary_limit_without_price_denies_before_reservation() -> None:
    storage = _MemoryStorage()
    limits = BudgetLimits.from_effective_config(
        _config(max_cost_usd="2", with_price=False)
    )
    boundary = _boundary(storage, limits, ticks=())
    with pytest.raises(BudgetPriceUnavailableError):
        boundary.reserve_model("local", "llama3", "abc")
    assert [event.event_type for event in storage.events] == [BUDGET_EXCEEDED]


def test_node_override_is_checked_independently_from_execution_balance() -> None:
    configuration = _config(max_tokens=100)
    budget = configuration["budget"]
    assert isinstance(budget, dict)
    budget["node_limits"] = {"node-a": {"max_total_tokens": 5}}
    storage = _MemoryStorage()
    boundary = _boundary(
        storage,
        BudgetLimits.from_effective_config(configuration),
        ticks=(),
    )
    with pytest.raises(DurableBudgetExceededError) as caught:
        boundary.reserve_model("local", "llama3", "a")
    assert caught.value.scope == "node"
    assert caught.value.dimensions == ("total_tokens",)


def test_actual_overage_is_committed_exactly_once_before_exceeded_evidence() -> None:
    storage = _MemoryStorage()
    limits = BudgetLimits.from_effective_config(_config(max_tokens=10))
    boundary = _boundary(storage, limits)
    handle = boundary.reserve_model("local", "llama3", "a")
    commit = boundary.commit_model(handle, _response(prompt=7, completion=6))
    assert commit.snapshot.usage.total_tokens == 13
    assert commit.exceeded
    assert [event.event_type for event in storage.events] == [
        BUDGET_RESERVED,
        BUDGET_COMMITTED,
        BUDGET_EXCEEDED,
    ]


def test_unresolved_reservation_blocks_a_new_effect_after_restart() -> None:
    storage = _MemoryStorage()
    limits = BudgetLimits.from_effective_config(_config())
    _boundary(storage, limits).reserve_model("local", "llama3", "abc")
    restarted = _boundary(storage, limits, ticks=())
    with pytest.raises(BudgetReservationAmbiguousError):
        restarted.reserve_tool("read_file")


def test_result_without_reservation_and_tampered_identity_fail_replay() -> None:
    storage = _MemoryStorage()
    limits = BudgetLimits.from_effective_config(_config())
    boundary = _boundary(storage, limits)
    handle = boundary.reserve_model("local", "llama3", "abc")
    boundary.commit_model(handle, _response())
    committed = storage.events[1]
    storage.events = [committed]
    with pytest.raises(BudgetIntegrityError):
        BudgetLedger.replay("exec-budget", limits, tuple(storage.events))

    storage = _MemoryStorage()
    boundary = _boundary(storage, limits)
    boundary.reserve_model("local", "llama3", "abc")
    payload = dict(storage.events[0].payload)
    payload["operation_id"] = "forged"
    storage.events[0] = storage.events[0].model_copy(update={"payload": payload})
    with pytest.raises(BudgetIntegrityError):
        BudgetLedger.replay("exec-budget", limits, tuple(storage.events))


def test_persisted_limits_digest_cannot_change_on_restart() -> None:
    storage = _MemoryStorage()
    limits = BudgetLimits.from_effective_config(_config())
    boundary = _boundary(storage, limits)
    handle = boundary.reserve_model("local", "llama3", "abc")
    boundary.commit_model(handle, _response())
    changed = BudgetLimits.from_effective_config(_config(max_tokens=101))
    with pytest.raises(BudgetIntegrityError, match="limits digest"):
        BudgetLedger.replay("exec-budget", changed, tuple(storage.events))


def test_historical_events_without_budget_evidence_remain_readable() -> None:
    limits = BudgetLimits.from_effective_config(_config())
    events = (
        ExecutionEvent(
            event_id="event-1",
            execution_id="exec-budget",
            event_type="NODE_STARTED",
            timestamp=_BASE_TIME,
            payload={"node_id": "node-a", "attempt": 1},
        ),
        ExecutionEvent(
            event_id="event-2",
            execution_id="exec-budget",
            event_type="NODE_COMPLETED",
            timestamp=_BASE_TIME.replace(microsecond=50_000),
            payload={
                "node_id": "node-a",
                "attempt": 1,
                "model_calls": [
                    {
                        "response_id": "historic-response",
                        "prompt_tokens": 2,
                        "completion_tokens": 3,
                        "total_tokens": 5,
                    }
                ],
            },
        ),
    )
    snapshot = BudgetLedger.replay("exec-budget", limits, events).snapshot()
    assert snapshot.usage.attempts == 1
    assert snapshot.usage.duration_ms == 50
    assert snapshot.usage.total_tokens == 5
    assert snapshot.usage.estimated_cost_usd is None


def test_historical_prefix_remains_charged_after_new_budget_events() -> None:
    limits = BudgetLimits.from_effective_config(_config())
    storage = _MemoryStorage()
    storage.events.extend(
        (
            ExecutionEvent(
                event_id="historic-start",
                execution_id="exec-budget",
                event_type="NODE_STARTED",
                timestamp=_BASE_TIME,
                payload={"node_id": "node-a", "attempt": 1},
            ),
            ExecutionEvent(
                event_id="historic-complete",
                execution_id="exec-budget",
                event_type="NODE_COMPLETED",
                timestamp=_BASE_TIME.replace(microsecond=50_000),
                payload={
                    "node_id": "node-a",
                    "attempt": 1,
                    "model_calls": [
                        {
                            "response_id": "historic-response",
                            "prompt_tokens": 2,
                            "completion_tokens": 3,
                            "total_tokens": 5,
                        }
                    ],
                },
            ),
        )
    )
    boundary = _boundary(storage, limits)
    handle = boundary.reserve_model("local", "llama3", "abc")
    snapshot = boundary.commit_model(handle, _response()).snapshot

    assert snapshot.usage.attempts == 1
    assert snapshot.usage.duration_ms == 75
    assert snapshot.usage.total_tokens == 10
    assert snapshot.usage.unpriced_operations == 1


def test_semantically_tampered_committed_cost_fails_closed() -> None:
    storage = _MemoryStorage()
    limits = BudgetLimits.from_effective_config(_config())
    boundary = _boundary(storage, limits)
    handle = boundary.reserve_model("local", "llama3", "abc")
    boundary.commit_model(handle, _response())
    payload = dict(storage.events[1].payload)
    actual = dict(payload["actual"])
    actual["estimated_cost_usd"] = "0"
    payload["actual"] = actual
    storage.events[1] = storage.events[1].model_copy(update={"payload": payload})

    with pytest.raises(BudgetIntegrityError, match="semantically invalid"):
        BudgetLedger.replay("exec-budget", limits, tuple(storage.events))


def test_tool_outcome_must_match_its_preceding_budget_commit() -> None:
    storage = _MemoryStorage()
    limits = BudgetLimits.from_effective_config(_config())
    boundary = _boundary(storage, limits, ticks=(20.0, 20.004))
    handle = boundary.reserve_tool("read_file")
    storage.events.append(
        ExecutionEvent(
            event_id="tool-called",
            execution_id="exec-budget",
            event_type="TOOL_CALLED",
            timestamp=_BASE_TIME.replace(microsecond=1),
            payload={
                "node_id": "node-a",
                "attempt": 1,
                "call_id": "call-1",
                "tool_name": "read_file",
            },
        )
    )
    commit = boundary.commit_tool(handle, succeeded=True)
    storage.events.append(
        ExecutionEvent(
            event_id="tool-completed",
            execution_id="exec-budget",
            event_type="TOOL_COMPLETED",
            timestamp=_BASE_TIME.replace(microsecond=3),
            payload={
                "node_id": "node-a",
                "attempt": 1,
                "call_id": "call-1",
                "tool_name": "read_file",
                "duration_ms": commit.actual.duration_ms,
                "estimated_cost_usd": "0.01",
            },
        )
    )
    BudgetLedger.replay("exec-budget", limits, tuple(storage.events))

    payload = dict(storage.events[-1].payload)
    payload["duration_ms"] = 999
    storage.events[-1] = storage.events[-1].model_copy(update={"payload": payload})
    with pytest.raises(BudgetIntegrityError, match="committed budget result"):
        BudgetLedger.replay("exec-budget", limits, tuple(storage.events))


def test_attempt_limit_uses_existing_node_start_evidence() -> None:
    limits = BudgetLimits.from_effective_config(_config())
    events = tuple(
        ExecutionEvent(
            event_id=f"event-{attempt}",
            execution_id="exec-budget",
            event_type="NODE_STARTED",
            timestamp=_BASE_TIME.replace(microsecond=attempt),
            payload={"node_id": "node-a", "attempt": attempt},
        )
        for attempt in range(1, 4)
    )
    ledger = BudgetLedger.replay("exec-budget", limits, events)
    with pytest.raises(DurableBudgetExceededError) as caught:
        ledger.ensure_attempt("node-a", 4)
    assert caught.value.dimensions == ("attempts",)


class _ModelProvider:
    def __init__(
        self,
        provider_id: str,
        model_name: str,
        outcomes: list[LLMResponse | Exception],
    ) -> None:
        self.provider_id = provider_id
        self.model_name = model_name
        self.outcomes = outcomes
        self.transport_calls = 0

    def complete(self, prompt: str, **_: object) -> LLMResponse:
        del prompt
        self.transport_calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class _ModelRegistry:
    def __init__(self, providers: dict[str, _ModelProvider]) -> None:
        self.providers = providers

    def is_configured(self, provider_id: str) -> bool:
        return provider_id in self.providers

    def configured_model(self, provider_id: str) -> str:
        return self.providers[provider_id].model_name

    def create_provider(self, provider_id: str) -> _ModelProvider:
        return self.providers[provider_id]


def _router_with_boundary(
    storage: _MemoryStorage,
    providers: dict[str, _ModelProvider],
    *,
    limits: BudgetLimits | None = None,
) -> ModelRouter:
    boundary = _boundary(
        storage,
        limits or BudgetLimits.from_effective_config(_config()),
        ticks=(10.0, 10.001, 10.002, 10.003),
    )
    return ModelRouter(
        tuple(providers),
        provider_registry=_ModelRegistry(providers),  # type: ignore[arg-type]
        budget_boundary=boundary,
        default_primary_provider=next(iter(providers)),
        default_fallback_providers=tuple(providers)[1:],
    )


def test_router_reserves_before_transport_and_commits_response_once() -> None:
    storage = _MemoryStorage()
    provider = _ModelProvider("local", "llama3", [_response()])
    response = _router_with_boundary(storage, {"local": provider}).complete_with_fallback(
        "abc"
    )
    assert response.response_id == "response-1"
    assert provider.transport_calls == 1
    assert [event.event_type for event in storage.events] == [
        BUDGET_RESERVED,
        BUDGET_COMMITTED,
    ]


def test_router_cancellation_before_effect_has_no_reservation_or_charge() -> None:
    storage = _MemoryStorage()
    provider = _ModelProvider("local", "llama3", [_response()])
    token = CancellationToken()
    token.cancel()
    with pytest.raises(RuntimeError, match="cancelada"):
        _router_with_boundary(storage, {"local": provider}).complete_with_fallback(
            "abc",
            cancellation_token=token,
        )
    assert provider.transport_calls == 0
    assert storage.events == []


def test_router_actual_overage_blocks_fallback_after_committed_response() -> None:
    storage = _MemoryStorage()
    local_response = _response(prompt=7, completion=6)
    primary = _ModelProvider("local", "llama3", [local_response])
    fallback = _ModelProvider(
        "other",
        "other-model",
        [local_response.model_copy(update={"provider": "other", "response_id": "fallback"})],
    )
    limits = BudgetLimits.from_effective_config(_config(max_tokens=10))
    router = _router_with_boundary(
        storage,
        {"local": primary, "other": fallback},
        limits=limits,
    )
    with pytest.raises(ModelResponseBudgetExceededError) as caught:
        router.complete_with_fallback("a")
    assert caught.value.response.total_tokens == 13
    assert primary.transport_calls == 1
    assert fallback.transport_calls == 0
    assert [event.event_type for event in storage.events] == [
        BUDGET_RESERVED,
        BUDGET_COMMITTED,
        BUDGET_EXCEEDED,
    ]


def test_router_closes_failed_reservation_before_transient_fallback() -> None:
    storage = _MemoryStorage()
    primary = _ModelProvider(
        "local",
        "llama3",
        [ProviderTimeoutError("timeout", provider_id="local")],
    )
    response = _response().model_copy(
        update={"provider": "other", "model_name": "other-model", "response_id": "other-1"}
    )
    fallback = _ModelProvider("other", "other-model", [response])
    result = _router_with_boundary(
        storage,
        {"local": primary, "other": fallback},
        limits=BudgetLimits.from_effective_config(_config()),
    ).complete_with_fallback("abc")
    assert result.response_id == "other-1"
    assert primary.transport_calls == fallback.transport_calls == 1
    assert [event.event_type for event in storage.events] == [
        BUDGET_RESERVED,
        BUDGET_COMMITTED,
        BUDGET_RESERVED,
        BUDGET_COMMITTED,
    ]
