"""Canonical in-memory compatibility and durable execution budget accounting."""

from __future__ import annotations

import hashlib
import json
import math
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_CEILING, Decimal, InvalidOperation
from typing import Annotated, Any, Literal, Protocol, runtime_checkable

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_serializer,
    field_validator,
    model_validator,
)

from ai_engineering_harness.contracts.events import EventType, ExecutionEvent
from ai_engineering_harness.persistence import (
    ExecutionLock,
    ResumeStateStorageProvider,
)

BUDGET_RESERVED = "BUDGET_RESERVED"
BUDGET_COMMITTED = "BUDGET_COMMITTED"
BUDGET_RELEASED = "BUDGET_RELEASED"
BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
BUDGET_EVENT_TYPES = frozenset(
    {BUDGET_RESERVED, BUDGET_COMMITTED, BUDGET_RELEASED, BUDGET_EXCEEDED}
)

BudgetOperationKind = Literal["model", "tool"]
BudgetEvidenceKind = Literal["model", "tool", "attempt"]
BudgetOutcome = Literal["succeeded", "failed"]
BudgetScope = Literal["execution", "node"]
_NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
_DECIMAL_ZERO = Decimal(0)
_MILLION = Decimal(1_000_000)


class BudgetError(RuntimeError):
    """Base error for budget configuration, integrity, and enforcement."""


class BudgetExceededError(BudgetError):
    """Compatibility token error used by the legacy in-memory tracker."""

    def __init__(self, *, max_tokens: int, consumed_tokens: int) -> None:
        self.max_tokens = max_tokens
        self.consumed_tokens = consumed_tokens
        super().__init__(
            "[BUDGET EXCEEDED] Orçamento máximo de tokens excedido ou esgotado: "
            f"{consumed_tokens} >= {max_tokens}"
        )


class DurableBudgetError(BudgetError):
    """Base error for the canonical journal-backed budget."""


class BudgetConfigurationError(DurableBudgetError, ValueError):
    """Persisted effective limits or prices are invalid."""


class BudgetIntegrityError(DurableBudgetError):
    """Budget evidence is duplicated, out of order, or identity-divergent."""


class BudgetDurabilityError(DurableBudgetError):
    """A reservation or result could not be durably written."""


class BudgetReservationAmbiguousError(BudgetIntegrityError):
    """A write-ahead reservation has no canonical result."""


class DurableBudgetExceededError(DurableBudgetError):
    """A deterministic estimate or committed result exceeds a durable limit."""

    def __init__(
        self,
        message: str,
        *,
        dimensions: tuple[str, ...],
        scope: BudgetScope,
        node_id: str,
        operation_id: str,
    ) -> None:
        self.dimensions = dimensions
        self.scope = scope
        self.node_id = node_id
        self.operation_id = operation_id
        super().__init__(message)


class BudgetPriceUnavailableError(DurableBudgetExceededError):
    """A monetary ceiling cannot be enforced without an applicable price."""


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")


def _parse_decimal(value: object, *, field_name: str) -> Decimal:
    if isinstance(value, bool):
        raise TypeError(f"{field_name} must be a finite non-negative decimal")
    try:
        parsed = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a finite non-negative decimal") from exc
    if not parsed.is_finite() or parsed < 0:
        raise ValueError(f"{field_name} must be a finite non-negative decimal")
    return parsed


def _decimal_text(value: Decimal) -> str:
    if value == 0:
        return "0"
    normalized = value.normalize()
    return format(normalized, "f")


class ModelPrice(_StrictFrozenModel):
    """Decimal USD price per million prompt and completion tokens."""

    prompt_per_million_usd: Decimal
    completion_per_million_usd: Decimal

    @field_validator("prompt_per_million_usd", "completion_per_million_usd", mode="before")
    @classmethod
    def parse_prices(cls, value: object) -> Decimal:
        return _parse_decimal(value, field_name="model price")

    @field_serializer("prompt_per_million_usd", "completion_per_million_usd")
    def serialize_prices(self, value: Decimal) -> str:
        return _decimal_text(value)

    def estimate(self, *, prompt_tokens: int, completion_tokens: int) -> Decimal:
        return (
            Decimal(prompt_tokens) * self.prompt_per_million_usd
            + Decimal(completion_tokens) * self.completion_per_million_usd
        ) / _MILLION


class BudgetLimitSet(_StrictFrozenModel):
    """Material caps shared by an execution or overridden for one node."""

    max_prompt_tokens: int | None = Field(default=None, gt=0)
    max_completion_tokens: int | None = Field(default=None, gt=0)
    max_total_tokens: int | None = Field(default=None, gt=0)
    max_tool_calls: int | None = Field(default=None, gt=0)
    max_duration_ms: int | None = Field(default=None, gt=0)
    max_attempts: int | None = Field(default=None, gt=0)
    max_cost_usd: Decimal | None = None

    @field_validator("max_cost_usd", mode="before")
    @classmethod
    def parse_cost(cls, value: object) -> Decimal | None:
        if value is None:
            return None
        parsed = _parse_decimal(value, field_name="max_cost_usd")
        if parsed <= 0:
            raise ValueError("max_cost_usd must be greater than zero")
        return parsed

    @field_serializer("max_cost_usd")
    def serialize_cost(self, value: Decimal | None) -> str | None:
        return None if value is None else _decimal_text(value)

    def merged(self, override: BudgetLimitSet | None) -> BudgetLimitSet:
        if override is None:
            return self
        base = self.model_dump(mode="python")
        for name, value in override.model_dump(mode="python").items():
            if value is not None:
                base[name] = value
        return BudgetLimitSet.model_validate(base)


