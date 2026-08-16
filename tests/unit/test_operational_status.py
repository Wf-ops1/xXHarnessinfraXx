"""Focused regression coverage for the F6.5 operational status projection."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from ai_engineering_harness.contracts.execution import (
    EXECUTION_RECORD_SCHEMA_VERSION,
    ApprovalStatus,
    ExecutionFailure,
    ExecutionRecord,
    ExecutionState,
)
from ai_engineering_harness.runtime import (
    ExecutionNextAction,
    ExecutionStatusView,
)
from ai_engineering_harness.runtime.execution_lifecycle import (
    ExecutionLifecycleService,
)

_CREATED_AT = datetime(2026, 8, 16, 12, 0, tzinfo=UTC)

_EXPECTED_ACTIONS = {
    ExecutionState.INITIATED: ExecutionNextAction.RESUME,
    ExecutionState.PREPARING_WORKSPACE: ExecutionNextAction.RESUME,
    ExecutionState.CONTEXT_ASSEMBLING: ExecutionNextAction.RESUME,
    ExecutionState.BLOCKED_INSUFFICIENT_CONTEXT: ExecutionNextAction.INSPECT,
    ExecutionState.BLOCKED_PREREQUISITE: ExecutionNextAction.INSPECT,
    ExecutionState.BLOCKED_BASE_CHANGED: ExecutionNextAction.INSPECT,
    ExecutionState.PLANNING: ExecutionNextAction.RESUME,
    ExecutionState.GENERATING_PLAN: ExecutionNextAction.RESUME,
    ExecutionState.EXECUTING: ExecutionNextAction.RESUME,
    ExecutionState.VERIFYING: ExecutionNextAction.VERIFY,
    ExecutionState.AWAITING_APPROVAL: ExecutionNextAction.APPROVE,
    ExecutionState.PAUSED_AWAITING_APPROVAL: ExecutionNextAction.APPROVE,
    ExecutionState.PROMOTING: ExecutionNextAction.RESUME,
    ExecutionState.REINDEXING: ExecutionNextAction.RESUME,
    ExecutionState.KNOWLEDGE_SYNC: ExecutionNextAction.RESUME,
    ExecutionState.GENERATING_EVIDENCE: ExecutionNextAction.RESUME,
    ExecutionState.ROLLBACK_IN_PROGRESS: ExecutionNextAction.RESUME,
    ExecutionState.BLOCKED_ROLLBACK: ExecutionNextAction.MANUAL_INTERVENTION,
    ExecutionState.COMPENSATED: ExecutionNextAction.NONE,
    ExecutionState.DRY_RUN_COMPLETED: ExecutionNextAction.NONE,
    ExecutionState.COMPLETED: ExecutionNextAction.NONE,
    ExecutionState.CANCELLED: ExecutionNextAction.NONE,
    ExecutionState.FAILED: ExecutionNextAction.INSPECT,
    ExecutionState.FAILED_BUDGET_EXCEEDED: ExecutionNextAction.INSPECT,
    ExecutionState.FAILED_RETRY_EXHAUSTED: ExecutionNextAction.INSPECT,
}

_BLOCKED_STATES = {
    ExecutionState.BLOCKED_INSUFFICIENT_CONTEXT,
    ExecutionState.BLOCKED_PREREQUISITE,
    ExecutionState.BLOCKED_BASE_CHANGED,
    ExecutionState.AWAITING_APPROVAL,
    ExecutionState.PAUSED_AWAITING_APPROVAL,
    ExecutionState.BLOCKED_ROLLBACK,
    ExecutionState.FAILED,
    ExecutionState.FAILED_BUDGET_EXCEEDED,
    ExecutionState.FAILED_RETRY_EXHAUSTED,
}


def _record(
    state: ExecutionState,
    *,
    failure: ExecutionFailure | None = None,
) -> ExecutionRecord:
    return ExecutionRecord(
        record_schema_version=EXECUTION_RECORD_SCHEMA_VERSION,
        revision=7,
        execution_id="exec-operational-status",
        workflow_name="operational-status",
        artifact_digest=f"sha256:{'a' * 64}",
        base_commit_sha="b" * 40,
        original_branch="main",
        worktree_path=None,
        current_node_id="execute",
        current_state=state,
        attempt_by_node={"execute": 3},
        created_at=_CREATED_AT,
        updated_at=_CREATED_AT + timedelta(seconds=2, milliseconds=345),
        configuration_digest=f"sha256:{'c' * 64}",
        approval_status=(
            ApprovalStatus.PENDING
            if state
            in {
                ExecutionState.AWAITING_APPROVAL,
                ExecutionState.PAUSED_AWAITING_APPROVAL,
            }
            else ApprovalStatus.NOT_REQUIRED
        ),
        candidate_commit_sha=None,
        promotion_commit_sha=None,
        failure=failure,
    )


@pytest.mark.parametrize("state", tuple(ExecutionState))
def test_status_projection_has_closed_action_and_blocker_mapping(
    state: ExecutionState,
) -> None:
    view = ExecutionLifecycleService._status_view(_record(state))

    assert view.status_schema_version == "1.0"
    assert view.current_attempt == 3
    assert view.duration_ms == 2_345
    assert view.next_action is _EXPECTED_ACTIONS[state]
    assert (view.blocker is not None) is (state in _BLOCKED_STATES)


def test_failure_blocker_is_typed_redacted_and_serialization_safe() -> None:
    raw_secret = "sk-" + "x" * 40
    view = ExecutionLifecycleService._status_view(
        _record(
            ExecutionState.FAILED,
            failure=ExecutionFailure(
                code="MODEL_PROVIDER_FAILED",
                message=f"api_key={raw_secret}",
                retryable=False,
                node_id="execute",
            ),
        )
    )

    assert view.blocker is not None
    assert view.blocker.code == "MODEL_PROVIDER_FAILED"
    assert raw_secret not in view.model_dump_json()
    assert "[REDACTED_SECRET]" in view.blocker.message


def test_status_contract_is_strict_frozen_and_rejects_unknown_fields() -> None:
    view = ExecutionLifecycleService._status_view(_record(ExecutionState.COMPLETED))

    with pytest.raises(ValidationError):
        ExecutionStatusView.model_validate(
            {**view.model_dump(mode="python"), "unexpected": "field"}
        )
    with pytest.raises(ValidationError):
        view.current_attempt = 99  # type: ignore[misc]
