"""Fail-closed operational tool registry and decision-bound dispatch."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Annotated, Any, cast

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError
from pydantic import BaseModel, ConfigDict, JsonValue, StringConstraints, field_validator

from ai_engineering_harness.governance import (
    PolicyDecisionIntegrityError,
    PolicyDeniedError,
    PolicyEngine,
    ToolPolicyDecision,
    ToolPolicyRequest,
)
from ai_engineering_harness.models.provider import ToolCall
from ai_engineering_harness.security import (
    RedactionContext,
    TrustCapabilityDeniedError,
    TrustEvaluationResult,
)
from ai_engineering_harness.security.redaction import Redactor

_NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
ToolHandler = Callable[[dict[str, JsonValue]], JsonValue]


class ToolRouterError(RuntimeError):
    """Base class for public operational tool routing failures."""


class ToolUnauthorizedError(PermissionError, ToolRouterError):
    """A capability or deterministic policy decision does not authorize a tool."""


class ToolUnavailableError(ToolRouterError):
    """A declared capability has no explicitly registered operational handler."""


class ToolPayloadValidationError(ToolRouterError):
    """A model-supplied tool payload violates its registered schema."""


class ToolExecutionError(ToolRouterError):
    """An operational tool handler failed without exposing its raw exception."""


class ToolDefinition(BaseModel):
    """Provider-facing schema for one operational tool."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    name: _NonEmptyStr
    description: _NonEmptyStr
    parameters: dict[str, JsonValue]

    @field_validator("parameters")
    @classmethod
    def require_valid_json_schema(
        cls,
        value: dict[str, JsonValue],
    ) -> dict[str, JsonValue]:
        try:
            Draft202012Validator.check_schema(value)
        except SchemaError as exc:
            raise ValueError(f"invalid tool JSON Schema: {exc.message}") from exc
        return value

    def provider_schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