class BudgetLimits(_StrictFrozenModel):
    """Canonical immutable limits and prices from one persisted effective config."""

    execution: BudgetLimitSet
    default_node: BudgetLimitSet
    node_overrides: dict[str, BudgetLimitSet] = Field(default_factory=dict)
    max_completion_tokens_per_call: int = Field(gt=0)
    model_prices: dict[str, ModelPrice] = Field(default_factory=dict)
    tool_prices_usd: dict[str, Decimal] = Field(default_factory=dict)

    @field_validator("node_overrides", "model_prices", "tool_prices_usd", mode="before")
    @classmethod
    def copy_mappings(cls, value: object) -> object:
        return dict(value) if isinstance(value, dict) else value

    @field_validator("node_overrides", "model_prices", "tool_prices_usd")
    @classmethod
    def sort_mappings(cls, value: dict[str, Any]) -> dict[str, Any]:
        if any(not isinstance(key, str) or not key.strip() for key in value):
            raise ValueError("budget mapping keys must be non-empty strings")
        return dict(sorted(value.items()))

    @field_validator("tool_prices_usd", mode="after")
    @classmethod
    def parse_tool_prices(cls, value: dict[str, Decimal]) -> dict[str, Decimal]:
        return {
            key: _parse_decimal(price, field_name=f"tool price {key!r}")
            for key, price in value.items()
        }

    @field_serializer("tool_prices_usd")
    def serialize_tool_prices(self, value: dict[str, Decimal]) -> dict[str, str]:
        return {key: _decimal_text(price) for key, price in value.items()}

    @classmethod
    def from_effective_config(cls, config: Mapping[str, object]) -> BudgetLimits:
        budget = config.get("budget")
        if not isinstance(budget, Mapping):
            raise BudgetConfigurationError("effective configuration has no budget object")

        def optional_positive_int(name: str, default: int | None) -> int | None:
            value = budget.get(name, default)
            if value is None:
                return None
            if type(value) is not int or value <= 0:
                raise BudgetConfigurationError(f"budget.{name} must be a positive integer or null")
            return value

        legacy_max = optional_positive_int("max_tokens", 100_000)
        execution = BudgetLimitSet(
            max_prompt_tokens=optional_positive_int("max_prompt_tokens", legacy_max),
            max_completion_tokens=optional_positive_int("max_completion_tokens", legacy_max),
            max_total_tokens=legacy_max,
            max_tool_calls=optional_positive_int("max_tool_calls", 10_000),
            max_duration_ms=optional_positive_int("max_duration_ms", 86_400_000),
            max_attempts=optional_positive_int("max_attempts", 10_000),
            max_cost_usd=budget.get("max_cost_usd"),
        )
        default_raw = budget.get("default_node_limits", {})
        if not isinstance(default_raw, Mapping):
            raise BudgetConfigurationError("budget.default_node_limits must be an object")
        default_node = execution.merged(_limit_override(default_raw))

        raw_overrides = budget.get("node_limits", {})
        if not isinstance(raw_overrides, Mapping):
            raise BudgetConfigurationError("budget.node_limits must be an object")
        overrides: dict[str, BudgetLimitSet] = {}
        for node_id, raw in raw_overrides.items():
            if not isinstance(node_id, str) or not node_id.strip() or not isinstance(raw, Mapping):
                raise BudgetConfigurationError("budget.node_limits entries must be named objects")
            overrides[node_id] = _limit_override(raw)

        raw_model_prices = budget.get("model_prices", {})
        if not isinstance(raw_model_prices, Mapping):
            raise BudgetConfigurationError("budget.model_prices must be an object")
        model_prices: dict[str, ModelPrice] = {}
        for identity, raw in raw_model_prices.items():
            if not isinstance(identity, str) or not identity.strip() or not isinstance(raw, Mapping):
                raise BudgetConfigurationError("budget.model_prices entries must be named objects")
            try:
                model_prices[identity] = ModelPrice.model_validate(dict(raw))
            except (TypeError, ValueError) as exc:
                raise BudgetConfigurationError(f"invalid model price for {identity!r}") from exc

        raw_tool_prices = budget.get("tool_prices_usd", {})
        if not isinstance(raw_tool_prices, Mapping):
            raise BudgetConfigurationError("budget.tool_prices_usd must be an object")
        tool_prices: dict[str, Decimal] = {}
        for tool_name, raw in raw_tool_prices.items():
            if not isinstance(tool_name, str) or not tool_name.strip():
                raise BudgetConfigurationError("budget.tool_prices_usd keys must be non-empty")
            tool_prices[tool_name] = _parse_decimal(raw, field_name=f"tool price {tool_name!r}")

        max_completion = optional_positive_int("max_completion_tokens_per_call", 4_096)
        assert max_completion is not None
        return cls(
            execution=execution,
            default_node=default_node,
            node_overrides=overrides,
            max_completion_tokens_per_call=max_completion,
            model_prices=model_prices,
            tool_prices_usd=tool_prices,
        )

    def for_node(self, node_id: str) -> BudgetLimitSet:
        return self.default_node.merged(self.node_overrides.get(node_id))

    def model_price(self, provider_id: str, model_name: str) -> ModelPrice | None:
        return self.model_prices.get(f"{provider_id}:{model_name}")

    def canonical_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ) + "\n"

    def digest(self) -> str:
        return "sha256:" + hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


def _limit_override(raw: Mapping[str, object]) -> BudgetLimitSet:
    allowed = {
        "max_prompt_tokens",
        "max_completion_tokens",
        "max_total_tokens",
        "max_tool_calls",
        "max_duration_ms",
        "max_attempts",
        "max_cost_usd",
    }
    extras = set(raw) - allowed
    if extras:
        raise BudgetConfigurationError(f"unknown node budget limit fields: {sorted(extras)}")
    try:
        return BudgetLimitSet.model_validate(dict(raw))
    except (TypeError, ValueError) as exc:
        raise BudgetConfigurationError("node budget limits are invalid") from exc


class BudgetIncrement(_StrictFrozenModel):
    """One estimate or one actual contribution to the canonical usage."""

    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    tool_calls: int = Field(default=0, ge=0)
    duration_ms: int = Field(default=0, ge=0)
    attempts: int = Field(default=0, ge=0)
    estimated_cost_usd: Decimal | None = None
    unpriced_operations: int = Field(default=0, ge=0)

    @field_validator("estimated_cost_usd", mode="before")
    @classmethod
    def parse_cost(cls, value: object) -> Decimal | None:
        return None if value is None else _parse_decimal(value, field_name="estimated_cost_usd")

    @field_serializer("estimated_cost_usd")
    def serialize_cost(self, value: Decimal | None) -> str | None:
        return None if value is None else _decimal_text(value)

    @model_validator(mode="after")
    def require_total(self) -> BudgetIncrement:
        if self.total_tokens != self.prompt_tokens + self.completion_tokens:
            raise ValueError("total_tokens must equal prompt_tokens + completion_tokens")
        if self.unpriced_operations and self.estimated_cost_usd is not None:
            raise ValueError("unpriced operations cannot carry an estimated cost")
        return self


class BudgetUsage(BudgetIncrement):
    """Aggregated usage for an execution or node."""


class BudgetRemaining(_StrictFrozenModel):
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    tool_calls: int | None
    duration_ms: int | None
    attempts: int | None
    estimated_cost_usd: Decimal | None

    @field_validator("estimated_cost_usd", mode="before")
    @classmethod
    def parse_cost(cls, value: object) -> Decimal | None:
        if value is None:
            return None
        parsed = value if isinstance(value, Decimal) else Decimal(str(value))
        if not parsed.is_finite():
            raise ValueError("remaining cost must be finite")
        return parsed

    @field_serializer("estimated_cost_usd")
    def serialize_cost(self, value: Decimal | None) -> str | None:
        return None if value is None else _decimal_text(value)


