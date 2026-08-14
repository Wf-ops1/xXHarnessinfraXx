"""Strict content-bound approval contracts and their canonical projection."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Literal, Self
from uuid import uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from ai_engineering_harness.contracts import ApprovalStatus
from ai_engineering_harness.contracts.execution import ExecutionId, validate_execution_id
from ai_engineering_harness.persistence.base import canonical_json_digest, canonical_json_object

_DIGEST_PATTERN = r"^sha256:[0-9a-f]{64}$"
_GIT_SHA_PATTERN = r"^[0-9a-f]{40}$"
_NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
_GateStatus = Literal["PASSED", "FAILED", "ERROR", "SKIPPED_NOT_APPLICABLE"]
_DECIDED_STATUSES = frozenset(
    {
        ApprovalStatus.APPROVED,
        ApprovalStatus.EXPIRED,
        ApprovalStatus.INVALIDATED,
    }
)


class ApprovalError(RuntimeError):
    """Base failure for content-bound approval handling."""


class ApprovalContractError(ApprovalError, ValueError):
    """An approval document or transition violates the strict contract."""


class ApprovalPersistenceError(ApprovalError):
    """The canonical approval projection could not be published or loaded."""


class ApprovalGateResult(BaseModel):
    """Minimal immutable identity of one persisted verification gate outcome."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    gate_id: _NonEmptyStr
    required: bool
    status: _GateStatus
    result_digest: str = Field(pattern=_DIGEST_PATTERN)


