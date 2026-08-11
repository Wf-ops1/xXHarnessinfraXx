"""Strict, immutable contracts for evidence-bound execution plans."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PLAN_SCHEMA_VERSION: Literal["1.0"] = "1.0"

_DIGEST_PATTERN = r"^sha256:[0-9a-f]{64}$"
_GIT_SHA_PATTERN = r"^[0-9a-f]{40}$"
_ID_PATTERN = r"^[a-z][a-z0-9]*(?:[-_][a-z0-9]+)*$"


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")


def _freeze(value: object) -> object:
    return tuple(value) if isinstance(value, list) else value


def _validate_text(value: str) -> str:
    if not value.strip() or value != value.strip() or "\x00" in value:
        raise ValueError("text must be nonblank, trimmed, and NUL-free")
    return value


def _validate_unique(values: tuple[str, ...], label: str) -> tuple[str, ...]:
    if len(set(values)) != len(values):
        raise ValueError(f"{label} must be unique")
    return values


class PlanAcceptanceCriterion(_StrictFrozenModel):
    order: int = Field(ge=1)
    criterion_id: str = Field(pattern=_ID_PATTERN)
    description: str = Field(min_length=1, max_length=4096)
    evidence_refs: tuple[str, ...] = Field(min_length=1)

    @field_validator("evidence_refs", mode="before")
    @classmethod
    def freeze_sequences(cls, value: object) -> object:
        return _freeze(value)

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str) -> str:
        return _validate_text(value)

    @field_validator("evidence_refs")
    @classmethod
    def validate_evidence(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _validate_unique(tuple(_validate_text(item) for item in value), "evidence_refs")


class PlanTarget(_StrictFrozenModel):
    target_id: str = Field(pattern=_ID_PATTERN)
    path: str = Field(min_length=1, max_length=4096)
    symbol: str | None = Field(default=None, max_length=4096)
    change_kind: Literal["create", "modify", "delete"]
    evidence_refs: tuple[str, ...] = Field(min_length=1)

    @field_validator("evidence_refs", mode="before")
    @classmethod
    def freeze_sequences(cls, value: object) -> object:
        return _freeze(value)

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        value = _validate_text(value)
        path = PurePosixPath(value)
        if (
            path.is_absolute()
            or "\\" in value
            or ":" in value
            or "://" in value
            or any(part in {"", ".", ".."} for part in value.split("/"))
            or path.as_posix() != value
        ):
            raise ValueError("target path must be a normalized POSIX relative path")
        return value

    @field_validator("symbol")
    @classmethod
    def validate_symbol(cls, value: str | None) -> str | None:
        return None if value is None else _validate_text(value)

    @field_validator("evidence_refs")
    @classmethod
    def validate_evidence(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _validate_unique(tuple(_validate_text(item) for item in value), "evidence_refs")


class PlanStep(_StrictFrozenModel):
    order: int = Field(ge=1)
    step_id: str = Field(pattern=_ID_PATTERN)
    description: str = Field(min_length=1, max_length=4096)
    target_ids: tuple[str, ...] = Field(min_length=1)
    tools: tuple[str, ...] = ()

    @field_validator("target_ids", "tools", mode="before")
    @classmethod
    def freeze_sequences(cls, value: object) -> object:
        return _freeze(value)

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str) -> str:
        return _validate_text(value)

    @field_validator("target_ids", "tools")
    @classmethod
    def validate_references(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _validate_unique(tuple(_validate_text(item) for item in value), "step references")


class PlanRisk(_StrictFrozenModel):
    risk_id: str = Field(pattern=_ID_PATTERN)
    description: str = Field(min_length=1, max_length=4096)
    mitigation: str = Field(min_length=1, max_length=4096)

    @field_validator("description", "mitigation")
    @classmethod
    def validate_text(cls, value: str) -> str:
        return _validate_text(value)


class PlanRollbackStrategy(_StrictFrozenModel):
    triggers: tuple[str, ...] = Field(min_length=1)
    actions: tuple[str, ...] = Field(min_length=1)
    verification: tuple[str, ...] = Field(min_length=1)

    @field_validator("triggers", "actions", "verification", mode="before")
    @classmethod
    def freeze_sequences(cls, value: object) -> object:
        return _freeze(value)

    @field_validator("triggers", "actions", "verification")
    @classmethod
    def validate_entries(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _validate_unique(tuple(_validate_text(item) for item in value), "rollback entries")


class PlanCompletionCondition(_StrictFrozenModel):
    condition_id: str = Field(pattern=_ID_PATTERN)
    criterion_id: str = Field(pattern=_ID_PATTERN)
    description: str = Field(min_length=1, max_length=4096)

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str) -> str:
        return _validate_text(value)


class PlanRemainingGap(_StrictFrozenModel):
    gap_id: str = Field(pattern=_ID_PATTERN)
    description: str = Field(min_length=1, max_length=4096)
    action: str = Field(min_length=1, max_length=4096)
    blocking: bool

    @field_validator("description", "action")
    @classmethod
    def validate_text(cls, value: str) -> str:
        return _validate_text(value)


class PlanContent(_StrictFrozenModel):
    """Provider-owned plan content, excluding trusted execution identity."""

    objective: str = Field(min_length=1, max_length=8192)
    acceptance_criteria: tuple[PlanAcceptanceCriterion, ...] = Field(min_length=1)
    targets: tuple[PlanTarget, ...] = Field(min_length=1)
    steps: tuple[PlanStep, ...] = Field(min_length=1)
    planned_tools: tuple[str, ...] = ()
    risks: tuple[PlanRisk, ...] = Field(min_length=1)
    applicable_gates: tuple[str, ...] = Field(min_length=1)
    rollback_strategy: PlanRollbackStrategy
    completion_conditions: tuple[PlanCompletionCondition, ...] = Field(min_length=1)
    remaining_gaps: tuple[PlanRemainingGap, ...]

    @field_validator(
        "acceptance_criteria",
        "targets",
        "steps",
        "planned_tools",
        "risks",
        "applicable_gates",
        "completion_conditions",
        "remaining_gaps",
        mode="before",
    )
    @classmethod
    def freeze_sequences(cls, value: object) -> object:
        return _freeze(value)

    @field_validator("objective")
    @classmethod
    def validate_objective(cls, value: str) -> str:
        return _validate_text(value)

    @field_validator("planned_tools", "applicable_gates")
    @classmethod
    def validate_named_sequences(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _validate_unique(tuple(_validate_text(item) for item in value), "plan declarations")

    @model_validator(mode="after")
    def validate_internal_references(self) -> Self:
        criteria = tuple(item.criterion_id for item in self.acceptance_criteria)
        targets = tuple(item.target_id for item in self.targets)
        steps = tuple(item.step_id for item in self.steps)
        risks = tuple(item.risk_id for item in self.risks)
        conditions = tuple(item.condition_id for item in self.completion_conditions)
        gaps = tuple(item.gap_id for item in self.remaining_gaps)
        for values, label in (
            (criteria, "criterion IDs"),
            (targets, "target IDs"),
            (steps, "step IDs"),
            (risks, "risk IDs"),
            (conditions, "condition IDs"),
            (gaps, "gap IDs"),
        ):
            _validate_unique(values, label)
        if tuple(item.order for item in self.acceptance_criteria) != tuple(
            range(1, len(self.acceptance_criteria) + 1)
        ):
            raise ValueError("acceptance criterion order must be contiguous from 1")
        if tuple(item.order for item in self.steps) != tuple(range(1, len(self.steps) + 1)):
            raise ValueError("step order must be contiguous from 1")

        target_set = set(targets)
        referenced_targets = {target for step in self.steps for target in step.target_ids}
        if any(target not in target_set for target in referenced_targets):
            raise ValueError("steps reference an unknown target")
        if referenced_targets != target_set:
            raise ValueError("every target must be referenced by at least one step")

        step_tools = {tool for step in self.steps for tool in step.tools}
        if step_tools != set(self.planned_tools):
            raise ValueError("planned_tools must exactly match tools used by steps")

        condition_criteria = tuple(item.criterion_id for item in self.completion_conditions)
        if len(condition_criteria) != len(set(condition_criteria)) or set(condition_criteria) != set(
            criteria
        ):
            raise ValueError("completion conditions must cover every criterion exactly once")
        if any(item.blocking for item in self.remaining_gaps):
            raise ValueError("a plan cannot contain a blocking remaining gap")
        return self


class PlanDocument(PlanContent):
    """Canonical plan with identities supplied only by trusted runtime code."""

    schema_version: Literal["1.0"] = PLAN_SCHEMA_VERSION
    execution_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    workflow_name: str = Field(min_length=1, max_length=512)
    base_commit_sha: str = Field(pattern=_GIT_SHA_PATTERN)
    context_digest: str = Field(pattern=_DIGEST_PATTERN)
    graph_input_digest: str = Field(pattern=_DIGEST_PATTERN)

    @field_validator("workflow_name")
    @classmethod
    def validate_workflow(cls, value: str) -> str:
        return _validate_text(value)


__all__ = [
    "PLAN_SCHEMA_VERSION",
    "PlanAcceptanceCriterion",
    "PlanCompletionCondition",
    "PlanContent",
    "PlanDocument",
    "PlanRemainingGap",
    "PlanRisk",
    "PlanRollbackStrategy",
    "PlanStep",
    "PlanTarget",
]
