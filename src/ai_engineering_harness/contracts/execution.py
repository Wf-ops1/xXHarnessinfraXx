"""Strict contracts for durable, resumable execution identity."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Annotated, Self, TypeAlias

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    TypeAdapter,
    field_validator,
    model_validator,
)

EXECUTION_RECORD_SCHEMA_VERSION = "1.0"

_DIGEST_PATTERN = r"^sha256:[0-9a-f]{64}$"
_GIT_SHA_PATTERN = r"^[0-9a-f]{40}$"
_EXECUTION_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"
_WINDOWS_RESERVED_EXECUTION_IDS = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{index}" for index in range(1, 10)}
    | {f"LPT{index}" for index in range(1, 10)}
)


def _require_path_safe_execution_id(value: str) -> str:
    if value.endswith("."):
        raise ValueError("execution_id cannot end with a dot")
    if value.split(".", maxsplit=1)[0].upper() in _WINDOWS_RESERVED_EXECUTION_IDS:
        raise ValueError("execution_id cannot use a reserved Windows path component")
    return value

_NonEmptyStr: TypeAlias = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
ExecutionId: TypeAlias = Annotated[
    str,
    StringConstraints(min_length=1, pattern=_EXECUTION_ID_PATTERN),
    AfterValidator(_require_path_safe_execution_id),
]
_AttemptCount: TypeAlias = Annotated[int, Field(ge=0)]
_EXECUTION_ID_ADAPTER = TypeAdapter(ExecutionId, config=ConfigDict(strict=True))


class _StrictFrozenModel(BaseModel):
    """Shared fail-closed configuration for persisted execution contracts."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")


class ExecutionState(str, Enum):
    """Closed state vocabulary; transition enforcement belongs to F2.4."""

    INITIATED = "INITIATED"
    PREPARING_WORKSPACE = "PREPARING_WORKSPACE"
    CONTEXT_ASSEMBLING = "CONTEXT_ASSEMBLING"
    BLOCKED_INSUFFICIENT_CONTEXT = "BLOCKED_INSUFFICIENT_CONTEXT"
    BLOCKED_PREREQUISITE = "BLOCKED_PREREQUISITE"
    BLOCKED_BASE_CHANGED = "BLOCKED_BASE_CHANGED"
    PLANNING = "PLANNING"
    GENERATING_PLAN = "GENERATING_PLAN"
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    PAUSED_AWAITING_APPROVAL = "PAUSED_AWAITING_APPROVAL"
    PROMOTING = "PROMOTING"
    REINDEXING = "REINDEXING"
    KNOWLEDGE_SYNC = "KNOWLEDGE_SYNC"
    GENERATING_EVIDENCE = "GENERATING_EVIDENCE"
    ROLLBACK_IN_PROGRESS = "ROLLBACK_IN_PROGRESS"
    COMPENSATED = "COMPENSATED"
    DRY_RUN_COMPLETED = "DRY_RUN_COMPLETED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"
    FAILED_BUDGET_EXCEEDED = "FAILED_BUDGET_EXCEEDED"
    FAILED_RETRY_EXHAUSTED = "FAILED_RETRY_EXHAUSTED"


class ApprovalStatus(str, Enum):
    """Approval lifecycle identity without implementing approval behavior."""

    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    INVALIDATED = "INVALIDATED"


class ExecutionFailure(_StrictFrozenModel):
    """Redaction-safe failure identity stored on an execution record."""

    code: _NonEmptyStr
    message: _NonEmptyStr
    retryable: bool
    node_id: _NonEmptyStr | None


class ExecutionRecord(_StrictFrozenModel):
    """Versioned snapshot that identifies one resumable workflow execution."""

    record_schema_version: Annotated[
        str,
        StringConstraints(pattern=r"^1\.0$"),
    ]
    revision: int = Field(ge=0)
    execution_id: ExecutionId
    workflow_name: _NonEmptyStr
    artifact_digest: str = Field(pattern=_DIGEST_PATTERN)
    base_commit_sha: str = Field(pattern=_GIT_SHA_PATTERN)
    original_branch: _NonEmptyStr
    worktree_path: _NonEmptyStr | None
    current_node_id: _NonEmptyStr
    current_state: ExecutionState
    attempt_by_node: dict[_NonEmptyStr, _AttemptCount]
    created_at: datetime
    updated_at: datetime
    configuration_digest: str = Field(pattern=_DIGEST_PATTERN)
    approval_status: ApprovalStatus
    candidate_commit_sha: str | None = Field(pattern=_GIT_SHA_PATTERN)
    promotion_commit_sha: str | None = Field(pattern=_GIT_SHA_PATTERN)
    failure: ExecutionFailure | None

    @field_validator("attempt_by_node", mode="before")
    @classmethod
    def copy_attempt_mapping(cls, value: object) -> object:
        """Detach mutable caller mappings before the frozen model retains them."""
        return dict(value) if isinstance(value, dict) else value

    @field_validator("attempt_by_node")
    @classmethod
    def sort_attempt_mapping(cls, value: dict[str, int]) -> dict[str, int]:
        return dict(sorted(value.items()))

    @field_validator("created_at", "updated_at")
    @classmethod
    def require_utc_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("execution timestamps must be timezone-aware UTC values")
        if value.utcoffset() != timedelta(0):
            raise ValueError("execution timestamps must use UTC")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_temporal_order(self) -> Self:
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot precede created_at")
        return self

    def canonical_json(self) -> str:
        """Serialize the complete record deterministically with one final newline."""
        try:
            serialized = json.dumps(
                self.model_dump(mode="json"),
                ensure_ascii=False,
                allow_nan=False,
                indent=2,
                sort_keys=True,
            )
        except (TypeError, ValueError) as exc:
            raise ValueError(f"execution record cannot be serialized as canonical JSON: {exc}") from exc
        return serialized + "\n"


def validate_execution_id(value: object) -> str:
    """Validate a path component using the same contract as ``ExecutionRecord``."""
    return _EXECUTION_ID_ADAPTER.validate_python(value)


__all__ = [
    "EXECUTION_RECORD_SCHEMA_VERSION",
    "ApprovalStatus",
    "ExecutionFailure",
    "ExecutionId",
    "ExecutionRecord",
    "ExecutionState",
]
