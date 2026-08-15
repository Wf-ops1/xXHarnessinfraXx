"""Focused F6.1 regressions for the single canonical event envelope."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from ai_engineering_harness.contracts import registry as contract_registry
from ai_engineering_harness.contracts.events import (
    CANONICAL_EVENT_TYPES,
    EXECUTION_EVENT_SCHEMA_VERSION,
    MINIMUM_EVENT_TYPES,
    EventType,
    ExecutionEvent,
    KnowledgeSyncEvent,
    KnowledgeUpdateEvent,
)
from ai_engineering_harness.observability.event_schema import HarnessTraceEvent

_REQUIRED_FIELDS = {
    "event_id",
    "execution_id",
    "sequence_number",
    "event_type",
    "timestamp",
    "graph_name",
    "node_id",
    "attempt",
    "actor",
    "details",
    "previous_hash",
    "current_hash",
}

_MINIMUM_VALUES = {
    "EXECUTION_CREATED",
    "WORKSPACE_CREATED",
    "CONTEXT_ASSEMBLED",
    "CONTEXT_BLOCKED",
    "PLAN_CREATED",
    "NODE_STARTED",
    "NODE_COMPLETED",
    "NODE_FAILED",
    "MODEL_REQUEST_COMPLETED",
    "MODEL_REQUEST_FAILED",
    "TOOL_AUTHORIZED",
    "TOOL_DENIED",
    "TOOL_STARTED",
    "TOOL_COMPLETED",
    "GATE_STARTED",
    "GATE_COMPLETED",
    "RETRY_SCHEDULED",
    "APPROVAL_REQUESTED",
    "APPROVAL_GRANTED",
    "APPROVAL_REJECTED",
    "APPROVAL_EXPIRED",
    "PROMOTION_STARTED",
    "PROMOTION_COMPLETED",
    "PROMOTION_FAILED",
    "KNOWLEDGE_SYNC",
    "EXECUTION_COMPLETED",
    "EXECUTION_FAILED",
    "EXECUTION_CANCELLED",
    "ROLLBACK_REQUESTED",
    "ROLLBACK_COMPLETED",
    "ROLLBACK_FAILED",
}


def _event(**overrides: object) -> ExecutionEvent:
    data: dict[str, object] = {
        "event_id": "event-f6-1",
        "execution_id": "exec-f6-1",
        "sequence_number": 0,
        "event_type": "NODE_STARTED",
        "timestamp": datetime(2026, 8, 15, tzinfo=UTC),
        "graph_name": "new-feature",
        "node_id": "implementation",
        "attempt": 1,
        "actor": "graph_executor",
        "details": {"node_id": "implementation", "attempt": 1},
        "previous_hash": None,
        "current_hash": None,
    }
    if "payload" in overrides:
        data.pop("details")
    data.update(overrides)
    return ExecutionEvent.model_validate(data)


def test_single_schema_has_versioned_f6_envelope_and_legacy_identity() -> None:
    assert HarnessTraceEvent is ExecutionEvent
    assert KnowledgeSyncEvent is ExecutionEvent
    assert KnowledgeUpdateEvent is ExecutionEvent
    assert EXECUTION_EVENT_SCHEMA_VERSION == "2.0"
    assert _REQUIRED_FIELDS <= set(ExecutionEvent.model_fields)

    event = _event(payload={"node_id": "implementation", "attempt": 1})
    document = json.loads(event.canonical_json())
    assert document["event_schema_version"] == "2.0"
    assert document["details"] == {"attempt": 1, "node_id": "implementation"}
    assert "payload" not in document
    assert event.payload == event.details


def test_registry_contains_no_independent_operational_event_model() -> None:
    event_models = {
        model
        for model in contract_registry._INTERNAL_MODELS
        if model.__name__.endswith("Event")
    }
    assert event_models == {ExecutionEvent}

    registry = contract_registry.ContractRegistry()
    assert not any(
        name.endswith(("KnowledgeSyncEvent", "KnowledgeUpdateEvent"))
        for name in registry.available_contracts
    )
    for alias in (
        "contracts/events/knowledge_sync.py#KnowledgeSyncCompleted",
        "contracts/events/knowledge_sync.py#KnowledgeSyncFailed",
    ):
        assert registry.resolve(alias).canonical_name.endswith("Details")


def test_minimum_taxonomy_is_closed_and_contains_every_planned_event() -> None:
    assert _MINIMUM_VALUES == {event_type.value for event_type in MINIMUM_EVENT_TYPES}
    assert MINIMUM_EVENT_TYPES <= CANONICAL_EVENT_TYPES
    assert all(event_type.name == event_type.value for event_type in EventType)


def test_details_are_detached_json_native_and_redacted() -> None:
    source = {
        "password": "controlled visible value",
        "nested": {"apiKey": "another controlled value"},
    }
    event = _event(details=source)
    source["password"] = "caller mutation"

    assert event.details == {
        "password": "[REDACTED_SECRET]",
        "nested": {"apiKey": "[REDACTED_SECRET]"},
    }
    assert "controlled visible value" not in event.canonical_json()
    assert "another controlled value" not in event.canonical_json()


def test_every_value_under_a_sensitive_key_is_redacted() -> None:
    event = _event(
        details={
            "password": 1234,
            "apiKey": False,
            "privateKey": None,
            "deployToken": 1.5,
            "secret_tokens": 2,
        }
    )

    assert event.details == {
        "password": "[REDACTED_SECRET]",
        "apiKey": "[REDACTED_SECRET]",
        "privateKey": "[REDACTED_SECRET]",
        "deployToken": "[REDACTED_SECRET]",
        "secret_tokens": "[REDACTED_SECRET]",
    }
    serialized = event.canonical_json()
    assert '"password":1234' not in serialized
    assert '"apiKey":false' not in serialized


def test_numeric_control_metadata_is_not_mistaken_for_a_secret() -> None:
    event = _event(
        details={
            "fencing_token": 7,
            "remaining_tokens": 900,
            "model_total_tokens": 100,
            "token_count": 3,
            "deployToken": 42,
        }
    )

    assert event.details == {
        "fencing_token": 7,
        "remaining_tokens": 900,
        "model_total_tokens": 100,
        "token_count": 3,
        "deployToken": "[REDACTED_SECRET]",
    }


@pytest.mark.parametrize(
    "overrides",
    [
        {"event_schema_version": "1.0"},
        {"sequence_number": -1},
        {"event_type": "UNKNOWN_EVENT"},
        {"timestamp": datetime(2026, 8, 15, tzinfo=UTC).replace(tzinfo=None)},
        {"timestamp": datetime(2026, 8, 15, tzinfo=timezone(-timedelta(hours=3)))},
        {"graph_name": " "},
        {"node_id": None},
        {"attempt": 0},
        {"actor": " "},
        {"details": {"bad": float("nan")}},
        {"unexpected": True},
    ],
)
def test_invalid_or_ambiguous_envelope_fails_closed(overrides: dict[str, object]) -> None:
    with pytest.raises((TypeError, ValidationError, ValueError)):
        _event(**overrides)


def test_non_node_event_explicitly_uses_zero_attempt_and_no_node() -> None:
    event = _event(
        event_type="EXECUTION_CREATED",
        node_id=None,
        attempt=0,
        details={"workflow_name": "new-feature"},
    )
    assert event.node_id is None
    assert event.attempt == 0
