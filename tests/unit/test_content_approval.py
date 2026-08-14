from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ai_engineering_harness.contracts import ApprovalStatus
from ai_engineering_harness.governance import (
    ApprovalContent,
    ApprovalContractError,
    ApprovalGateResult,
    ApprovalManager,
    ApprovalPersistenceError,
    ApprovalRequest,
)


def _content(
    *,
    artifact: str = "sha256:" + "1" * 64,
    candidate: str = "4" * 40,
    diff: str = "sha256:" + "3" * 64,
    plan: str = "sha256:" + "2" * 64,
    gate_digest: str = "sha256:" + "5" * 64,
    suite_digest: str = "sha256:" + "6" * 64,
) -> ApprovalContent:
    return ApprovalContent(
        execution_id="exec-content-approval",
        artifact_digest=artifact,
        plan_digest=plan,
        diff_digest=diff,
        candidate_commit_sha=candidate,
        gate_results=(
            ApprovalGateResult(
                gate_id="unit_test",
                required=True,
                status="PASSED",
                result_digest=gate_digest,
            ),
        ),
        verification_suite_digest=suite_digest,
    )


def _pending(content: ApprovalContent | None = None) -> ApprovalRequest:
    requested_at = datetime(2026, 8, 14, 12, tzinfo=UTC)
    return ApprovalRequest.pending(
        content=content or _content(),
        reason="Promote the exact verified candidate",
        requested_at=requested_at,
        expires_at=requested_at + timedelta(hours=1),
    )


def _execution_directory(root: Path) -> Path:
    directory = root / ".harness" / "state" / "executions" / "exec-content-approval"
    directory.mkdir(parents=True)
    return directory


def test_canonical_request_and_decision_contain_every_bound_field(tmp_path: Path) -> None:
    execution_directory = _execution_directory(tmp_path)
    manager = ApprovalManager(tmp_path)
    pending = _pending()

    path = manager.publish(pending)
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert path.name == "approval-request.json"
    assert set(payload) == {
        "approval_schema_version",
        "execution_id",
        "artifact_digest",
        "plan_digest",
        "diff_digest",
        "candidate_commit_sha",
        "gate_results",
        "verification_suite_digest",
        "reason",
        "requested_at",
        "expires_at",
        "status",
        "approver_id",
        "decided_at",
        "comment",
        "subject_digest",
    }
    assert payload["status"] == "PENDING"
    assert payload["approver_id"] is None
    assert payload["decided_at"] is None
    assert payload["comment"] is None
    assert path.read_text(encoding="utf-8") == pending.canonical_json()

    decided_at = pending.requested_at + timedelta(minutes=5)
    approved = pending.approve(
        approver_id="reviewer-f56",
        decided_at=decided_at,
        comment="Reviewed candidate, plan, diff and gates",
    )
    manager.publish(approved)

    assert manager.load(pending.execution_id) == approved
    assert approved.status is ApprovalStatus.APPROVED
    assert approved.approver_id == "reviewer-f56"
    assert approved.decided_at == decided_at
    assert not (execution_directory / "approval_request.json").exists()


def test_every_normative_content_change_changes_the_subject_digest() -> None:
    baseline = _pending()
    variants = (
        _content(artifact="sha256:" + "7" * 64),
        _content(candidate="7" * 40),
        _content(diff="sha256:" + "8" * 64),
        _content(plan="sha256:" + "9" * 64),
        _content(gate_digest="sha256:" + "a" * 64),
        _content(suite_digest="sha256:" + "b" * 64),
    )

    for content in variants:
        assert _pending(content).subject_digest != baseline.subject_digest


def test_expired_or_redecided_request_fails_closed() -> None:
    pending = _pending()

    with pytest.raises(ApprovalContractError, match="expiration"):
        pending.approve(
            approver_id="late-reviewer",
            decided_at=pending.expires_at,
        )

    expired = pending.expire(decided_at=pending.expires_at)
    assert expired.status is ApprovalStatus.EXPIRED
    assert expired.approver_id is None
    assert expired.comment == "approval_expired"
    with pytest.raises(ApprovalContractError, match="pending"):
        expired.approve(
            approver_id="late-reviewer",
            decided_at=pending.expires_at + timedelta(seconds=1),
        )


def test_projection_tamper_is_not_silently_rewritten(tmp_path: Path) -> None:
    _execution_directory(tmp_path)
    manager = ApprovalManager(tmp_path)
    request = _pending()
    path = manager.publish(request)
    path.write_text(request.canonical_json() + "\n", encoding="utf-8")

    with pytest.raises(ApprovalPersistenceError, match="invalid|noncanonical"):
        manager.load(request.execution_id)


def test_legacy_underscored_file_is_not_promotion_evidence(tmp_path: Path) -> None:
    execution_directory = _execution_directory(tmp_path)
    (execution_directory / "approval_request.json").write_text(
        '{"execution_id":"exec-content-approval","status":"APPROVED"}\n',
        encoding="utf-8",
    )

    assert ApprovalManager(tmp_path).load("exec-content-approval") is None