@dataclass(frozen=True, slots=True)
class ToolRegistration:
    """One explicit handler and its immutable policy target metadata."""

    definition: ToolDefinition
    handler: ToolHandler
    operation: str = "invoke"
    path_argument: str | None = None
    default_path: str | None = None
    redaction_context: RedactionContext = field(
        default_factory=RedactionContext,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if not self.operation.strip() or self.operation != self.operation.strip():
            raise ValueError("tool registration operation must be canonical and non-empty")
        if self.path_argument is not None and (
            not self.path_argument.strip()
            or self.path_argument != self.path_argument.strip()
        ):
            raise ValueError("tool registration path_argument must be canonical and non-empty")
        if self.path_argument is None and self.default_path is not None:
            raise ValueError("default_path requires a path_argument")
        if not isinstance(self.redaction_context, RedactionContext):
            raise TypeError("redaction_context must be a RedactionContext")


@dataclass(frozen=True, slots=True)
class ToolDispatchTarget:
    """Policy-relevant identity derived from a validated registration and payload."""

    tool: str
    operation: str
    path: str | None


class ToolRouter:
    """Validate capability availability and dispatch only with a verified decision."""

    def __init__(
        self,
        allowed_tools: list[str] | tuple[str, ...],
        *,
        registrations: Mapping[str, ToolRegistration] | None = None,
        trust_boundary: TrustEvaluationResult | None = None,
    ) -> None:
        enabled = tuple(allowed_tools)
        if len(set(enabled)) != len(enabled):
            raise ValueError("enabled tool capabilities must be unique")
        if any(not isinstance(name, str) or not name.strip() for name in enabled):
            raise ValueError("enabled tool capabilities must be non-empty strings")
        self._enabled_tools = enabled

        source = registrations if registrations is not None else {}
        copied: dict[str, ToolRegistration] = {}
        for name, registration in source.items():
            if name != registration.definition.name:
                raise ValueError("tool registration key must match its definition name")
            if name in copied:
                raise ValueError(f"duplicate tool registration: {name}")
            copied[name] = registration
        self._registrations = copied
        if trust_boundary is not None and not isinstance(trust_boundary, TrustEvaluationResult):
            raise TypeError("trust_boundary must be a TrustEvaluationResult or None")
        self._trust_boundary = trust_boundary

    @property
    def enabled_tools(self) -> tuple[str, ...]:
        return self._enabled_tools

    @property
    def registered_tools(self) -> tuple[str, ...]:
        return tuple(sorted(self._registrations))

    @property
    def trust_boundary(self) -> TrustEvaluationResult | None:
        return self._trust_boundary

    def require_trust_mode(self, trust_mode: str) -> None:
        boundary = self._trust_boundary
        if boundary is None:
            return
        try:
            boundary.require_root(boundary.authorized_root)
        except TrustCapabilityDeniedError as exc:
            raise ToolUnauthorizedError(str(exc)) from exc
        if trust_mode != boundary.mode:
            raise ToolUnauthorizedError(
                "tool trust mode does not match the effective trust boundary"
            )

    def prepare(
        self,
        effective_allowed_tools: Sequence[str],
        *,
        effective_denied_tools: Sequence[str] = (),
    ) -> tuple[dict[str, Any], ...]:
        """Validate the compiled capability view before prompt composition."""
        allowed, denied = self._validate_compiled_capabilities(
            effective_allowed_tools,
            effective_denied_tools,
        )
        schemas: list[dict[str, Any]] = []
        for name in allowed:
            self._require_enabled(name, allowed, denied)
            schemas.append(self._registration(name).definition.provider_schema())
        return tuple(schemas)

    def validate_calls(self, calls: Sequence[ToolCall]) -> tuple[ToolDispatchTarget, ...]:
        """Validate an entire model batch and derive its concrete policy targets."""
        seen_call_ids: set[str] = set()
        targets: list[ToolDispatchTarget] = []
        for call in calls:
            if call.call_id in seen_call_ids:
                raise ToolPayloadValidationError("tool call IDs must be unique within a batch")
            seen_call_ids.add(call.call_id)
            self._require_enabled(call.name, self._enabled_tools, ())
            registration = self._registration(call.name)
            self._validate_payload(call.name, call.arguments, registration)
            targets.append(self._target(registration, call.arguments))
        return tuple(targets)

    def dispatch(
        self,
        tool_name: str,
        payload: dict[str, JsonValue],
        *,
        policy_engine: PolicyEngine | None = None,
        decision: ToolPolicyDecision | None = None,
    ) -> JsonValue:
        self._require_enabled(tool_name, self._enabled_tools, ())
        registration = self._registration(tool_name)
        self._validate_payload(tool_name, payload, registration)
        target = self._target(registration, payload)
        self._require_verified_decision(target, policy_engine, decision)
        try:
            result = registration.handler(payload)
            projected = Redactor.redact_json(
                result,
                context=registration.redaction_context,
            )
            return _copy_json_value(cast(JsonValue, projected))
        except ToolRouterError:
            raise
        except Exception as exc:
            safe_type = Redactor.redact_text(type(exc).__name__)
            raise ToolExecutionError(f"tool {tool_name} failed: {safe_type}") from exc

    @staticmethod
    def _validate_compiled_capabilities(
        effective_allowed: Sequence[str],
        effective_denied: Sequence[str],
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        allowed = tuple(effective_allowed)
        denied = tuple(effective_denied)
        if len(set(allowed)) != len(allowed):
            raise ToolUnauthorizedError("effective tool allowlist contains duplicates")
        if len(set(denied)) != len(denied):
            raise ToolUnauthorizedError("effective tool denylist contains duplicates")
        overlap = sorted(set(allowed) & set(denied))
        if overlap:
            raise ToolUnauthorizedError(
                "effective tool policy overlaps allow and deny: " + ", ".join(overlap)
            )
        return allowed, denied

    def _require_enabled(
        self,
        name: str,
        effective_allowed: Sequence[str],
        effective_denied: Sequence[str],
    ) -> None:
        if (
            name in effective_denied
            or name not in effective_allowed
            or name not in self._enabled_tools
        ):
            raise ToolUnauthorizedError(f"tool capability is not enabled: {name}")

    def _registration(self, name: str) -> ToolRegistration:
        try:
            return self._registrations[name]
        except KeyError as exc:
            raise ToolUnavailableError(
                f"tool capability has no operational registration: {name}"
            ) from exc

    @staticmethod
    def _validate_payload(
        tool_name: str,
        payload: dict[str, JsonValue],
        registration: ToolRegistration,
    ) -> None:
        try:
            Draft202012Validator(registration.definition.parameters).validate(payload)
        except ValidationError as exc:
            raise ToolPayloadValidationError(
                f"tool payload violates schema for {tool_name}"
            ) from exc

    @staticmethod
    def _target(
        registration: ToolRegistration,
        payload: dict[str, JsonValue],
    ) -> ToolDispatchTarget:
        path: str | None = None
        if registration.path_argument is not None:
            raw_path = payload.get(registration.path_argument, registration.default_path)
            if raw_path is not None and not isinstance(raw_path, str):
                raise ToolPayloadValidationError("tool policy path must be a string")
            path = raw_path
        return ToolDispatchTarget(
            tool=registration.definition.name,
            operation=registration.operation,
            path=path,
        )

    def _require_verified_decision(
        self,
        target: ToolDispatchTarget,
        engine: PolicyEngine | None,
        decision: ToolPolicyDecision | None,
    ) -> None:
        if engine is None or decision is None:
            raise ToolUnauthorizedError("tool dispatch requires a verified policy decision")
        request = decision.request
        self.require_trust_mode(request.trust_mode)
        try:
            actual_request = ToolPolicyRequest(
                role=request.role,
                node_id=request.node_id,
                workflow=request.workflow,
                trust_mode=request.trust_mode,
                tool=target.tool,
                operation=target.operation,
                path=target.path,
                approval_granted=request.approval_granted,
            )
        except ValueError as exc:
            raise ToolUnauthorizedError("tool dispatch target is invalid for policy") from exc
        if actual_request != request:
            raise ToolUnauthorizedError("policy decision does not match tool dispatch target")
        try:
            engine.require_allowed(decision)
        except (PolicyDeniedError, PolicyDecisionIntegrityError) as exc:
            raise ToolUnauthorizedError("tool policy decision is not authorized") from exc


def _copy_json_value(value: object) -> JsonValue:
    try:
        serialized = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return json.loads(serialized)
    except (TypeError, ValueError) as exc:
        raise ToolExecutionError("tool result must be JSON-native") from exc


__all__ = [
    "ToolDefinition",
    "ToolDispatchTarget",
    "ToolExecutionError",
    "ToolPayloadValidationError",
    "ToolRegistration",
    "ToolRouter",
    "ToolRouterError",
    "ToolUnauthorizedError",
    "ToolUnavailableError",
]
