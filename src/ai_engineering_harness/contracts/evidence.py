"""Strict canonical contract for one completed execution evidence manifest."""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from .execution import ApprovalStatus, ExecutionId

EVIDENCE_MANIFEST_SCHEMA_VERSION: Literal["1.0"] = "1.0"

_NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
_Digest = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]
_GitSha = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]
_JournalHash = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
_RelativePath = Annotated[str, StringConstraints(min_length=1, max_length=1024)]
EvidenceNotApplicableReason = Literal[
    "approval_not_required",
    "budget_boundary_not_used",
    "context_policy_not_used",
    "knowledge_sync_not_run",
    "plan_not_generated",
    "promotion_manager_not_used",
    "promotion_not_performed",
]


class EvidenceApplicability(StrEnum):
    """Whether an optional evidence capability actually ran."""

    RECORDED = "RECORDED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")


class EvidenceDigest(_StrictFrozenModel):
    """A real digest or an explicit reason why the capability did not run."""

    status: EvidenceApplicability
    digest: _Digest | None = None
    reason: EvidenceNotApplicableReason | None = None

    @model_validator(mode="after")
    def require_discriminated_value(self) -> Self:
        if self.status is EvidenceApplicability.RECORDED:
            if self.digest is None or self.reason is not None:
                raise ValueError("recorded digest evidence requires only digest")
        elif self.digest is not None or self.reason is None:
            raise ValueError("not-applicable digest evidence requires only reason")
        return self


class PromotionEvidence(_StrictFrozenModel):
    status: EvidenceApplicability
    commit_sha: _GitSha | None = None
    reason: EvidenceNotApplicableReason | None = None

    @model_validator(mode="after")
    def require_discriminated_value(self) -> Self:
        if self.status is EvidenceApplicability.RECORDED:
            if self.commit_sha is None or self.reason is not None:
                raise ValueError("recorded promotion evidence requires only commit_sha")
        elif self.commit_sha is not None or self.reason is None:
            raise ValueError("not-applicable promotion evidence requires only reason")
        return self


class ApprovalEvidence(_StrictFrozenModel):
    status: ApprovalStatus
    subject_digest: _Digest | None = None
    reason: EvidenceNotApplicableReason | None = None

    @model_validator(mode="after")
    def require_consistent_status(self) -> Self:
        if self.status is ApprovalStatus.NOT_REQUIRED:
            if self.subject_digest is not None or self.reason is None:
                raise ValueError("not-required approval requires only reason")
        elif self.subject_digest is None or self.reason is not None:
            raise ValueError("recorded approval requires only subject_digest")
        return self


class GateEvidence(_StrictFrozenModel):
    gate_id: _NonEmptyStr
    required: bool
    status: Literal["PASSED", "FAILED", "ERROR", "SKIPPED_NOT_APPLICABLE"]
    result_digest: _Digest


class ModelEvidence(_StrictFrozenModel):
    provider: _NonEmptyStr
    model: _NonEmptyStr


class BudgetEvidence(_StrictFrozenModel):
    status: EvidenceApplicability
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    tool_calls: int = Field(default=0, ge=0)
    duration_ms: int = Field(default=0, ge=0)
    attempts: int = Field(default=0, ge=0)
    estimated_cost_usd: _NonEmptyStr | None = None
    unpriced_operations: int = Field(default=0, ge=0)
    reason: EvidenceNotApplicableReason | None = None

    @model_validator(mode="after")
    def require_consistent_usage(self) -> Self:
        if self.total_tokens != self.prompt_tokens + self.completion_tokens:
            raise ValueError("budget total_tokens must equal prompt + completion")
        counters = (
            self.prompt_tokens,
            self.completion_tokens,
            self.total_tokens,
            self.tool_calls,
            self.duration_ms,
            self.attempts,
            self.unpriced_operations,
        )
        if self.status is EvidenceApplicability.NOT_APPLICABLE:
            if any(counters) or self.estimated_cost_usd is not None or self.reason is None:
                raise ValueError("not-applicable budget cannot contain synthetic usage")
        elif self.reason is not None:
            raise ValueError("recorded budget cannot contain a not-applicable reason")
        return self


class KnowledgeEvidence(_StrictFrozenModel):
    status: EvidenceApplicability
    transaction_id: _NonEmptyStr | None = None
    transaction_status: _NonEmptyStr | None = None
    reason: EvidenceNotApplicableReason | None = None

    @model_validator(mode="after")
    def require_discriminated_value(self) -> Self:
        if self.status is EvidenceApplicability.RECORDED:
            if (
                self.transaction_id is None
                or self.transaction_status is None
                or self.reason is not None
            ):
                raise ValueError("recorded knowledge evidence requires transaction identity and status")
        elif (
            self.transaction_id is not None
            or self.transaction_status is not None
            or self.reason is None
        ):
            raise ValueError("not-applicable knowledge evidence requires only reason")
        return self


