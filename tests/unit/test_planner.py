"""Strict F4.4 planning contract and fail-closed specificity tests."""

from __future__ import annotations

import inspect

import pytest
from pydantic import ValidationError

from ai_engineering_harness.contracts import PlanContent, PlanDocument
from ai_engineering_harness.runtime.planner import Planner

_DIGEST = "sha256:" + "1" * 64


def _valid_content() -> dict[str, object]:
    return {
        "objective": "Modify the indexed logging symbol to satisfy AC-1",
        "acceptance_criteria": [
            {
                "order": 1,
                "criterion_id": "ac-1",
                "description": "The validated logging requirement is satisfied",
                "evidence_refs": [f"artifact:acceptance_criteria@{_DIGEST}"],
            }
        ],
        "targets": [
            {
                "target_id": "logging-target",
                "path": "src/logging.py",
                "symbol": "logging",
                "change_kind": "modify",
                "evidence_refs": ["symbol:src/logging.py:8:logging"],
            }
        ],
        "steps": [
            {
                "order": 1,
                "step_id": "change-logging",
                "description": "Change the evidence-bound logging function",
                "target_ids": ["logging-target"],
                "tools": ["file_writer"],
            }
        ],
        "planned_tools": ["file_writer"],
        "risks": [
            {
                "risk_id": "logging-regression",
                "description": "Existing logging behavior may regress",
                "mitigation": "Run the compiled verification gates",
            }
        ],
        "applicable_gates": ["typecheck", "lint", "unit_test", "build"],
        "rollback_strategy": {
            "triggers": ["A required gate fails"],
            "actions": ["Revert the target change"],
            "verification": ["Repeat every required gate"],
        },
        "completion_conditions": [
            {
                "condition_id": "complete-ac-1",
                "criterion_id": "ac-1",
                "description": "Evidence demonstrates AC-1",
            }
        ],
        "remaining_gaps": [],
    }


def test_plan_contract_is_strict_frozen_versioned_and_tuple_backed() -> None:
    document = PlanDocument.model_validate(
        {
            **_valid_content(),
            "schema_version": "1.0",
            "execution_id": "exec-plan-contract",
            "workflow_name": "new-feature",
            "base_commit_sha": "a" * 40,
            "context_digest": _DIGEST,
            "graph_input_digest": "sha256:" + "2" * 64,
        }
    )

    assert document.schema_version == "1.0"
    assert isinstance(document.steps, tuple)
    assert isinstance(document.steps[0].target_ids, tuple)
    with pytest.raises(ValidationError):
        document.objective = "changed"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        PlanContent.model_validate({**_valid_content(), "unexpected": True})


def test_provider_schema_is_derived_from_content_and_excludes_trusted_identity() -> None:
    schema = Planner.response_schema()
    properties = schema["properties"]

    assert schema == PlanContent.model_json_schema()
    assert "objective" in properties
    assert "execution_id" not in properties
    assert "context_digest" not in properties
    assert Planner.schema_digest().startswith("sha256:")


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        (
            lambda value: value["targets"][0].update(path="../escape.py"),
            "normalized POSIX",
        ),
        (
            lambda value: value["steps"][0].update(order=2),
            "contiguous",
        ),
        (
            lambda value: value["steps"][0].update(target_ids=["unknown-target"]),
            "unknown target",
        ),
        (
            lambda value: value.update(planned_tools=["invented-tool"]),
            "planned_tools",
        ),
        (
            lambda value: value.update(
                remaining_gaps=[
                    {
                        "gap_id": "missing-authority",
                        "description": "Authority is absent",
                        "action": "Request explicit authority",
                        "blocking": True,
                    }
                ]
            ),
            "blocking remaining gap",
        ),
    ],
)
def test_invalid_generic_or_unbound_plan_content_fails_closed(mutation, match: str) -> None:
    content = _valid_content()
    mutation(content)

    with pytest.raises(ValidationError, match=match):
        PlanContent.model_validate(content)


def test_legacy_fabricated_planner_inputs_are_not_supported() -> None:
    parameters = inspect.signature(Planner.create_plan).parameters

    assert "context_package" not in parameters
    assert "intent" not in parameters
    assert {
        "context_report",
        "context_digest",
        "context_request",
        "verification_policy",
        "tool_policy",
    }.issubset(parameters)
