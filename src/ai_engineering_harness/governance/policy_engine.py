"""Typed, deterministic and default-deny runtime policy evaluation."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from fnmatch import fnmatchcase
from pathlib import PurePosixPath
from typing import Annotated, Any, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    StringConstraints,
    field_validator,
    model_validator,
)

from ai_engineering_harness.governance.budget import BudgetTracker

_NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
TrustMode = Literal["trusted", "restricted"]
PolicyEffect = Literal["allow", "deny"]
DecisionReason = Literal["rule-allow", "rule-deny", "approval-required", "default-deny"]
_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:")


class PolicyEngineError(RuntimeError):
    """Base class for policy evaluation failures."""


class PolicyDeniedError(PermissionError, PolicyEngineError):
    """A complete request was denied by an applied rule or by default."""

    def __init__(self, decision: ToolPolicyDecision) -> None:
        super().__init__(
            f"tool policy denied request via {decision.rule_id}: {decision.reason}"
        )
        self.decision = decision


class PolicyDecisionIntegrityError(PolicyEngineError):
    """A supplied decision was not produced by this engine for its request."""


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")


class ToolPolicyRequest(_StrictFrozenModel):
    """Complete context required to authorize one concrete tool effect."""

    role: _NonEmptyStr
    node_id: _NonEmptyStr
    workflow: _NonEmptyStr
    trust_mode: TrustMode
    tool: _NonEmptyStr
    operation: _NonEmptyStr
    path: _NonEmptyStr | None = None
    approval_granted: bool = False

    @field_validator("path")
    @classmethod
    def canonicalize_relative_path(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.replace("\\", "/")
        if normalized.startswith("/") or _WINDOWS_DRIVE.match(normalized):
            raise ValueError("policy request path must be relative")
        path = PurePosixPath(normalized)
        if ".." in path.parts:
            raise ValueError("policy request path cannot traverse parents")
        canonical = path.as_posix()
        return canonical if canonical else "."


class ToolPolicyRule(_StrictFrozenModel):
    """One stable allow/deny rule over every F5.2 authorization dimension."""

    rule_id: _NonEmptyStr
    effect: PolicyEffect
    roles: tuple[_NonEmptyStr, ...] = ("*",)
    node_ids: tuple[_NonEmptyStr, ...] = ("*",)
    workflows: tuple[_NonEmptyStr, ...] = ("*",)
    trust_modes: tuple[TrustMode, ...] = ("trusted", "restricted")
    tools: tuple[_NonEmptyStr, ...] = ("*",)
    operations: tuple[_NonEmptyStr, ...] = ("*",)
    path_patterns: tuple[_NonEmptyStr, ...] = ("*",)
    approval_required: bool = False

    @field_validator(
        "roles",
        "node_ids",
        "workflows",
        "trust_modes",
        "tools",
        "operations",
        "path_patterns",
        mode="before",
    )
    @classmethod
    def freeze_selectors(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @field_validator(
        "roles",
        "node_ids",
        "workflows",
        "trust_modes",
        "tools",
        "operations",
        "path_patterns",
    )
    @classmethod
    def require_unique_non_empty_selectors(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("policy rule selectors cannot be empty")
        if len(set(value)) != len(value):
            raise ValueError("policy rule selectors must be unique")
        return value

    @model_validator(mode="after")
    def deny_rules_cannot_require_approval(self) -> Self:
        if self.effect == "deny" and self.approval_required:
            raise ValueError("deny rules cannot require approval")
        return self

    def matches(self, request: ToolPolicyRequest) -> bool:
        """Match exact selectors plus explicit wildcards and path globs."""
        return (
            _selected(request.role, self.roles)
            and _selected(request.node_id, self.node_ids)
            and _selected(request.workflow, self.workflows)
            and request.trust_mode in self.trust_modes
            and _selected(request.tool, self.tools)
            and _selected(request.operation, self.operations)
            and _path_selected(request.path, self.path_patterns)
        )


class ToolPolicyDecision(_StrictFrozenModel):
    """Persistable result containing the request and the exact applied rule."""

    request: ToolPolicyRequest
    allowed: bool
    rule_id: _NonEmptyStr
    rule_effect: PolicyEffect
    approval_required: bool
    reason: DecisionReason

    @model_validator(mode="after")
    def require_consistent_result(self) -> Self:
        if self.reason == "rule-allow":
            if not self.allowed or self.rule_effect != "allow":
                raise ValueError("rule-allow requires an allowed result and allow rule")
            if self.approval_required and not self.request.approval_granted:
                raise ValueError("approval-bound allow requires granted approval")
        elif self.allowed:
            raise ValueError("only rule-allow decisions may be allowed")
        if self.reason == "approval-required":
            if self.rule_effect != "allow" or not self.approval_required:
                raise ValueError("approval-required must identify an approval-bound allow rule")
            if self.request.approval_granted:
                raise ValueError("approval-required is invalid when approval is granted")
        if self.reason == "default-deny" and (
            self.rule_id != "default-deny"
            or self.rule_effect != "deny"
            or self.approval_required
        ):
            raise ValueError("default-deny must use the reserved deny identity")
        if self.reason != "default-deny" and self.rule_id == "default-deny":
            raise ValueError("default-deny identity is reserved")
        if self.reason == "rule-deny" and (
            self.rule_effect != "deny" or self.approval_required
        ):
            raise ValueError("rule-deny requires a non-approval deny rule")
        return self

    def digest(self) -> str:
        canonical = json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class PolicyEngine:
    """Single evaluator for runtime authorization and legacy token accounting."""

    def __init__(
        self,
        config: Mapping[str, Any] | None = None,
        *,
        rules: Sequence[ToolPolicyRule] = (),
    ) -> None:
        detached_config = dict(config or {})
        budget = detached_config.get("budget", {})
        if not isinstance(budget, Mapping):
            raise TypeError("budget configuration must be a mapping")
        max_tokens = budget.get("max_tokens", 100_000)
        if type(max_tokens) is not int:
            raise TypeError("budget.max_tokens must be an integer")
        self.config = detached_config
        self.budget_tracker = BudgetTracker(max_tokens=max_tokens)

        ordered = tuple(sorted(rules, key=lambda rule: rule.rule_id))
        identifiers = tuple(rule.rule_id for rule in ordered)
        if "default-deny" in identifiers:
            raise ValueError("default-deny is a reserved rule identity")
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("policy rule identities must be unique")
        self._rules = ordered

    @property
    def rules(self) -> tuple[ToolPolicyRule, ...]:
        return self._rules

    def evaluate(self, request: ToolPolicyRequest) -> ToolPolicyDecision:
        """Apply deny-wins and return a deterministic default-deny decision."""
        matching = tuple(rule for rule in self._rules if rule.matches(request))
        denied = tuple(rule for rule in matching if rule.effect == "deny")
        if denied:
            return _decision(request, denied[0], allowed=False, reason="rule-deny")

        allowed = tuple(rule for rule in matching if rule.effect == "allow")
        if not allowed:
            return ToolPolicyDecision(
                request=request,
                allowed=False,
                rule_id="default-deny",
                rule_effect="deny",
                approval_required=False,
                reason="default-deny",
            )
        applied = allowed[0]
        if applied.approval_required and not request.approval_granted:
            return _decision(
                request,
                applied,
                allowed=False,
                reason="approval-required",
            )
        return _decision(request, applied, allowed=True, reason="rule-allow")

    def require_allowed(self, decision: ToolPolicyDecision) -> None:
        """Re-evaluate a supplied decision and reject forgery, drift or denial."""
        expected = self.evaluate(decision.request)
        if expected != decision:
            raise PolicyDecisionIntegrityError(
                "policy decision does not match deterministic evaluation"
            )
        if not decision.allowed:
            raise PolicyDeniedError(decision)

    def record_usage(self, token_count: int) -> None:
        """Preserve the existing budget boundary until F5.4 integrates it fully."""
        self.budget_tracker.add_tokens(token_count)


def _selected(value: str, selectors: tuple[str, ...]) -> bool:
    return "*" in selectors or value in selectors


def _path_selected(path: str | None, patterns: tuple[str, ...]) -> bool:
    candidate = path or ""
    return any(pattern == "*" or fnmatchcase(candidate, pattern) for pattern in patterns)


def _decision(
    request: ToolPolicyRequest,
    rule: ToolPolicyRule,
    *,
    allowed: bool,
    reason: DecisionReason,
) -> ToolPolicyDecision:
    return ToolPolicyDecision(
        request=request,
        allowed=allowed,
        rule_id=rule.rule_id,
        rule_effect=rule.effect,
        approval_required=rule.approval_required,
        reason=reason,
    )


__all__ = [
    "DecisionReason",
    "PolicyDecisionIntegrityError",
    "PolicyDeniedError",
    "PolicyEffect",
    "PolicyEngine",
    "PolicyEngineError",
    "ToolPolicyDecision",
    "ToolPolicyRequest",
    "ToolPolicyRule",
    "TrustMode",
]