class EvidenceFile(_StrictFrozenModel):
    path: _RelativePath
    digest: _Digest
    size_bytes: int = Field(ge=0)

    @field_validator("path")
    @classmethod
    def require_canonical_path(cls, value: str) -> str:
        parts = value.split("/")
        if (
            "\\" in value
            or "//" in value
            or value.startswith(("/", "./"))
            or (len(value) >= 2 and value[1] == ":")
            or any(part in {"", ".", ".."} for part in parts)
        ):
            raise ValueError("evidence file path must be canonical POSIX-relative")
        return value


class EvidenceManifest(_StrictFrozenModel):
    """Canonical, redaction-safe terminal evidence for one exact execution."""

    evidence_schema_version: Literal["1.0"] = EVIDENCE_MANIFEST_SCHEMA_VERSION
    execution_id: ExecutionId
    final_result: Literal["VERIFIED", "PROMOTED"]
    base_commit_sha: _GitSha
    promotion: PromotionEvidence
    artifact_digest: _Digest
    configuration_digest: _Digest
    plan: EvidenceDigest
    context: EvidenceDigest
    diff: EvidenceDigest
    gates: Annotated[tuple[GateEvidence, ...], Field(min_length=1)]
    approval: ApprovalEvidence
    models: tuple[ModelEvidence, ...]
    budget: BudgetEvidence
    knowledge: KnowledgeEvidence
    journal_final_hash: _JournalHash
    journal_final_sequence: int = Field(gt=0)
    files: Annotated[tuple[EvidenceFile, ...], Field(min_length=1)]

    @field_validator("gates", "models", "files", mode="before")
    @classmethod
    def freeze_sequences(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def require_canonical_collections_and_result(self) -> Self:
        if self.final_result == "PROMOTED":
            if self.promotion.status is not EvidenceApplicability.RECORDED:
                raise ValueError("promoted result requires recorded promotion evidence")
            if self.approval.status is not ApprovalStatus.APPROVED:
                raise ValueError("promoted result requires approved content evidence")
        elif self.promotion.status is not EvidenceApplicability.NOT_APPLICABLE:
            raise ValueError("verified result cannot claim a promotion")
        elif self.approval.status is not ApprovalStatus.NOT_REQUIRED:
            raise ValueError("verified result cannot claim promotion approval")
        expected_reasons = (
            (self.promotion, "promotion_manager_not_used"),
            (self.plan, "plan_not_generated"),
            (self.context, "context_policy_not_used"),
            (self.diff, "promotion_not_performed"),
            (self.approval, "approval_not_required"),
            (self.budget, "budget_boundary_not_used"),
            (self.knowledge, "knowledge_sync_not_run"),
        )
        for evidence, expected_reason in expected_reasons:
            if (
                evidence.status is EvidenceApplicability.NOT_APPLICABLE
                or evidence.status is ApprovalStatus.NOT_REQUIRED
            ) and evidence.reason != expected_reason:
                raise ValueError("not-applicable evidence reason does not match its section")
        if len({item.gate_id for item in self.gates}) != len(self.gates):
            raise ValueError("gate evidence identities must be unique")
        if len({item.result_digest for item in self.gates}) != len(self.gates):
            raise ValueError("gate evidence result digests must be unique")
        if tuple(sorted(self.models, key=lambda item: (item.provider, item.model))) != self.models:
            raise ValueError("model evidence must be sorted")
        if len({(item.provider, item.model) for item in self.models}) != len(self.models):
            raise ValueError("model evidence must be unique")
        if tuple(sorted(self.files, key=lambda item: item.path)) != self.files:
            raise ValueError("evidence files must be sorted")
        if len({item.path for item in self.files}) != len(self.files):
            raise ValueError("evidence file paths must be unique")
        return self

    def canonical_json(self) -> str:
        """Serialize deterministically without ambiguous JSON null fields."""

        try:
            serialized = json.dumps(
                self.model_dump(mode="json", exclude_none=True),
                ensure_ascii=False,
                allow_nan=False,
                indent=2,
                sort_keys=True,
            )
        except (TypeError, ValueError) as exc:
            raise ValueError(f"evidence manifest cannot be serialized: {exc}") from exc
        return serialized + "\n"


__all__ = [
    "EVIDENCE_MANIFEST_SCHEMA_VERSION",
    "ApprovalEvidence",
    "BudgetEvidence",
    "EvidenceApplicability",
    "EvidenceDigest",
    "EvidenceFile",
    "EvidenceManifest",
    "EvidenceNotApplicableReason",
    "GateEvidence",
    "KnowledgeEvidence",
    "ModelEvidence",
    "PromotionEvidence",
]
