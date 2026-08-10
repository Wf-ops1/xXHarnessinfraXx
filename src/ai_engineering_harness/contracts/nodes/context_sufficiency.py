"""Canonical contracts for evidence-based context sufficiency."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Final, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ContextGraphType = Literal["new_feature", "bug_fix", "refactoring", "migration"]
ContextDimensionId = Literal[
    "requirements",
    "acceptance_criteria",
    "structural_coverage",
    "symbol_relevance",
    "architecture_constraints",
    "conflicts_and_gaps",
]
ContextAction = Literal["proceed", "retrieve_more", "request_human", "abort"]
EvidenceKind = Literal["artifact", "query", "snapshot", "symbol"]

CONTEXT_DIMENSION_ORDER: Final[tuple[ContextDimensionId, ...]] = (
    "requirements",
    "acceptance_criteria",
    "structural_coverage",
    "symbol_relevance",
    "architecture_constraints",
    "conflicts_and_gaps",
)
_DIGEST_PATTERN = r"^sha256:[0-9a-f]{64}$"
_ARTIFACT_ID_PATTERN = r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$"


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")


def _freeze_sequence(value: object) -> object:
    return tuple(value) if isinstance(value, list) else value


def _validate_text(value: str) -> str:
    if not value.strip() or value != value.strip() or "\x00" in value:
        raise ValueError("text must be nonblank, trimmed, and NUL-free")
    return value


def _validate_score(value: Decimal) -> Decimal:
    if not value.is_finite() or value < Decimal(0) or value > Decimal(1):
        raise ValueError("score must be a finite Decimal between zero and one")
    if value != value.quantize(Decimal("0.000001")):
        raise ValueError("score must contain at most six decimal places")
    return value


def _parse_score(value: object) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, str) and value == value.strip():
        try:
            return Decimal(value)
        except InvalidOperation as exc:
            raise ValueError("score must use canonical decimal text") from exc
    raise TypeError("score must be a Decimal or canonical decimal text")


class RetrievalRequest(_StrictFrozenModel):
    """Immutable request used to select evidence for one supported workflow."""

    requirement_id: str = Field(min_length=1, max_length=512)
    graph_type: ContextGraphType
    query: str = Field(min_length=1, max_length=8192)

    @field_validator("requirement_id", "query")
    @classmethod
    def validate_text(cls, value: str) -> str:
        return _validate_text(value)


class ContextRequestIdentity(_StrictFrozenModel):
    """Persistable request identity that never includes the raw natural-language query."""

    requirement_id: str = Field(min_length=1, max_length=512)
    graph_type: ContextGraphType
    query_digest: str = Field(pattern=_DIGEST_PATTERN)

    @field_validator("requirement_id")
    @classmethod
    def validate_requirement_id(cls, value: str) -> str:
        return _validate_text(value)


class ArtifactEvidence(_StrictFrozenModel):
    """Content-free proof for one validated knowledge artifact."""

    artifact_id: str = Field(pattern=_ARTIFACT_ID_PATTERN)
    relative_path: str = Field(pattern=r"^\.harness/knowledge/artifacts/[a-z][a-z0-9_]*\.md$")
    digest: str = Field(pattern=_DIGEST_PATTERN)
    size_bytes: int = Field(gt=0)
    has_markdown_heading: bool

    @model_validator(mode="after")
    def validate_artifact_path(self) -> Self:
        expected_path = f".harness/knowledge/artifacts/{self.artifact_id}.md"
        if self.relative_path != expected_path:
            raise ValueError("artifact evidence path must match artifact_id")
        return self


class EvidenceReference(_StrictFrozenModel):
    """Typed, content-free evidence used by a scored dimension."""

    kind: EvidenceKind
    identifier: str = Field(min_length=1, max_length=4096)
    digest: str | None = Field(default=None, pattern=_DIGEST_PATTERN)

    @field_validator("identifier")
    @classmethod
    def validate_identifier(cls, value: str) -> str:
        return _validate_text(value)


class ManifestResult(_StrictFrozenModel):
    """Deterministic result of matching one graph manifest against stored artifacts."""

    graph_type: ContextGraphType
    requirements_expected: tuple[str, ...]
    acceptance_criteria_expected: tuple[str, ...]
    architecture_constraints_expected: tuple[str, ...]
    present_artifacts: tuple[str, ...]
    missing_artifacts: tuple[str, ...]
    invalid_artifacts: tuple[str, ...]
    all_required_present: bool

    @field_validator(
        "requirements_expected",
        "acceptance_criteria_expected",
        "architecture_constraints_expected",
        "present_artifacts",
        "missing_artifacts",
        "invalid_artifacts",
        mode="before",
    )
    @classmethod
    def freeze_sequences(cls, value: object) -> object:
        return _freeze_sequence(value)

    @model_validator(mode="after")
    def validate_partition(self) -> Self:
        expected = (
            self.requirements_expected
            + self.acceptance_criteria_expected
            + self.architecture_constraints_expected
        )
        if not all(expected) or len(set(expected)) != len(expected):
            raise ValueError("manifest artifact IDs must be non-empty and unique")
        observed = self.present_artifacts + self.missing_artifacts + self.invalid_artifacts
        if len(set(observed)) != len(observed) or set(observed) != set(expected):
            raise ValueError("manifest result must partition every expected artifact exactly once")
        if self.all_required_present != (set(self.present_artifacts) == set(expected)):
            raise ValueError("all_required_present does not match the manifest result")
        return self


class ContextDimension(_StrictFrozenModel):
    """One explainable sufficiency dimension with typed evidence and remediation."""

    dimension_id: ContextDimensionId
    score: Decimal
    evidence: tuple[EvidenceReference, ...]
    reason: str = Field(min_length=1, max_length=4096)
    gaps: tuple[str, ...] = ()
    recommended_action: ContextAction

    @field_validator("score", mode="before")
    @classmethod
    def parse_score(cls, value: object) -> Decimal:
        return _parse_score(value)

    @field_validator("score")
    @classmethod
    def validate_score(cls, value: Decimal) -> Decimal:
        return _validate_score(value)

    @field_validator("evidence", "gaps", mode="before")
    @classmethod
    def freeze_sequences(cls, value: object) -> object:
        return _freeze_sequence(value)

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        return _validate_text(value)

    @field_validator("gaps")
    @classmethod
    def validate_gaps(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(_validate_text(gap) for gap in value)


class ContextSufficiencyReport(_StrictFrozenModel):
    """The single canonical decision contract shared by evaluator, runtime, and graph catalog."""

    schema_version: Literal["1.0"] = "1.0"
    request: ContextRequestIdentity
    workflow_name: str = Field(min_length=1, max_length=512)
    commit_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    policy_id: str = Field(min_length=1, max_length=512)
    policy_schema_version: str = Field(min_length=1, max_length=64)
    policy_definition_version: str = Field(min_length=1, max_length=64)
    policy_digest: str = Field(pattern=_DIGEST_PATTERN)
    attempt: int = Field(ge=1)
    manifest: ManifestResult
    artifact_evidence: tuple[ArtifactEvidence, ...]
    dimensions: tuple[ContextDimension, ...]
    confidence: Decimal
    threshold: Decimal
    is_sufficient: bool
    gaps: tuple[str, ...]
    recommended_action: ContextAction

    @field_validator("artifact_evidence", "dimensions", "gaps", mode="before")
    @classmethod
    def freeze_sequences(cls, value: object) -> object:
        return _freeze_sequence(value)

    @field_validator("workflow_name", "policy_id", "policy_schema_version", "policy_definition_version")
    @classmethod
    def validate_text(cls, value: str) -> str:
        return _validate_text(value)

    @field_validator("confidence", "threshold", mode="before")
    @classmethod
    def parse_score(cls, value: object) -> Decimal:
        return _parse_score(value)

    @field_validator("confidence", "threshold")
    @classmethod
    def validate_score(cls, value: Decimal) -> Decimal:
        return _validate_score(value)

    @field_validator("gaps")
    @classmethod
    def validate_gaps(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(_validate_text(gap) for gap in value)

    @model_validator(mode="after")
    def validate_decision(self) -> Self:
        dimension_ids = tuple(dimension.dimension_id for dimension in self.dimensions)
        if dimension_ids != CONTEXT_DIMENSION_ORDER:
            raise ValueError("dimensions must contain the six canonical IDs in canonical order")
        evidence_ids = tuple(evidence.artifact_id for evidence in self.artifact_evidence)
        if evidence_ids != tuple(sorted(evidence_ids)) or len(set(evidence_ids)) != len(evidence_ids):
            raise ValueError("artifact evidence must be unique and sorted by artifact_id")
        if set(evidence_ids) != set(self.manifest.present_artifacts):
            raise ValueError("artifact evidence must exactly match present manifest artifacts")
        if self.manifest.graph_type != self.request.graph_type:
            raise ValueError("manifest graph_type must match the request")
        if self.is_sufficient:
            if self.gaps or self.recommended_action != "proceed":
                raise ValueError("a sufficient decision must have no gaps and recommend proceed")
        elif not self.gaps or self.recommended_action == "proceed":
            raise ValueError("an insufficient decision must include gaps and a blocking action")
        return self


__all__ = [
    "CONTEXT_DIMENSION_ORDER",
    "ArtifactEvidence",
    "ContextAction",
    "ContextDimension",
    "ContextDimensionId",
    "ContextGraphType",
    "ContextRequestIdentity",
    "ContextSufficiencyReport",
    "EvidenceReference",
    "ManifestResult",
    "RetrievalRequest",
]
