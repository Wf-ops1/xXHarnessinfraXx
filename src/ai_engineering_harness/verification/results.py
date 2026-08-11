"""Strict, commit-bound verification result contracts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ai_engineering_harness.contracts import VerificationGateId

_GIT_SHA_PATTERN = r"^[0-9a-f]{40}$"


class GateStatus(str, Enum):
    """Closed outcome vocabulary for one configured verification gate."""

    PASSED = "PASSED"
    FAILED = "FAILED"
    ERROR = "ERROR"
    SKIPPED_NOT_APPLICABLE = "SKIPPED_NOT_APPLICABLE"


class GateRequirement(BaseModel):
    """One policy-derived gate and whether it blocks completion."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    gate_id: VerificationGateId
    required: bool


class GateResult(BaseModel):
    """Bounded, redacted evidence produced by one gate attempt."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    result_schema_version: str = Field(default="1.0", pattern=r"^1\.0$")
    gate_id: VerificationGateId
    status: GateStatus
    required: bool
    argv: tuple[str, ...]
    cwd: str = Field(min_length=1)
    started_at: datetime
    finished_at: datetime
    duration_ms: int = Field(ge=0)
    exit_code: int | None
    stdout: str
    stderr: str
    verified_commit_sha: str = Field(pattern=_GIT_SHA_PATTERN)

    @field_validator("argv", mode="before")
    @classmethod
    def freeze_argv(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @field_validator("argv")
    @classmethod
    def validate_argv(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(type(part) is not str or not part for part in value):
            raise ValueError("gate argv must contain only non-empty strings")
        return value

    @field_validator("started_at", "finished_at")
    @classmethod
    def require_utc_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("verification timestamps must be timezone-aware UTC")
        if value.utcoffset() != timedelta(0):
            raise ValueError("verification timestamps must use UTC")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_outcome(self) -> Self:
        if self.finished_at < self.started_at:
            raise ValueError("gate finished_at cannot precede started_at")
        expected_duration = int(
            (self.finished_at - self.started_at).total_seconds() * 1000
        )
        if self.duration_ms != expected_duration:
            raise ValueError("gate duration_ms must match its UTC timestamps")
        if self.status is GateStatus.SKIPPED_NOT_APPLICABLE:
            if self.required:
                raise ValueError("a required gate cannot be skipped as not applicable")
            if self.argv or self.exit_code is not None or self.stdout or self.stderr:
                raise ValueError("a not-applicable gate cannot contain process evidence")
            return self
        if not self.argv:
            raise ValueError("an executed or attempted gate requires argv")
        if self.status is GateStatus.PASSED and self.exit_code != 0:
            raise ValueError("a passed gate requires exit code zero")
        if self.status is GateStatus.FAILED and (
            self.exit_code is None or self.exit_code == 0
        ):
            raise ValueError("a failed gate requires a non-zero exit code")
        return self

    @property
    def gate_type(self) -> str:
        """Compatibility alias for the pre-F4.7 public attribute."""

        return self.gate_id

    @property
    def command(self) -> str:
        """Render argv only for human-facing compatibility."""

        return " ".join(self.argv)

    @property
    def passed(self) -> bool:
        """Compatibility projection; persistence uses the closed status."""

        return self.status is GateStatus.PASSED


class VerificationSuiteResult(BaseModel):
    """Immutable ordered result for one policy-derived suite attempt."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    result_schema_version: str = Field(default="1.0", pattern=r"^1\.0$")
    verified_commit_sha: str = Field(pattern=_GIT_SHA_PATTERN)
    gate_results: tuple[GateResult, ...]

    @field_validator("gate_results", mode="before")
    @classmethod
    def freeze_results(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def validate_suite_identity(self) -> Self:
        gate_ids = tuple(result.gate_id for result in self.gate_results)
        if len(set(gate_ids)) != len(gate_ids):
            raise ValueError("verification suite results must use unique gate ids")
        if any(
            result.verified_commit_sha != self.verified_commit_sha
            for result in self.gate_results
        ):
            raise ValueError("every gate result must match the suite commit")
        return self

    @property
    def total_gates(self) -> int:
        return len(self.gate_results)

    @property
    def passed_gates(self) -> int:
        return sum(
            result.status is GateStatus.PASSED for result in self.gate_results
        )

    @property
    def executed_required_gates(self) -> int:
        return sum(
            result.required
            and result.status is not GateStatus.SKIPPED_NOT_APPLICABLE
            for result in self.gate_results
        )

    @property
    def all_passed(self) -> bool:
        """Return the F4.7 completion decision, never vacuous truth."""

        return (
            self.executed_required_gates > 0
            and all(
                not result.required or result.status is GateStatus.PASSED
                for result in self.gate_results
            )
        )


__all__ = [
    "GateRequirement",
    "GateResult",
    "GateStatus",
    "VerificationSuiteResult",
]
