"""Focused F5.2 proofs for the unified default-deny policy engine."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ai_engineering_harness.governance import (
    PolicyDecisionIntegrityError,
    PolicyDeniedError,
    PolicyEngine,
    ToolPolicyDecision,
    ToolPolicyRequest,
    ToolPolicyRule,
)
from ai_engineering_harness.tools import (
    ToolDefinition,
    ToolRegistration,
    ToolRouter,
    ToolUnauthorizedError,
)


def _request(**overrides: object) -> ToolPolicyRequest:
    values: dict[str, object] = {
        "role": "code_agent",
        "node_id": "edit",
        "workflow": "feature",
        "trust_mode": "restricted",
        "tool": "apply_patch",
        "operation": "write",
        "path": "src/module.py",
        "approval_granted": False,
    }
    values.update(overrides)
    return ToolPolicyRequest.model_validate(values)


def _allow_rule(**overrides: object) -> ToolPolicyRule:
    values: dict[str, object] = {
        "rule_id": "allow-code-edit",
        "effect": "allow",
        "roles": ("code_agent",),
        "node_ids": ("edit",),
        "workflows": ("feature",),
        "trust_modes": ("restricted",),
        "tools": ("apply_patch",),
        "operations": ("write",),
        "path_patterns": ("src/*.py",),
    }
    values.update(overrides)
    return ToolPolicyRule.model_validate(values)


def test_default_deny_ignores_legacy_wildcard_configuration() -> None:
    engine = PolicyEngine(config={"tools": {"allowed": ["*"]}})

    decision = engine.evaluate(_request())

    assert decision.allowed is False
    assert decision.rule_id == "default-deny"
    assert decision.rule_effect == "deny"
    assert decision.reason == "default-deny"
    with pytest.raises(PolicyDeniedError):
        engine.require_allowed(decision)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("role", "requirement_analyst"),
        ("node_id", "review"),
        ("workflow", "incident"),
        ("trust_mode", "trusted"),
        ("tool", "read_file"),
        ("operation", "read"),
        ("path", "docs/module.py"),
    ),
)
def test_every_request_dimension_participates_in_matching(field: str, value: str) -> None:
    engine = PolicyEngine(rules=(_allow_rule(),))

    assert engine.evaluate(_request(**{field: value})).reason == "default-deny"


def test_deny_wins_and_rule_identity_is_deterministic() -> None:
    allow = _allow_rule(rule_id="z-allow", path_patterns=("*",))
    deny_b = ToolPolicyRule(
        rule_id="b-deny",
        effect="deny",
        roles=("code_agent",),
        node_ids=("edit",),
        workflows=("feature",),
        trust_modes=("restricted",),
        tools=("apply_patch",),
        operations=("write",),
        path_patterns=("src/*",),
    )
    deny_a = deny_b.model_copy(update={"rule_id": "a-deny"})
    engine = PolicyEngine(rules=(allow, deny_b, deny_a))

    decision = engine.evaluate(_request())

    assert decision.allowed is False
    assert decision.rule_id == "a-deny"
    assert decision.reason == "rule-deny"


def test_approval_bound_allow_rule_fails_closed_until_granted() -> None:
    engine = PolicyEngine(rules=(_allow_rule(approval_required=True),))

    unresolved = engine.evaluate(_request())
    approved = engine.evaluate(_request(approval_granted=True))

    assert unresolved.allowed is False
    assert unresolved.rule_id == "allow-code-edit"
    assert unresolved.reason == "approval-required"
    assert approved.allowed is True
    assert approved.reason == "rule-allow"
    with pytest.raises(ValidationError, match="approval-bound"):
        ToolPolicyDecision(
            request=_request(),
            allowed=True,
            rule_id="forged-approval",
            rule_effect="allow",
            approval_required=True,
            reason="rule-allow",
        )


def test_decision_digest_is_stable_and_engine_rejects_forgery() -> None:
    engine = PolicyEngine(rules=(_allow_rule(),))
    decision = engine.evaluate(_request())
    round_tripped = ToolPolicyDecision.model_validate_json(decision.model_dump_json())

    assert decision.allowed is True
    assert round_tripped.digest() == decision.digest()
    forged = decision.model_copy(update={"rule_id": "forged"})
    with pytest.raises(PolicyDecisionIntegrityError):
        engine.require_allowed(forged)


def test_paths_are_canonical_relative_and_rules_are_unambiguous() -> None:
    assert _request(path="src\\module.py").path == "src/module.py"
    with pytest.raises(ValidationError, match="relative"):
        _request(path="C:\\repo\\module.py")
    with pytest.raises(ValidationError, match="traverse"):
        _request(path="../module.py")
    with pytest.raises(ValueError, match="identities"):
        PolicyEngine(rules=(_allow_rule(), _allow_rule()))


def test_router_requires_a_verified_decision_matching_the_real_target() -> None:
    effects: list[dict[str, object]] = []
    router = ToolRouter(
        ("apply_patch",),
        registrations={
            "apply_patch": ToolRegistration(
                definition=ToolDefinition(
                    name="apply_patch",
                    description="test write",
                    parameters={
                        "type": "object",
                        "properties": {"path": {"type": "string"}},
                        "required": ["path"],
                        "additionalProperties": False,
                    },
                ),
                handler=lambda payload: effects.append(payload) or {"ok": True},
                operation="write",
                path_argument="path",
            )
        },
    )
    engine = PolicyEngine(rules=(_allow_rule(path_patterns=("*",)),))
    decision = engine.evaluate(_request())

    with pytest.raises(ToolUnauthorizedError, match="verified"):
        router.dispatch("apply_patch", {"path": "src/module.py"})
    with pytest.raises(ToolUnauthorizedError, match="does not match"):
        router.dispatch(
            "apply_patch",
            {"path": "src/other.py"},
            policy_engine=engine,
            decision=decision,
        )
    result = router.dispatch(
        "apply_patch",
        {"path": "src/module.py"},
        policy_engine=engine,
        decision=decision,
    )

    assert result == {"ok": True}
    assert effects == [{"path": "src/module.py"}]
