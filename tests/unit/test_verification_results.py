"""F4.7 verification result contracts and fail-closed completion decision."""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from ai_engineering_harness.verification import (
    GateResult,
    GateStatus,
    VerificationSuiteResult,
)

_COMMIT = "a" * 40
_STARTED = datetime(2026, 8, 11, 17, 0, tzinfo=UTC)


def _result(
    *,
    gate_id: str = "unit_test",
    status: GateStatus = GateStatus.PASSED,
    required: bool = True,
    commit: str = _COMMIT,
) -> GateResult:
    skipped = status is GateStatus.SKIPPED_NOT_APPLICABLE
    return GateResult.model_validate(
        {
            "gate_id": gate_id,
            "status": status,
            "required": required,
            "argv": () if skipped else ("python", "-m", "pytest"),
            "cwd": ".",
            "started_at": _STARTED,
            "finished_at": _STARTED if skipped else _STARTED + timedelta(milliseconds=25),
            "duration_ms": 0 if skipped else 25,
            "exit_code": None if skipped else (0 if status is GateStatus.PASSED else 1),
            "stdout": "" if skipped else "redacted output",
            "stderr": "",
            "verified_commit_sha": commit,
        }
    )


def test_suite_completion_is_not_vacuously_true() -> None:
    result = VerificationSuiteResult(
        verified_commit_sha=_COMMIT,
        gate_results=(),
    )

    assert result.total_gates == 0
    assert result.executed_required_gates == 0
    assert result.all_passed is False


def test_optional_not_applicable_does_not_replace_required_execution() -> None:
    suite = VerificationSuiteResult(
        verified_commit_sha=_COMMIT,
        gate_results=(
            _result(),
            _result(
                gate_id="security_scan",
                status=GateStatus.SKIPPED_NOT_APPLICABLE,
                required=False,
            ),
        ),
    )

    assert suite.total_gates == 2
    assert suite.passed_gates == 1
    assert suite.executed_required_gates == 1
    assert suite.all_passed is True


def test_required_failure_and_error_block_completion() -> None:
    failed = VerificationSuiteResult(
        verified_commit_sha=_COMMIT,
        gate_results=(_result(status=GateStatus.FAILED),),
    )
    errored = VerificationSuiteResult(
        verified_commit_sha=_COMMIT,
        gate_results=(_result(status=GateStatus.ERROR),),
    )

    assert failed.all_passed is False
    assert errored.all_passed is False


def test_required_gate_cannot_be_skipped() -> None:
    with pytest.raises(ValidationError, match="required gate cannot be skipped"):
        _result(status=GateStatus.SKIPPED_NOT_APPLICABLE)


def test_suite_rejects_duplicate_gate_or_other_commit() -> None:
    with pytest.raises(ValidationError, match="unique gate ids"):
        VerificationSuiteResult(
            verified_commit_sha=_COMMIT,
            gate_results=(_result(), _result()),
        )

    with pytest.raises(ValidationError, match="match the suite commit"):
        VerificationSuiteResult(
            verified_commit_sha=_COMMIT,
            gate_results=(_result(commit="b" * 40),),
        )