class ApprovalContent(BaseModel):
    """Exact executable content that one promotion decision may authorize."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    execution_id: ExecutionId
    artifact_digest: str = Field(pattern=_DIGEST_PATTERN)
    plan_digest: str = Field(pattern=_DIGEST_PATTERN)
    diff_digest: str = Field(pattern=_DIGEST_PATTERN)
    candidate_commit_sha: str = Field(pattern=_GIT_SHA_PATTERN)
    gate_results: tuple[ApprovalGateResult, ...]
    verification_suite_digest: str = Field(pattern=_DIGEST_PATTERN)

    @field_validator("gate_results", mode="before")
    @classmethod
    def freeze_gate_results(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def require_complete_unique_gate_results(self) -> Self:
        if not self.gate_results:
            raise ValueError("approval content requires at least one gate result")
        gate_ids = tuple(result.gate_id for result in self.gate_results)
        if len(set(gate_ids)) != len(gate_ids):
            raise ValueError("approval gate results must use unique gate ids")
        return self

    def subject_payload(self) -> dict[str, object]:
        """Return the detached JSON identity covered by a human decision."""

        return {
            "artifact_digest": self.artifact_digest,
            "candidate_commit_sha": self.candidate_commit_sha,
            "diff_digest": self.diff_digest,
            "execution_id": self.execution_id,
            "gate_results": [
                result.model_dump(mode="json") for result in self.gate_results
            ],
            "plan_digest": self.plan_digest,
            "verification_suite_digest": self.verification_suite_digest,
        }


class ApprovalRequest(ApprovalContent):
    """Canonical ``approval-request.json`` including request and decision state."""

    approval_schema_version: Literal["1.0"] = "1.0"
    reason: _NonEmptyStr
    requested_at: datetime
    expires_at: datetime
    status: ApprovalStatus
    approver_id: _NonEmptyStr | None
    decided_at: datetime | None
    comment: _NonEmptyStr | None
    subject_digest: str = Field(pattern=_DIGEST_PATTERN)

    @field_validator("requested_at", "expires_at", "decided_at")
    @classmethod
    def require_utc_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("approval timestamps must be timezone-aware UTC values")
        if value.utcoffset() != timedelta(0):
            raise ValueError("approval timestamps must use UTC")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_decision_and_binding(self) -> Self:
        if self.expires_at <= self.requested_at:
            raise ValueError("approval expiration must follow the request timestamp")
        expected_subject = self.calculate_subject_digest(
            content=ApprovalContent.model_validate(
                self.model_dump(
                    mode="python",
                    include={
                        "execution_id",
                        "artifact_digest",
                        "plan_digest",
                        "diff_digest",
                        "candidate_commit_sha",
                        "gate_results",
                        "verification_suite_digest",
                    },
                )
            ),
            reason=self.reason,
            requested_at=self.requested_at,
            expires_at=self.expires_at,
        )
        if self.subject_digest != expected_subject:
            raise ValueError("approval subject digest does not match its content")
        if self.status is ApprovalStatus.PENDING:
            if any(
                value is not None
                for value in (self.approver_id, self.decided_at, self.comment)
            ):
                raise ValueError("pending approval cannot contain decision fields")
            return self
        if self.status not in _DECIDED_STATUSES:
            raise ValueError("approval request status is not supported")
        if self.decided_at is None or self.decided_at < self.requested_at:
            raise ValueError("decided approval requires an ordered decision timestamp")
        if self.status is ApprovalStatus.APPROVED:
            if self.approver_id is None:
                raise ValueError("approved request requires an approver id")
            if self.decided_at >= self.expires_at:
                raise ValueError("approval decision must precede expiration")
        elif self.approver_id is not None:
            raise ValueError("system expiration or invalidation cannot claim an approver")
        return self

    @classmethod
    def pending(
        cls,
        *,
        content: ApprovalContent,
        reason: str,
        requested_at: datetime,
        expires_at: datetime,
    ) -> ApprovalRequest:
        """Create one undecided request over an exact immutable content snapshot."""

        subject_digest = cls.calculate_subject_digest(
            content=content,
            reason=reason,
            requested_at=requested_at,
            expires_at=expires_at,
        )
        return cls.model_validate(
            {
                **content.model_dump(mode="python"),
                "approval_schema_version": "1.0",
                "reason": reason,
                "requested_at": requested_at,
                "expires_at": expires_at,
                "status": ApprovalStatus.PENDING,
                "approver_id": None,
                "decided_at": None,
                "comment": None,
                "subject_digest": subject_digest,
            }
        )

    @staticmethod
    def calculate_subject_digest(
        *,
        content: ApprovalContent,
        reason: str,
        requested_at: datetime,
        expires_at: datetime,
    ) -> str:
        """Bind content, intent and validity window into one deterministic digest."""

        if not isinstance(content, ApprovalContent):
            raise ApprovalContractError("content must be an ApprovalContent")
        if type(reason) is not str or not reason.strip() or reason != reason.strip():
            raise ApprovalContractError("reason must be a non-empty trimmed string")
        for value, label in (
            (requested_at, "requested_at"),
            (expires_at, "expires_at"),
        ):
            if value.tzinfo is None or value.utcoffset() != timedelta(0):
                raise ApprovalContractError(f"{label} must use timezone-aware UTC")
        payload = content.subject_payload()
        payload.update(
            {
                "expires_at": expires_at.astimezone(UTC).isoformat(),
                "reason": reason,
                "requested_at": requested_at.astimezone(UTC).isoformat(),
            }
        )
        return canonical_json_digest(canonical_json_object(payload))

    def approve(
        self,
        *,
        approver_id: str,
        decided_at: datetime,
        comment: str | None = None,
    ) -> ApprovalRequest:
        """Return the immutable approved successor of a pending request."""

        if self.status is not ApprovalStatus.PENDING:
            raise ApprovalContractError("only a pending request can be approved")
        return self._decision(
            status=ApprovalStatus.APPROVED,
            approver_id=approver_id,
            decided_at=decided_at,
            comment=comment,
        )

    def expire(self, *, decided_at: datetime) -> ApprovalRequest:
        """Return a fail-closed expired successor without a human identity."""

        if self.status not in {ApprovalStatus.PENDING, ApprovalStatus.APPROVED}:
            raise ApprovalContractError("only a live request can expire")
        return self._decision(
            status=ApprovalStatus.EXPIRED,
            approver_id=None,
            decided_at=decided_at,
            comment="approval_expired",
        )

    def invalidate(self, *, decided_at: datetime, reason: str) -> ApprovalRequest:
        """Return a fail-closed invalidated successor with an explicit reason."""

        if self.status not in {ApprovalStatus.PENDING, ApprovalStatus.APPROVED}:
            raise ApprovalContractError("only a live request can be invalidated")
        return self._decision(
            status=ApprovalStatus.INVALIDATED,
            approver_id=None,
            decided_at=decided_at,
            comment=reason,
        )

    def content(self) -> ApprovalContent:
        """Project only the immutable executable content."""

        return ApprovalContent.model_validate(
            self.model_dump(
                mode="python",
                include={
                    "execution_id",
                    "artifact_digest",
                    "plan_digest",
                    "diff_digest",
                    "candidate_commit_sha",
                    "gate_results",
                    "verification_suite_digest",
                },
            )
        )

    def canonical_json(self) -> str:
        """Serialize the complete projection deterministically."""

        return canonical_json_object(self.model_dump(mode="json"))

    def _decision(
        self,
        *,
        status: ApprovalStatus,
        approver_id: str | None,
        decided_at: datetime,
        comment: str | None,
    ) -> ApprovalRequest:
        document = self.model_dump(mode="python")
        document.update(
            {
                "status": status,
                "approver_id": approver_id,
                "decided_at": decided_at,
                "comment": comment,
            }
        )
        try:
            return ApprovalRequest.model_validate(document)
        except ValueError as exc:
            raise ApprovalContractError(str(exc)) from exc


class ApprovalManager:
    """Publish and load the exact approval projection under one execution root."""

    filename = "approval-request.json"

    def __init__(self, project_root: Path):
        try:
            root = Path(project_root).resolve(strict=True)
        except (OSError, RuntimeError, ValueError) as exc:
            raise ApprovalPersistenceError("project_root must resolve") from exc
        if not root.is_dir():
            raise ApprovalPersistenceError("project_root must be a directory")
        self.project_root = root
        self.execution_root = root / ".harness" / "state" / "executions"

    def path(self, execution_id: str) -> Path:
        """Return the confined canonical path without creating state."""

        validated_id = validate_execution_id(execution_id)
        destination = self.execution_root / validated_id / self.filename
        try:
            destination.relative_to(self.project_root)
        except ValueError as exc:
            raise ApprovalPersistenceError("approval path escaped project root") from exc
        return destination

    def publish(self, request: ApprovalRequest) -> Path:
        """Atomically replace the projection after strict canonical validation."""

        if not isinstance(request, ApprovalRequest):
            raise ApprovalContractError("request must be an ApprovalRequest")
        destination = self.path(request.execution_id)
        if not destination.parent.is_dir():
            raise ApprovalPersistenceError("managed execution directory is missing")
        content = request.canonical_json().encode("utf-8")
        if destination.is_file():
            try:
                if destination.read_bytes() == content:
                    return destination
            except OSError as exc:
                raise ApprovalPersistenceError("approval projection could not be read") from exc
        temporary = destination.with_name(f".{self.filename}.{uuid4().hex}.tmp")
        try:
            with temporary.open("xb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, destination)
        except OSError as exc:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise ApprovalPersistenceError("approval projection could not be published") from exc
        return destination

    def load(self, execution_id: str) -> ApprovalRequest | None:
        """Load a canonical projection or fail closed on malformed/tampered bytes."""

        path = self.path(execution_id)
        if not path.exists():
            return None
        if not path.is_file():
            raise ApprovalPersistenceError("approval projection is not a regular file")
        try:
            raw = path.read_text(encoding="utf-8")
            document = json.loads(raw)
            if type(document) is not dict:
                raise ValueError("approval projection must be a JSON object")
            request = ApprovalRequest.model_validate_json(raw)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            raise ApprovalPersistenceError("approval projection is invalid") from exc
        if request.execution_id != execution_id or raw != request.canonical_json():
            raise ApprovalPersistenceError("approval projection is noncanonical or foreign")
        return request


__all__ = [
    "ApprovalContent",
    "ApprovalContractError",
    "ApprovalError",
    "ApprovalGateResult",
    "ApprovalManager",
    "ApprovalPersistenceError",
    "ApprovalRequest",
]