class BudgetNodeSnapshot(_StrictFrozenModel):
    node_id: _NonEmptyStr
    limits: BudgetLimitSet
    usage: BudgetUsage
    remaining: BudgetRemaining
    exceeded_dimensions: tuple[str, ...] = ()

    @field_validator("exceeded_dimensions", mode="before")
    @classmethod
    def freeze_dimensions(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value


class BudgetSnapshot(_StrictFrozenModel):
    """Redaction-safe balance reconstructed exclusively from persisted evidence."""

    execution_id: _NonEmptyStr
    limits_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    limits: BudgetLimitSet
    usage: BudgetUsage
    remaining: BudgetRemaining
    nodes: dict[str, BudgetNodeSnapshot]
    active_reservation_ids: tuple[str, ...] = ()
    exceeded_dimensions: tuple[str, ...] = ()

    @field_validator("nodes", mode="before")
    @classmethod
    def copy_nodes(cls, value: object) -> object:
        return dict(value) if isinstance(value, dict) else value

    @field_validator("nodes")
    @classmethod
    def sort_nodes(cls, value: dict[str, BudgetNodeSnapshot]) -> dict[str, BudgetNodeSnapshot]:
        return dict(sorted(value.items()))

    @field_validator("active_reservation_ids", "exceeded_dimensions", mode="before")
    @classmethod
    def freeze_tuples(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @property
    def is_exceeded(self) -> bool:
        return bool(self.exceeded_dimensions)


class BudgetReservation(_StrictFrozenModel):
    reservation_id: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    limits_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    node_id: _NonEmptyStr
    attempt: int = Field(ge=1)
    operation_id: _NonEmptyStr
    kind: BudgetOperationKind
    fencing_token: int = Field(gt=0)
    provider_id: _NonEmptyStr | None = None
    model_name: _NonEmptyStr | None = None
    tool_name: _NonEmptyStr | None = None
    estimate: BudgetIncrement

    @model_validator(mode="after")
    def require_kind_identity(self) -> BudgetReservation:
        if self.kind == "model":
            if self.provider_id is None or self.model_name is None or self.tool_name is not None:
                raise ValueError("model reservation identity is invalid")
        elif self.tool_name is None or self.provider_id is not None or self.model_name is not None:
            raise ValueError("tool reservation identity is invalid")
        expected = _reservation_digest(self.model_dump(mode="json", exclude={"reservation_id"}))
        if self.reservation_id != expected:
            raise ValueError("reservation_id does not match the canonical reservation")
        return self


class BudgetResult(_StrictFrozenModel):
    reservation_id: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    limits_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    node_id: _NonEmptyStr
    attempt: int = Field(ge=1)
    operation_id: _NonEmptyStr
    kind: BudgetOperationKind
    fencing_token: int = Field(gt=0)
    outcome: BudgetOutcome
    actual: BudgetIncrement
    response_id: _NonEmptyStr | None = None


class BudgetRelease(_StrictFrozenModel):
    reservation_id: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    limits_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    node_id: _NonEmptyStr
    attempt: int = Field(ge=1)
    operation_id: _NonEmptyStr
    kind: BudgetOperationKind
    fencing_token: int = Field(gt=0)
    reason_code: _NonEmptyStr


class BudgetExceededEvidence(_StrictFrozenModel):
    limits_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    node_id: _NonEmptyStr
    attempt: int = Field(ge=1)
    operation_id: _NonEmptyStr
    kind: BudgetEvidenceKind
    fencing_token: int = Field(gt=0)
    scope: BudgetScope
    dimensions: tuple[_NonEmptyStr, ...] = Field(min_length=1)
    reservation_id: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")

    @field_validator("dimensions", mode="before")
    @classmethod
    def freeze_dimensions(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def require_sorted_unique_dimensions(self) -> BudgetExceededEvidence:
        if self.dimensions != tuple(sorted(set(self.dimensions))):
            raise ValueError("budget exceeded dimensions must be sorted and unique")
        return self


def _reservation_digest(document: Mapping[str, object]) -> str:
    canonical = json.dumps(
        document,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class BudgetReservationHandle:
    reservation: BudgetReservation
    started_tick: float


@dataclass(frozen=True, slots=True)
class BudgetCommit:
    actual: BudgetIncrement
    snapshot: BudgetSnapshot

    @property
    def exceeded(self) -> bool:
        return self.snapshot.is_exceeded


class _UsageAccumulator:
    __slots__ = (
        "attempts",
        "completion_tokens",
        "duration_ms",
        "known_cost",
        "prompt_tokens",
        "tool_calls",
        "unpriced_operations",
    )

    def __init__(self) -> None:
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.tool_calls = 0
        self.duration_ms = 0
        self.attempts = 0
        self.known_cost = _DECIMAL_ZERO
        self.unpriced_operations = 0

    def add(self, increment: BudgetIncrement) -> None:
        self.prompt_tokens += increment.prompt_tokens
        self.completion_tokens += increment.completion_tokens
        self.tool_calls += increment.tool_calls
        self.duration_ms += increment.duration_ms
        self.attempts += increment.attempts
        if increment.estimated_cost_usd is not None:
            self.known_cost += increment.estimated_cost_usd
        self.unpriced_operations += increment.unpriced_operations

    def usage(self) -> BudgetUsage:
        return BudgetUsage(
            prompt_tokens=self.prompt_tokens,
            completion_tokens=self.completion_tokens,
            total_tokens=self.prompt_tokens + self.completion_tokens,
            tool_calls=self.tool_calls,
            duration_ms=self.duration_ms,
            attempts=self.attempts,
            estimated_cost_usd=(
                None if self.unpriced_operations else self.known_cost
            ),
            unpriced_operations=self.unpriced_operations,
        )


class BudgetLedger:
    """Strict replay and capacity checks over the canonical execution journal."""

    def __init__(
        self,
        execution_id: str,
        limits: BudgetLimits,
        events: Sequence[ExecutionEvent],
    ) -> None:
        self.execution_id = execution_id
        self.limits = limits
        self.events = tuple(events)
        self.active_reservations: dict[str, BudgetReservation] = {}
        self._closed_reservations: set[str] = set()
        self._committed_results: dict[str, BudgetResult] = {}
        self._execution_usage = _UsageAccumulator()
        self._node_usage: dict[str, _UsageAccumulator] = {}
        self._evidence_dimensions: set[str] = set()
        self._seen_budget_events = False
        self._replay()

    @classmethod
    def replay(
        cls,
        execution_id: str,
        limits: BudgetLimits,
        events: Sequence[ExecutionEvent],
    ) -> BudgetLedger:
        return cls(execution_id, limits, events)

    def snapshot(self) -> BudgetSnapshot:
        usage = self._execution_usage.usage()
        execution_dimensions = set(_exceeded_dimensions(self.limits.execution, usage))
        execution_dimensions.update(self._evidence_dimensions)
        nodes: dict[str, BudgetNodeSnapshot] = {}
        for node_id in sorted(self._node_usage):
            node_usage = self._node_usage[node_id].usage()
            node_limits = self.limits.for_node(node_id)
            node_dimensions = _exceeded_dimensions(node_limits, node_usage)
            nodes[node_id] = BudgetNodeSnapshot(
                node_id=node_id,
                limits=node_limits,
                usage=node_usage,
                remaining=_remaining(node_limits, node_usage),
                exceeded_dimensions=node_dimensions,
            )
            execution_dimensions.update(f"node:{node_id}:{name}" for name in node_dimensions)
        return BudgetSnapshot(
            execution_id=self.execution_id,
            limits_digest=self.limits.digest(),
            limits=self.limits.execution,
            usage=usage,
            remaining=_remaining(self.limits.execution, usage),
            nodes=nodes,
            active_reservation_ids=tuple(sorted(self.active_reservations)),
            exceeded_dimensions=tuple(sorted(execution_dimensions)),
        )

    def ensure_increment(
        self,
        node_id: str,
        increment: BudgetIncrement,
        *,
        operation_id: str,
    ) -> None:
        execution_pending = _sum_increments(
            self._execution_usage.usage(),
            *(reservation.estimate for reservation in self.active_reservations.values()),
            increment,
        )
        execution_dimensions = _exceeded_dimensions(self.limits.execution, execution_pending)
        if execution_dimensions:
            raise DurableBudgetExceededError(
                "execution budget estimate exceeds the remaining balance",
                dimensions=execution_dimensions,
                scope="execution",
                node_id=node_id,
                operation_id=operation_id,
            )
        node_pending_reservations = tuple(
            reservation.estimate
            for reservation in self.active_reservations.values()
            if reservation.node_id == node_id
        )
        node_usage = self._node_usage.get(node_id, _UsageAccumulator()).usage()
        pending = _sum_increments(node_usage, *node_pending_reservations, increment)
        node_dimensions = _exceeded_dimensions(self.limits.for_node(node_id), pending)
        if node_dimensions:
            raise DurableBudgetExceededError(
                "node budget estimate exceeds the remaining balance",
                dimensions=node_dimensions,
                scope="node",
                node_id=node_id,
                operation_id=operation_id,
            )

    def ensure_attempt(self, node_id: str, attempt: int) -> None:
        operation_id = f"attempt-{attempt}"
        self.ensure_increment(
            node_id,
            BudgetIncrement(total_tokens=0, duration_ms=1, attempts=1),
            operation_id=operation_id,
        )

    def next_operation_id(self, node_id: str, attempt: int, kind: BudgetOperationKind) -> str:
        if self.active_reservations:
            raise BudgetReservationAmbiguousError(
                "canonical budget contains an unresolved write-ahead reservation"
            )
        count = 1
        for event in self.events:
            if event.event_type not in {BUDGET_RESERVED, BUDGET_EXCEEDED}:
                continue
            payload = event.payload
            if (
                payload.get("node_id") == node_id
                and payload.get("attempt") == attempt
                and payload.get("kind") == kind
            ):
                count += 1
        return f"{kind}-{count:06d}"

    def require_active(self, reservation_id: str) -> BudgetReservation:
        try:
            return self.active_reservations[reservation_id]
        except KeyError as exc:
            raise BudgetIntegrityError("budget result has no active reservation") from exc

    def _node(self, node_id: str) -> _UsageAccumulator:
        return self._node_usage.setdefault(node_id, _UsageAccumulator())

    def _add(self, node_id: str, increment: BudgetIncrement) -> None:
        self._execution_usage.add(increment)
        self._node(node_id).add(increment)

    def _replay(self) -> None:
        first_budget_index = next(
            (
                index
                for index, event in enumerate(self.events)
                if event.event_type in BUDGET_EVENT_TYPES
            ),
            len(self.events),
        )
        dispatched_tools: dict[tuple[str, int, str], tuple[str, str]] = {}
        last_budget_timestamp: datetime | None = None
        last_fencing = 0
        for index, event in enumerate(self.events):
            if event.execution_id != self.execution_id:
                raise BudgetIntegrityError("budget replay received a foreign execution event")
            if event.event_type in BUDGET_EVENT_TYPES:
                self._seen_budget_events = True
                if last_budget_timestamp is not None and event.timestamp < last_budget_timestamp:
                    raise BudgetIntegrityError("budget event timestamps cannot regress")
                last_budget_timestamp = event.timestamp
                try:
                    if event.event_type == BUDGET_RESERVED:
                        reservation = BudgetReservation.model_validate(event.payload)
                        if reservation.limits_digest != self.limits.digest():
                            raise BudgetIntegrityError("budget reservation limits digest diverges")
                        if reservation.fencing_token < last_fencing:
                            raise BudgetIntegrityError("budget fencing token cannot regress")
                        last_fencing = reservation.fencing_token
                        if (
                            reservation.reservation_id in self.active_reservations
                            or reservation.reservation_id in self._closed_reservations
                        ):
                            raise BudgetIntegrityError("budget reservation is duplicated")
                        if self.active_reservations:
                            raise BudgetReservationAmbiguousError(
                                "canonical budget contains overlapping reservations"
                            )
                        self._validate_reservation_semantics(reservation)
                        self.active_reservations[reservation.reservation_id] = reservation
                    elif event.event_type == BUDGET_COMMITTED:
                        result = BudgetResult.model_validate(event.payload)
                        reservation = self._matching_result(result)
                        self._validate_result_semantics(reservation, result)
                        self._add(reservation.node_id, result.actual)
                        self._committed_results[reservation.reservation_id] = result
                        self._close(reservation.reservation_id)
                    elif event.event_type == BUDGET_RELEASED:
                        release = BudgetRelease.model_validate(event.payload)
                        reservation = self._matching_result(release)
                        self._close(reservation.reservation_id)
                    else:
                        evidence = BudgetExceededEvidence.model_validate(event.payload)
                        if evidence.limits_digest != self.limits.digest():
                            raise BudgetIntegrityError(
                                "budget exceeded evidence limits digest diverges"
                            )
                        if evidence.fencing_token < last_fencing:
                            raise BudgetIntegrityError("budget fencing token cannot regress")
                        last_fencing = evidence.fencing_token
                        self._validate_exceeded_semantics(evidence)
                        self._evidence_dimensions.update(
                            (
                                dimension
                                if evidence.scope == "execution"
                                else f"node:{evidence.node_id}:{dimension}"
                            )
                            for dimension in evidence.dimensions
                        )
                except BudgetIntegrityError:
                    raise
                except (TypeError, ValueError) as exc:
                    raise BudgetIntegrityError("budget event payload is invalid") from exc
                continue

            if index < first_budget_index:
                continue
            if event.event_type == "TOOL_CALLED":
                node_id = event.payload.get("node_id")
                attempt = event.payload.get("attempt")
                call_id = event.payload.get("call_id")
                tool_name = event.payload.get("tool_name")
                if (
                    not isinstance(node_id, str)
                    or type(attempt) is not int
                    or not isinstance(call_id, str)
                    or not isinstance(tool_name, str)
                ):
                    raise BudgetIntegrityError("tool write-ahead budget identity is malformed")
                matches = tuple(
                    reservation
                    for reservation in self.active_reservations.values()
                    if reservation.kind == "tool"
                    and reservation.node_id == node_id
                    and reservation.attempt == attempt
                    and reservation.tool_name == tool_name
                )
                if len(matches) != 1:
                    raise BudgetIntegrityError(
                        "tool effect has no unique preceding budget reservation"
                    )
                identity = (node_id, attempt, call_id)
                if identity in dispatched_tools or any(
                    matches[0].reservation_id == dispatched[0]
                    for dispatched in dispatched_tools.values()
                ):
                    raise BudgetIntegrityError("tool budget dispatch identity is duplicated")
                dispatched_tools[identity] = (matches[0].reservation_id, tool_name)
            elif event.event_type in {"TOOL_COMPLETED", "TOOL_FAILED"}:
                node_id = event.payload.get("node_id")
                attempt = event.payload.get("attempt")
                call_id = event.payload.get("call_id")
                tool_name = event.payload.get("tool_name")
                if (
                    not isinstance(node_id, str)
                    or type(attempt) is not int
                    or not isinstance(call_id, str)
                    or not isinstance(tool_name, str)
                ):
                    raise BudgetIntegrityError("tool outcome budget identity is malformed")
                identity = (node_id, attempt, call_id)
                dispatched = dispatched_tools.pop(identity, None)
                if dispatched is None or dispatched[1] != tool_name:
                    raise BudgetIntegrityError("tool outcome does not match its budgeted call")
                reservation_id = dispatched[0]
                committed_result = self._committed_results.get(reservation_id)
                if committed_result is None:
                    raise BudgetIntegrityError(
                        "tool outcome has no committed budget result"
                    )
                expected_event_type = (
                    "TOOL_COMPLETED"
                    if committed_result.outcome == "succeeded"
                    else "TOOL_FAILED"
                )
                expected_cost = (
                    None
                    if committed_result.actual.estimated_cost_usd is None
                    else _decimal_text(committed_result.actual.estimated_cost_usd)
                )
                if (
                    event.event_type != expected_event_type
                    or event.payload.get("duration_ms")
                    != committed_result.actual.duration_ms
                    or event.payload.get("estimated_cost_usd") != expected_cost
                ):
                    raise BudgetIntegrityError(
                        "tool outcome diverges from its committed budget result"
                    )

        self._replay_attempts()
        self._replay_verification_durations()
        self._replay_historical_usage(self.events[:first_budget_index])

    def _validate_reservation_semantics(self, reservation: BudgetReservation) -> None:
        estimate = reservation.estimate
        if reservation.kind == "model":
            assert reservation.provider_id is not None and reservation.model_name is not None
            model_price = self.limits.model_price(
                reservation.provider_id,
                reservation.model_name,
            )
            expected_cost = (
                None
                if model_price is None
                else model_price.estimate(
                    prompt_tokens=estimate.prompt_tokens,
                    completion_tokens=self.limits.max_completion_tokens_per_call,
                )
            )
            valid = (
                estimate.completion_tokens == self.limits.max_completion_tokens_per_call
                and estimate.tool_calls == 0
                and estimate.duration_ms == 1
                and estimate.attempts == 0
                and estimate.estimated_cost_usd == expected_cost
                and estimate.unpriced_operations == (1 if model_price is None else 0)
            )
        else:
            assert reservation.tool_name is not None
            tool_price = self.limits.tool_prices_usd.get(reservation.tool_name)
            valid = (
                estimate.prompt_tokens == 0
                and estimate.completion_tokens == 0
                and estimate.total_tokens == 0
                and estimate.tool_calls == 1
                and estimate.duration_ms == 1
                and estimate.attempts == 0
                and estimate.estimated_cost_usd == tool_price
                and estimate.unpriced_operations == (1 if tool_price is None else 0)
            )
        if not valid:
            raise BudgetIntegrityError("budget reservation estimate is semantically invalid")

    def _validate_result_semantics(
        self,
        reservation: BudgetReservation,
        result: BudgetResult,
    ) -> None:
        actual = result.actual
        if reservation.kind == "model":
            assert reservation.provider_id is not None and reservation.model_name is not None
            model_price = self.limits.model_price(
                reservation.provider_id,
                reservation.model_name,
            )
            if result.outcome == "failed":
                valid = (
                    result.response_id is None
                    and actual.prompt_tokens == 0
                    and actual.completion_tokens == 0
                    and actual.total_tokens == 0
                    and actual.tool_calls == 0
                    and actual.attempts == 0
                    and actual.estimated_cost_usd is None
                    and actual.unpriced_operations == 1
                )
            else:
                expected_cost = (
                    None
                    if model_price is None
                    else model_price.estimate(
                        prompt_tokens=actual.prompt_tokens,
                        completion_tokens=actual.completion_tokens,
                    )
                )
                valid = (
                    result.response_id is not None
                    and actual.tool_calls == 0
                    and actual.attempts == 0
                    and actual.estimated_cost_usd == expected_cost
                    and actual.unpriced_operations == (1 if model_price is None else 0)
                )
        else:
            assert reservation.tool_name is not None
            tool_price = self.limits.tool_prices_usd.get(reservation.tool_name)
            valid = (
                result.response_id is None
                and actual.prompt_tokens == 0
                and actual.completion_tokens == 0
                and actual.total_tokens == 0
                and actual.tool_calls == 1
                and actual.attempts == 0
                and actual.estimated_cost_usd == tool_price
                and actual.unpriced_operations == (1 if tool_price is None else 0)
            )
        if not valid:
            raise BudgetIntegrityError("budget result usage is semantically invalid")

    def _validate_exceeded_semantics(self, evidence: BudgetExceededEvidence) -> None:
        valid_dimensions = {
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
            "tool_calls",
            "duration_ms",
            "attempts",
            "cost_usd",
            "cost_usd_unavailable",
        }
        if not set(evidence.dimensions) <= valid_dimensions:
            raise BudgetIntegrityError("budget exceeded dimensions are semantically invalid")
        if evidence.reservation_id is None:
            return
        result = self._committed_results.get(evidence.reservation_id)
        if result is None:
            raise BudgetIntegrityError("budget exceeded evidence has no committed result")
        identity = (
            evidence.node_id,
            evidence.attempt,
            evidence.operation_id,
            evidence.kind,
            evidence.fencing_token,
        )
        expected_identity = (
            result.node_id,
            result.attempt,
            result.operation_id,
            result.kind,
            result.fencing_token,
        )
        if identity != expected_identity:
            raise BudgetIntegrityError("budget exceeded evidence identity diverges")
        snapshot = self.snapshot()
        node_prefix = f"node:{evidence.node_id}:"
        expected_scope: BudgetScope = (
            "node"
            if any(item.startswith(node_prefix) for item in snapshot.exceeded_dimensions)
            else "execution"
        )
        expected_dimensions = tuple(
            item.split(":", 2)[-1]
            for item in snapshot.exceeded_dimensions
            if not item.startswith("node:") or item.startswith(node_prefix)
        )
        if (
            evidence.scope != expected_scope
            or evidence.dimensions != tuple(sorted(set(expected_dimensions)))
        ):
            raise BudgetIntegrityError("budget exceeded evidence diverges from committed usage")

    def _matching_result(self, result: BudgetResult | BudgetRelease) -> BudgetReservation:
        if result.limits_digest != self.limits.digest():
            raise BudgetIntegrityError("budget result limits digest diverges")
        reservation = self.require_active(result.reservation_id)
        identity = (
            result.limits_digest,
            result.node_id,
            result.attempt,
            result.operation_id,
            result.kind,
            result.fencing_token,
        )
        expected = (
            reservation.limits_digest,
            reservation.node_id,
            reservation.attempt,
            reservation.operation_id,
            reservation.kind,
            reservation.fencing_token,
        )
        if identity != expected:
            raise BudgetIntegrityError("budget result identity diverges from its reservation")
        return reservation

    def _close(self, reservation_id: str) -> None:
        del self.active_reservations[reservation_id]
        if reservation_id in self._closed_reservations:
            raise BudgetIntegrityError("budget reservation was closed more than once")
        self._closed_reservations.add(reservation_id)

    def _replay_attempts(self) -> None:
        seen: set[tuple[str, int]] = set()
        for event in self.events:
            if event.event_type == "NODE_STARTED":
                node_id = event.payload.get("node_id")
                attempt = event.payload.get("attempt")
            elif event.event_type == "PLAN_GENERATION_STARTED":
                node_id = "__planning__"
                attempt = event.payload.get("attempt")
            elif event.event_type == "VERIFICATION_GATE_STARTED":
                gate_id = event.payload.get("gate_id")
                node_id = (
                    f"__verification__:{gate_id}"
                    if isinstance(gate_id, str)
                    else None
                )
                attempt = event.payload.get("attempt")
            else:
                continue
            if not isinstance(node_id, str) or not node_id or type(attempt) is not int or attempt < 1:
                raise BudgetIntegrityError("historical attempt evidence is malformed")
            identity = (node_id, attempt)
            if identity in seen:
                raise BudgetIntegrityError("attempt evidence is duplicated")
            seen.add(identity)
            self._add(node_id, BudgetIncrement(total_tokens=0, attempts=1))

    def _replay_verification_durations(self) -> None:
        open_gates: dict[tuple[str, int, int], datetime] = {}
        for event in self.events:
            payload = event.payload
            if event.event_type == "VERIFICATION_GATE_STARTED":
                gate_id = payload.get("gate_id")
                attempt = payload.get("attempt")
                gate_index = payload.get("gate_index")
                if (
                    not isinstance(gate_id, str)
                    or not gate_id
                    or type(attempt) is not int
                    or attempt < 1
                    or type(gate_index) is not int
                    or gate_index < 0
                ):
                    raise BudgetIntegrityError("verification budget identity is malformed")
                identity = (gate_id, attempt, gate_index)
                if identity in open_gates:
                    raise BudgetIntegrityError("verification budget start is duplicated")
                open_gates[identity] = event.timestamp
                continue
            if event.event_type != "VERIFICATION_GATE_RECORDED":
                continue
            gate_id = payload.get("gate_id")
            attempt = payload.get("attempt")
            gate_index = payload.get("gate_index")
            if (
                not isinstance(gate_id, str)
                or type(attempt) is not int
                or type(gate_index) is not int
            ):
                raise BudgetIntegrityError(
                    "verification budget result identity is malformed"
                )
            identity = (gate_id, attempt, gate_index)
            try:
                started_at = open_gates.pop(identity)
            except KeyError as exc:
                raise BudgetIntegrityError(
                    "verification budget result has no start"
                ) from exc
            persisted_duration = payload.get("duration_ms")
            if persisted_duration is None:
                duration_ms = max(
                    0,
                    int((event.timestamp - started_at).total_seconds() * 1000),
                )
            elif type(persisted_duration) is int and persisted_duration >= 0:
                duration_ms = persisted_duration
            else:
                raise BudgetIntegrityError("verification budget duration is malformed")
            self._add(
                f"__verification__:{gate_id}",
                BudgetIncrement(total_tokens=0, duration_ms=duration_ms),
            )

    def _replay_historical_usage(self, events: Sequence[ExecutionEvent]) -> None:
        response_ids: set[str] = set()
        tool_ids: set[tuple[str, int, str]] = set()
        starts: dict[tuple[str, int], datetime] = {}
        for event in events:
            payload = event.payload
            if event.event_type == "NODE_STARTED":
                node_id = payload.get("node_id")
                attempt = payload.get("attempt")
                if isinstance(node_id, str) and type(attempt) is int:
                    starts[(node_id, attempt)] = event.timestamp
                continue
            if event.event_type in {"NODE_COMPLETED", "NODE_FAILED"}:
                node_id = payload.get("node_id")
                attempt = payload.get("attempt")
                if not isinstance(node_id, str) or type(attempt) is not int:
                    raise BudgetIntegrityError("historical node outcome identity is malformed")
                started = starts.get((node_id, attempt))
                if started is not None:
                    duration = max(0, int((event.timestamp - started).total_seconds() * 1000))
                    self._add(node_id, BudgetIncrement(total_tokens=0, duration_ms=duration))
                raw_calls = payload.get("model_calls", [])
                if not isinstance(raw_calls, list):
                    raise BudgetIntegrityError("historical model usage is malformed")
                for raw in raw_calls:
                    self._add_historical_model(node_id, raw, response_ids)
                continue
            if event.event_type == "PLAN_GENERATED":
                self._add_historical_model("__planning__", payload, response_ids)
                continue
            if event.event_type in {"TOOL_COMPLETED", "TOOL_FAILED"}:
                node_id = payload.get("node_id")
                attempt = payload.get("attempt")
                call_id = payload.get("call_id")
                if not isinstance(node_id, str) or type(attempt) is not int or not isinstance(call_id, str):
                    raise BudgetIntegrityError("historical tool usage is malformed")
                identity = (node_id, attempt, call_id)
                if identity in tool_ids:
                    raise BudgetIntegrityError("historical tool outcome is duplicated")
                tool_ids.add(identity)
                tool_name = payload.get("tool_name")
                tool_price = (
                    self.limits.tool_prices_usd.get(tool_name)
                    if isinstance(tool_name, str)
                    else None
                )
                self._add(
                    node_id,
                    BudgetIncrement(
                        total_tokens=0,
                        tool_calls=1,
                        estimated_cost_usd=tool_price,
                        unpriced_operations=1 if tool_price is None else 0,
                    ),
                )

    def _add_historical_model(
        self,
        node_id: str,
        raw: object,
        response_ids: set[str],
    ) -> None:
        if not isinstance(raw, Mapping):
            raise BudgetIntegrityError("historical model usage is malformed")
        response_id = raw.get("response_id")
        prompt = raw.get("prompt_tokens")
        completion = raw.get("completion_tokens")
        total = raw.get("total_tokens")
        if (
            not isinstance(response_id, str)
            or not response_id
            or type(prompt) is not int
            or prompt < 0
            or type(completion) is not int
            or completion < 0
            or type(total) is not int
            or total != prompt + completion
        ):
            raise BudgetIntegrityError("historical model usage is malformed")
        if response_id in response_ids:
            raise BudgetIntegrityError("historical model response is duplicated")
        response_ids.add(response_id)
        provider_id = raw.get("provider_id", raw.get("provider"))
        model_name = raw.get("model_name")
        price = (
            self.limits.model_price(provider_id, model_name)
            if isinstance(provider_id, str) and isinstance(model_name, str)
            else None
        )
        self._add(
            node_id,
            BudgetIncrement(
                prompt_tokens=prompt,
                completion_tokens=completion,
                total_tokens=total,
                estimated_cost_usd=(
                    None
                    if price is None
                    else price.estimate(
                        prompt_tokens=prompt,
                        completion_tokens=completion,
                    )
                ),
                unpriced_operations=1 if price is None else 0,
            ),
        )


def _sum_increments(base: BudgetUsage, *increments: BudgetIncrement) -> BudgetUsage:
    accumulator = _UsageAccumulator()
    accumulator.add(base)
    for increment in increments:
        accumulator.add(increment)
    return accumulator.usage()


def _exceeded_dimensions(limits: BudgetLimitSet, usage: BudgetUsage) -> tuple[str, ...]:
    dimensions: list[str] = []
    pairs = (
        ("prompt_tokens", limits.max_prompt_tokens, usage.prompt_tokens),
        ("completion_tokens", limits.max_completion_tokens, usage.completion_tokens),
        ("total_tokens", limits.max_total_tokens, usage.total_tokens),
        ("tool_calls", limits.max_tool_calls, usage.tool_calls),
        ("duration_ms", limits.max_duration_ms, usage.duration_ms),
        ("attempts", limits.max_attempts, usage.attempts),
    )
    for name, maximum, consumed in pairs:
        if maximum is not None and consumed > maximum:
            dimensions.append(name)
    if limits.max_cost_usd is not None:
        if usage.estimated_cost_usd is None:
            dimensions.append("cost_usd_unavailable")
        elif usage.estimated_cost_usd > limits.max_cost_usd:
            dimensions.append("cost_usd")
    return tuple(sorted(dimensions))


def _remaining(limits: BudgetLimitSet, usage: BudgetUsage) -> BudgetRemaining:
    return BudgetRemaining(
        prompt_tokens=(None if limits.max_prompt_tokens is None else limits.max_prompt_tokens - usage.prompt_tokens),
        completion_tokens=(None if limits.max_completion_tokens is None else limits.max_completion_tokens - usage.completion_tokens),
        total_tokens=(None if limits.max_total_tokens is None else limits.max_total_tokens - usage.total_tokens),
        tool_calls=(None if limits.max_tool_calls is None else limits.max_tool_calls - usage.tool_calls),
        duration_ms=(None if limits.max_duration_ms is None else limits.max_duration_ms - usage.duration_ms),
        attempts=(None if limits.max_attempts is None else limits.max_attempts - usage.attempts),
        estimated_cost_usd=(
            None
            if limits.max_cost_usd is None or usage.estimated_cost_usd is None
            else limits.max_cost_usd - usage.estimated_cost_usd
        ),
    )


@runtime_checkable
class BudgetBoundary(Protocol):
    """Pre-effect reservation and post-effect result boundary used by model/tools."""

    def reserve_model(self, provider_id: str, model_name: str, prompt: str) -> BudgetReservationHandle:
        ...

    def commit_model(self, handle: BudgetReservationHandle, response: Any) -> BudgetCommit:
        ...

    def fail_model(self, handle: BudgetReservationHandle) -> BudgetCommit:
        ...

    def reserve_tool(self, tool_name: str) -> BudgetReservationHandle:
        ...

    def commit_tool(self, handle: BudgetReservationHandle, *, succeeded: bool) -> BudgetCommit:
        ...

    def release(self, handle: BudgetReservationHandle, *, reason_code: str) -> None:
        ...


class JournalBudgetBoundary:
    """One node/attempt view that appends budget evidence to the canonical journal."""

    def __init__(
        self,
        *,
        storage: ResumeStateStorageProvider,
        lock: ExecutionLock,
        execution_id: str,
        graph_name: str,
        node_id: str,
        attempt: int,
        limits: BudgetLimits,
        event_id_factory: Callable[[], str] | None = None,
        clock: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] | None = None,
    ) -> None:
        if not isinstance(storage, ResumeStateStorageProvider):
            raise TypeError("storage must implement ResumeStateStorageProvider")
        if lock.execution_id != execution_id or lock.fencing_token <= 0:
            raise ValueError("budget lock identity is invalid")
        if not graph_name.strip() or graph_name != graph_name.strip():
            raise ValueError("budget graph identity is invalid")
        if not node_id.strip() or attempt < 1:
            raise ValueError("budget node identity is invalid")
        self._storage = storage
        self._lock = lock
        self.execution_id = execution_id
        self.graph_name = graph_name
        self.node_id = node_id
        self.attempt = attempt
        self.limits = limits
        self._event_id_factory = event_id_factory or (lambda: f"budget-event-{uuid.uuid4().hex}")
        self._clock = clock or (lambda: datetime.now(UTC))
        self._monotonic = monotonic or time.monotonic

    def snapshot(self) -> BudgetSnapshot:
        return self._ledger().snapshot()

    def materialize_exceeded(
        self,
        *,
        operation_id: str,
        kind: BudgetEvidenceKind = "attempt",
    ) -> BudgetSnapshot:
        """Append redacted evidence when external durable usage crossed a cap."""
        snapshot = self.snapshot()
        if not snapshot.is_exceeded:
            return snapshot
        for event in self._storage.load_events(self.execution_id, lock=self._lock):
            if (
                event.event_type == BUDGET_EXCEEDED
                and event.payload.get("node_id") == self.node_id
                and event.payload.get("attempt") == self.attempt
                and event.payload.get("operation_id") == operation_id
            ):
                return snapshot
        node_prefix = f"node:{self.node_id}:"
        node_dimensions = tuple(
            item.removeprefix(node_prefix)
            for item in snapshot.exceeded_dimensions
            if item.startswith(node_prefix)
        )
        scope: BudgetScope = "node" if node_dimensions else "execution"
        dimensions = node_dimensions or tuple(
            item for item in snapshot.exceeded_dimensions if not item.startswith("node:")
        )
        evidence = BudgetExceededEvidence(
            limits_digest=self.limits.digest(),
            node_id=self.node_id,
            attempt=self.attempt,
            operation_id=operation_id,
            kind=kind,
            fencing_token=self._lock.fencing_token,
            scope=scope,
            dimensions=tuple(sorted(set(dimensions))),
        )
        self._append(BUDGET_EXCEEDED, evidence.model_dump(mode="json"))
        return self.snapshot()

    def ensure_attempt_available(self) -> None:
        ledger = self._ledger()
        try:
            ledger.ensure_attempt(self.node_id, self.attempt)
        except DurableBudgetExceededError as exc:
            self._append_denial(exc, kind="attempt")
            raise

    def reserve_model(
        self,
        provider_id: str,
        model_name: str,
        prompt: str,
    ) -> BudgetReservationHandle:
        if not provider_id.strip() or not model_name.strip() or not isinstance(prompt, str):
            raise BudgetConfigurationError("model reservation identity is invalid")
        ledger = self._ledger()
        operation_id = ledger.next_operation_id(self.node_id, self.attempt, "model")
        price = self.limits.model_price(provider_id, model_name)
        monetary_cap = (
            self.limits.execution.max_cost_usd is not None
            or self.limits.for_node(self.node_id).max_cost_usd is not None
        )
        if monetary_cap and price is None:
            exc = BudgetPriceUnavailableError(
                "monetary budget requires an applicable model price",
                dimensions=("cost_usd_unavailable",),
                scope="execution",
                node_id=self.node_id,
                operation_id=operation_id,
            )
            self._append_denial(exc, kind="model")
            raise exc
        prompt_estimate = len(prompt.encode("utf-8"))
        completion_estimate = self.limits.max_completion_tokens_per_call
        estimated_cost = (
            None
            if price is None
            else price.estimate(
                prompt_tokens=prompt_estimate,
                completion_tokens=completion_estimate,
            )
        )
        estimate = BudgetIncrement(
            prompt_tokens=prompt_estimate,
            completion_tokens=completion_estimate,
            total_tokens=prompt_estimate + completion_estimate,
            duration_ms=1,
            estimated_cost_usd=estimated_cost,
            unpriced_operations=1 if price is None else 0,
        )
        return self._reserve(
            ledger,
            operation_id=operation_id,
            kind="model",
            estimate=estimate,
            provider_id=provider_id,
            model_name=model_name,
        )

    def reserve_tool(self, tool_name: str) -> BudgetReservationHandle:
        if not tool_name.strip():
            raise BudgetConfigurationError("tool reservation identity is invalid")
        ledger = self._ledger()
        operation_id = ledger.next_operation_id(self.node_id, self.attempt, "tool")
        price = self.limits.tool_prices_usd.get(tool_name)
        monetary_cap = (
            self.limits.execution.max_cost_usd is not None
            or self.limits.for_node(self.node_id).max_cost_usd is not None
        )
        if monetary_cap and price is None:
            exc = BudgetPriceUnavailableError(
                "monetary budget requires an applicable tool price",
                dimensions=("cost_usd_unavailable",),
                scope="execution",
                node_id=self.node_id,
                operation_id=operation_id,
            )
            self._append_denial(exc, kind="tool")
            raise exc
        estimate = BudgetIncrement(
            total_tokens=0,
            tool_calls=1,
            duration_ms=1,
            estimated_cost_usd=price,
            unpriced_operations=1 if price is None else 0,
        )
        return self._reserve(
            ledger,
            operation_id=operation_id,
            kind="tool",
            estimate=estimate,
            tool_name=tool_name,
        )

    def commit_model(self, handle: BudgetReservationHandle, response: Any) -> BudgetCommit:
        reservation = self._validate_handle(handle, kind="model")
        prompt_tokens = getattr(response, "prompt_tokens", None)
        completion_tokens = getattr(response, "completion_tokens", None)
        total_tokens = getattr(response, "total_tokens", None)
        response_id = getattr(response, "response_id", None)
        if (
            type(prompt_tokens) is not int
            or prompt_tokens < 0
            or type(completion_tokens) is not int
            or completion_tokens < 0
            or type(total_tokens) is not int
            or total_tokens != prompt_tokens + completion_tokens
            or not isinstance(response_id, str)
            or not response_id
        ):
            raise BudgetIntegrityError("model response usage is invalid")
        assert reservation.provider_id is not None and reservation.model_name is not None
        price = self.limits.model_price(reservation.provider_id, reservation.model_name)
        actual = BudgetIncrement(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            duration_ms=self._duration_ms(handle),
            estimated_cost_usd=(
                None
                if price is None
                else price.estimate(
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                )
            ),
            unpriced_operations=1 if price is None else 0,
        )
        return self._commit(handle, actual, outcome="succeeded", response_id=response_id)

    def fail_model(self, handle: BudgetReservationHandle) -> BudgetCommit:
        self._validate_handle(handle, kind="model")
        return self._commit(
            handle,
            BudgetIncrement(
                total_tokens=0,
                duration_ms=self._duration_ms(handle),
                unpriced_operations=1,
            ),
            outcome="failed",
            response_id=None,
        )

    def commit_tool(self, handle: BudgetReservationHandle, *, succeeded: bool) -> BudgetCommit:
        reservation = self._validate_handle(handle, kind="tool")
        assert reservation.tool_name is not None
        price = self.limits.tool_prices_usd.get(reservation.tool_name)
        return self._commit(
            handle,
            BudgetIncrement(
                total_tokens=0,
                tool_calls=1,
                duration_ms=self._duration_ms(handle),
                estimated_cost_usd=price,
                unpriced_operations=1 if price is None else 0,
            ),
            outcome="succeeded" if succeeded else "failed",
            response_id=None,
        )

    def release(self, handle: BudgetReservationHandle, *, reason_code: str) -> None:
        reservation = self._validate_handle(handle)
        if not reason_code.strip():
            raise ValueError("budget release reason must be non-empty")
        release = BudgetRelease(
            reservation_id=reservation.reservation_id,
            limits_digest=reservation.limits_digest,
            node_id=reservation.node_id,
            attempt=reservation.attempt,
            operation_id=reservation.operation_id,
            kind=reservation.kind,
            fencing_token=reservation.fencing_token,
            reason_code=reason_code,
        )
        self._append(BUDGET_RELEASED, release.model_dump(mode="json"))

    def _reserve(
        self,
        ledger: BudgetLedger,
        *,
        operation_id: str,
        kind: BudgetOperationKind,
        estimate: BudgetIncrement,
        provider_id: str | None = None,
        model_name: str | None = None,
        tool_name: str | None = None,
    ) -> BudgetReservationHandle:
        try:
            ledger.ensure_increment(self.node_id, estimate, operation_id=operation_id)
        except DurableBudgetExceededError as exc:
            self._append_denial(exc, kind=kind)
            raise
        document: dict[str, object] = {
            "limits_digest": self.limits.digest(),
            "node_id": self.node_id,
            "attempt": self.attempt,
            "operation_id": operation_id,
            "kind": kind,
            "fencing_token": self._lock.fencing_token,
            "provider_id": provider_id,
            "model_name": model_name,
            "tool_name": tool_name,
            "estimate": estimate.model_dump(mode="json"),
        }
        reservation = BudgetReservation.model_validate(
            {
                "reservation_id": _reservation_digest(document),
                **document,
            }
        )
        self._append(BUDGET_RESERVED, reservation.model_dump(mode="json"))
        return BudgetReservationHandle(
            reservation=reservation,
            started_tick=self._tick(),
        )

    def _commit(
        self,
        handle: BudgetReservationHandle,
        actual: BudgetIncrement,
        *,
        outcome: BudgetOutcome,
        response_id: str | None,
    ) -> BudgetCommit:
        reservation = self._validate_handle(handle)
        result = BudgetResult(
            reservation_id=reservation.reservation_id,
            limits_digest=reservation.limits_digest,
            node_id=reservation.node_id,
            attempt=reservation.attempt,
            operation_id=reservation.operation_id,
            kind=reservation.kind,
            fencing_token=reservation.fencing_token,
            outcome=outcome,
            actual=actual,
            response_id=response_id,
        )
        self._append(BUDGET_COMMITTED, result.model_dump(mode="json"))
        snapshot = self.snapshot()
        if snapshot.exceeded_dimensions:
            local_dimensions = tuple(
                item.split(":", 2)[-1]
                for item in snapshot.exceeded_dimensions
                if not item.startswith("node:") or item.startswith(f"node:{self.node_id}:")
            )
            scope: BudgetScope = (
                "node"
                if any(item.startswith(f"node:{self.node_id}:") for item in snapshot.exceeded_dimensions)
                else "execution"
            )
            evidence = BudgetExceededEvidence(
                limits_digest=self.limits.digest(),
                node_id=self.node_id,
                attempt=self.attempt,
                operation_id=reservation.operation_id,
                kind=reservation.kind,
                fencing_token=self._lock.fencing_token,
                scope=scope,
                dimensions=tuple(sorted(set(local_dimensions))),
                reservation_id=reservation.reservation_id,
            )
            self._append(BUDGET_EXCEEDED, evidence.model_dump(mode="json"))
            snapshot = self.snapshot()
        return BudgetCommit(actual=actual, snapshot=snapshot)

    def _append_denial(
        self,
        exc: DurableBudgetExceededError,
        *,
        kind: BudgetEvidenceKind,
    ) -> None:
        evidence = BudgetExceededEvidence(
            limits_digest=self.limits.digest(),
            node_id=self.node_id,
            attempt=self.attempt,
            operation_id=exc.operation_id,
            kind=kind,
            fencing_token=self._lock.fencing_token,
            scope=exc.scope,
            dimensions=tuple(sorted(set(exc.dimensions))),
        )
        self._append(BUDGET_EXCEEDED, evidence.model_dump(mode="json"))

    def _validate_handle(
        self,
        handle: BudgetReservationHandle,
        *,
        kind: BudgetOperationKind | None = None,
    ) -> BudgetReservation:
        if not isinstance(handle, BudgetReservationHandle):
            raise TypeError("budget reservation handle is invalid")
        reservation = handle.reservation
        if (
            reservation.node_id != self.node_id
            or reservation.attempt != self.attempt
            or reservation.fencing_token != self._lock.fencing_token
            or (kind is not None and reservation.kind != kind)
        ):
            raise BudgetIntegrityError("budget reservation handle identity diverges")
        active = self._ledger().require_active(reservation.reservation_id)
        if active != reservation:
            raise BudgetIntegrityError("budget reservation handle payload diverges")
        return reservation

    def _ledger(self) -> BudgetLedger:
        try:
            events = self._storage.load_events(self.execution_id, lock=self._lock)
            return BudgetLedger.replay(self.execution_id, self.limits, events)
        except BudgetError:
            raise
        except Exception as exc:
            raise BudgetDurabilityError("canonical budget journal cannot be read") from exc

    def _append(self, event_type: str, payload: dict[str, object]) -> ExecutionEvent:
        try:
            events = self._storage.load_events(self.execution_id, lock=self._lock)
            minimum = events[-1].timestamp if events else datetime.min.replace(tzinfo=UTC)
            timestamp = self._clock()
            if (
                timestamp.tzinfo is None
                or timestamp.utcoffset() is None
                or timestamp.utcoffset() != timedelta(0)
            ):
                raise ValueError("budget clock must return UTC")
            timestamp = timestamp.astimezone(UTC)
            if timestamp <= minimum:
                timestamp = minimum + timedelta(microseconds=1)
            event = ExecutionEvent(
                event_id=self._event_id_factory(),
                execution_id=self.execution_id,
                sequence_number=0,
                event_type=EventType(event_type),
                timestamp=timestamp,
                graph_name=self.graph_name,
                node_id=self.node_id,
                attempt=self.attempt,
                actor="budget_boundary",
                details=payload,
            )
            return self._storage.append_event(self.execution_id, event, lock=self._lock)
        except BudgetError:
            raise
        except Exception as exc:
            raise BudgetDurabilityError(f"cannot append canonical {event_type} evidence") from exc

    def _tick(self) -> float:
        tick = self._monotonic()
        if isinstance(tick, bool) or not isinstance(tick, (int, float)) or not math.isfinite(tick):
            raise BudgetDurabilityError("budget monotonic clock returned an invalid value")
        return float(tick)

    def _duration_ms(self, handle: BudgetReservationHandle) -> int:
        elapsed = Decimal(str(self._tick())) - Decimal(str(handle.started_tick))
        if elapsed < 0:
            raise BudgetDurabilityError("budget monotonic clock regressed")
        return int((elapsed * Decimal(1000)).to_integral_value(rounding=ROUND_CEILING))


class BudgetTracker:
    """Legacy in-memory token guard retained for direct router compatibility."""

    def __init__(self, max_tokens: int = 100_000) -> None:
        if type(max_tokens) is not int or max_tokens <= 0:
            raise ValueError("max_tokens deve ser inteiro positivo")
        self.max_tokens = max_tokens
        self.consumed_tokens = 0

    @property
    def remaining_tokens(self) -> int:
        return max(self.max_tokens - self.consumed_tokens, 0)

    @property
    def is_exhausted(self) -> bool:
        return self.consumed_tokens >= self.max_tokens

    def ensure_available(self) -> None:
        if self.is_exhausted:
            raise BudgetExceededError(
                max_tokens=self.max_tokens,
                consumed_tokens=self.consumed_tokens,
            )

    def add_tokens(self, count: int) -> None:
        if type(count) is not int or count < 0:
            raise ValueError("count deve ser inteiro não negativo")
        self.consumed_tokens += count
        if self.consumed_tokens > self.max_tokens:
            raise BudgetExceededError(
                max_tokens=self.max_tokens,
                consumed_tokens=self.consumed_tokens,
            )
