"""Schemas de eventos de execução e sincronização de conhecimento."""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from ai_engineering_harness.security import Redactor

from ..execution import ExecutionId
from .event_types import NODE_SCOPED_EVENT_TYPES, EventType

EXECUTION_EVENT_SCHEMA_VERSION = "2.0"

_NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ExecutionEvent(BaseModel):
    """Strict, redacted envelope used by every canonical execution event."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    event_schema_version: Annotated[
        str,
        StringConstraints(pattern=r"^2\.0$"),
    ] = EXECUTION_EVENT_SCHEMA_VERSION
    event_id: ExecutionId = Field(description="Identificador único do evento")
    execution_id: ExecutionId = Field(description="ID da execução vinculada")
    sequence_number: int = Field(
        ge=0,
        description="Posição no journal; zero identifica somente um draft pré-append",
    )
    event_type: EventType = Field(description="Tipo fechado do evento operacional")
    timestamp: datetime = Field(description="Timestamp ISO do evento")
    graph_name: _NonEmptyStr = Field(description="Nome canônico do grafo/workflow")
    node_id: _NonEmptyStr | None = Field(
        default=None,
        description="Nó relacionado, quando o evento é node-scoped",
    )
    attempt: int = Field(ge=0, description="Tentativa relacionada; zero quando não aplicável")
    actor: _NonEmptyStr = Field(description="Subsistema ou ator que produziu o evento")
    details: dict[str, Any] = Field(
        validation_alias=AliasChoices("details", "payload"),
        description="Detalhes JSON-native redigidos antes da persistência",
    )
    previous_hash: _NonEmptyStr | None = Field(
        default=None,
        description="SHA-256 do evento anterior no Hash Chain",
    )
    current_hash: _NonEmptyStr | None = Field(
        default=None,
        description="SHA-256 deste evento encadeado",
    )

    @field_validator("timestamp")
    @classmethod
    def require_utc_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("event timestamp must be timezone-aware UTC")
        if value.utcoffset() != timedelta(0):
            raise ValueError("event timestamp must use UTC")
        return value.astimezone(UTC)

    @field_validator("event_type", mode="before")
    @classmethod
    def require_known_event_type(cls, value: object) -> EventType:
        if isinstance(value, EventType):
            return value
        if type(value) is not str:
            raise TypeError("event_type must be a canonical event type string")
        try:
            return EventType(value)
        except ValueError as exc:
            raise ValueError(f"unknown canonical event_type: {value!r}") from exc

    @field_validator("details", mode="before")
    @classmethod
    def require_redacted_json_native_details(cls, value: object) -> object:
        redacted = _redact_event_json(value)
        copied = _copy_json_native(redacted, path="details")
        if not isinstance(copied, dict):
            raise TypeError("event details must be a JSON object")
        return copied

    @model_validator(mode="after")
    def require_scoped_metadata(self) -> ExecutionEvent:
        if self.event_type in NODE_SCOPED_EVENT_TYPES:
            if self.node_id is None:
                raise ValueError("node-scoped events require node_id")
            if self.attempt < 1:
                raise ValueError("node-scoped events require a positive attempt")
        return self

    @property
    def payload(self) -> dict[str, Any]:
        """Compatibility read alias; canonical serialization uses ``details``."""

        return self.details

    def canonical_json(self) -> str:
        """Serialize the envelope as one compact canonical journal line."""
        try:
            serialized = json.dumps(
                self.model_dump(mode="json"),
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        except (TypeError, ValueError) as exc:
            raise ValueError(f"event cannot be serialized as canonical JSON: {exc}") from exc
        return serialized + "\n"


def _copy_json_native(value: object, *, path: str) -> object:
    if value is None or type(value) in {bool, int, str}:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError(f"{path} contains a non-finite number")
        return value
    if type(value) is list:
        return [
            _copy_json_native(item, path=f"{path}[{index}]")
            for index, item in enumerate(value)
        ]
    if type(value) is dict:
        copied: dict[str, object] = {}
        for key, item in value.items():
            if type(key) is not str:
                raise ValueError(f"{path} contains a non-string object key")
            copied[key] = _copy_json_native(item, path=f"{path}.{key}")
        return copied
    raise ValueError(f"{path} contains non-JSON-native value {type(value).__name__}")


def _redact_event_json(value: object) -> object:
    """Redact secret-bearing text without destroying numeric control metadata."""

    if isinstance(value, str):
        return Redactor.redact_text(value)
    if value is None or type(value) in {bool, int, float}:
        return value
    if type(value) is list:
        return [_redact_event_json(item) for item in value]
    if type(value) is dict:
        redacted: dict[str, object] = {}
        for key, item in value.items():
            if type(key) is not str:
                raise TypeError("event detail keys must be strings")
            safe_key = Redactor.redact_text(key)
            probe = Redactor.redact_json({key: "event-redaction-probe"})
            sensitive_key = isinstance(probe, dict) and probe.get(safe_key) != "event-redaction-probe"
            if sensitive_key:
                redacted[safe_key] = "[REDACTED_SECRET]"
            else:
                redacted[safe_key] = _redact_event_json(item)
        return redacted
    return value

# Backward-compatible import name. It is intentionally the canonical envelope,
# never a second Pydantic event schema.
KnowledgeSyncEvent = ExecutionEvent
