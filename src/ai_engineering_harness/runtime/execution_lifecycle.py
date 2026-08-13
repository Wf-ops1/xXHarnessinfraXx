"""Canonical F2.5 lifecycle for start, resume, approval, cancellation, and views."""

from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from ai_engineering_harness.contracts import (
    CompiledGraphArtifact,
    DeterministicNodeSpec,
    HumanApprovalNodeSpec,
    NodeSpec,
    ResolvedPolicySpec,
)
from ai_engineering_harness.contracts.events import ExecutionEvent
from ai_engineering_harness.contracts.execution import (
    EXECUTION_RECORD_SCHEMA_VERSION,
    ApprovalStatus,
    ExecutionId,
    ExecutionRecord,
    ExecutionState,
)
from ai_engineering_harness.contracts.nodes import (
    ContextSufficiencyReport,
    RetrievalRequest,
)
from ai_engineering_harness.contracts.policies import (
    ContextSufficiencyPolicySpec,
    RetryCostPolicySpec,
    VerificationPolicySpec,
)
from ai_engineering_harness.core.config import ConfigResolutionError, ConfigResolver
from ai_engineering_harness.models.router import (
    ModelEgressDeniedError,
    ModelRouter,
    ModelRoutingConfigurationError,
)
from ai_engineering_harness.persistence import (
    ExecutionBundle,
    ExecutionLock,
    ResumeStateStorageProvider,
    StateStorageError,
    canonical_json_digest,
    canonical_json_object,
)
from ai_engineering_harness.security.redaction import Redactor
from ai_engineering_harness.security.trust import (
    TrustBoundaryConfigurationError,
    TrustBoundaryEvaluator,
    TrustCapabilityDeniedError,
    TrustEvaluationResult,
)
from ai_engineering_harness.verification import (
    GateRequirement,
    GateResult,
    GateStatus,
    ResolvedGateCommand,
    VerificationConfigurationError,
    VerificationEngine,
    VerificationPrerequisiteError,
    VerificationSuiteResult,
)
from ai_engineering_harness.workspace import (
    ProvisionedWorktree,
    WorktreeError,
)

from .context_assembler import (
    ContextAssembler,
    ContextPrerequisiteError,
    InsufficientContextError,
)
from .graph_executor import (
    VERIFICATION_REPAIR_SCHEDULED,
    GraphExecutionPausedResult,
    GraphExecutionResult,
    GraphExecutor,
    VerificationRepairRequest,
)
from .maf_adapter import MAFAdapter
from .node_executors import (
    ModelCallMetadata,
    NodeExecutorRegistry,
    RetryBudget,
    RetryContext,
)
from .planner import Planner, PlanPrerequisiteError
from .promotion_manager import (
    CandidateCommit,
    PromotionBaseChangedError,
    PromotionError,
    PromotionManager,
)
from .state_machine import VALID_STATE_TRANSITIONS, EventSourcedStateMachine

APPROVAL_REQUESTED: Literal["APPROVAL_REQUESTED"] = "APPROVAL_REQUESTED"
EXECUTION_APPROVED: Literal["EXECUTION_APPROVED"] = "EXECUTION_APPROVED"
APPROVAL_INVALIDATED: Literal["APPROVAL_INVALIDATED"] = "APPROVAL_INVALIDATED"
CONTEXT_EVALUATED: Literal["CONTEXT_EVALUATED"] = "CONTEXT_EVALUATED"
PLAN_GENERATION_STARTED: Literal["PLAN_GENERATION_STARTED"] = "PLAN_GENERATION_STARTED"
PLAN_GENERATED: Literal["PLAN_GENERATED"] = "PLAN_GENERATED"
VERIFICATION_GATE_STARTED: Literal["VERIFICATION_GATE_STARTED"] = "VERIFICATION_GATE_STARTED"
VERIFICATION_GATE_RECORDED: Literal["VERIFICATION_GATE_RECORDED"] = "VERIFICATION_GATE_RECORDED"
VERIFICATION_SUITE_RECORDED: Literal["VERIFICATION_SUITE_RECORDED"] = "VERIFICATION_SUITE_RECORDED"
CANDIDATE_COMMIT_STARTED: Literal["CANDIDATE_COMMIT_STARTED"] = "CANDIDATE_COMMIT_STARTED"
CANDIDATE_COMMIT_RECORDED: Literal["CANDIDATE_COMMIT_RECORDED"] = "CANDIDATE_COMMIT_RECORDED"
PROMOTION_STARTED: Literal["PROMOTION_STARTED"] = "PROMOTION_STARTED"
PROMOTION_COMPLETED: Literal["PROMOTION_COMPLETED"] = "PROMOTION_COMPLETED"
PROMOTION_DRY_RUN_RECORDED: Literal["PROMOTION_DRY_RUN_RECORDED"] = "PROMOTION_DRY_RUN_RECORDED"
_CONTEXT_POLICY_REFERENCE = "policies/context_sufficiency.yaml"
_TOOL_POLICY_REFERENCE = "policies/tool_policy.yaml"
_VERIFICATION_POLICY_REFERENCE = "policies/verification_policy.yaml"
_RETRY_COST_POLICY_REFERENCE = "policies/retry_cost_policy.yaml"

_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_GIT_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
_APPROVAL_EVENT_TYPES = frozenset({APPROVAL_REQUESTED, EXECUTION_APPROVED, APPROVAL_INVALIDATED})
_VERIFICATION_EVENT_TYPES = frozenset(
    {
        VERIFICATION_GATE_STARTED,
        VERIFICATION_GATE_RECORDED,
        VERIFICATION_SUITE_RECORDED,
    }
)
_VERIFICATION_GATE_STARTED_KEYS = frozenset(
    {
        "attempt",
        "gate_index",
        "gate_id",
        "required",
        "argv",
        "cwd",
        "policy_digest",
        "verified_commit_sha",
        "fencing_token",
    }
)
_VERIFICATION_GATE_RECORDED_KEYS = frozenset(
    {
        "attempt",
        "gate_index",
        "gate_id",
        "required",
        "status",
        "result_digest",
        "policy_digest",
        "verified_commit_sha",
        "fencing_token",
    }
)
_VERIFICATION_SUITE_RECORDED_KEYS = frozenset(
    {
        "attempt",
        "policy_digest",
        "verified_commit_sha",
        "result_digest",
        "gate_result_digests",
        "all_passed",
        "fencing_token",
    }
)
class ExecutionLifecycleError(Exception):
    """Base class for public F2.5 lifecycle failures."""

    def __init__(self, message: str, *, execution_id: str | None = None) -> None:
        super().__init__(message)
        self.execution_id = execution_id


class ExecutionConfigurationError(ExecutionLifecycleError):
    """Effective configuration is unsafe or cannot be snapshotted exactly."""


class ExecutionApprovalRequiredError(ExecutionLifecycleError):
    """A paused execution has no matching canonical approval."""


class ApprovalSubjectMismatchError(ExecutionLifecycleError):
    """An approval event does not bind to the current immutable subject."""


class ApprovalLifecycleIntegrityError(ExecutionLifecycleError):
    """Approval events and the execution snapshot cannot be reconciled."""


class ExecutionCancellationError(ExecutionLifecycleError):
    """The requested execution cannot be cancelled or resumed."""


class ExecutionGitIdentityError(ExecutionLifecycleError):
    """The immutable starting Git identity could not be established."""


class ContextLifecycleIntegrityError(ExecutionLifecycleError):
    """Persisted context attempts cannot be reconciled with the execution snapshot."""


class ContextRetryExhaustedError(ExecutionLifecycleError):
    """A new context retrieval was refused after the durable retry budget was consumed."""


class PlanningLifecycleIntegrityError(ExecutionLifecycleError):
    """Persisted planning events cannot be reconciled with the execution snapshot."""


class PlanningPrerequisiteError(ExecutionLifecycleError):
    """Typed fail-closed planning failure before the first graph node."""


class VerificationLifecycleIntegrityError(ExecutionLifecycleError):
    """Persisted verification evidence cannot be reconciled fail-closed."""


class VerificationLifecyclePrerequisiteError(ExecutionLifecycleError):
    """The canonical verification suite cannot run in the active worktree."""


class VerificationRequiredError(ExecutionLifecycleError):
    """Graph traversal ended and the execution awaits canonical verification."""


class VerificationRetryExhaustedError(ExecutionLifecycleError):
    """A durable verification repair limit refused the next correction attempt."""

    classification = "retry_exhausted"


class PromotionLifecycleError(ExecutionLifecycleError):
    """Base class for candidate and promotion lifecycle failures."""


class PromotionLifecyclePrerequisiteError(PromotionLifecycleError):
    """Promotion was refused because a durable prerequisite is absent."""


class PromotionLifecycleIntegrityError(PromotionLifecycleError):
    """Git effects and the execution journal cannot be reconciled exactly."""


class PromotionLifecycleBaseChangedError(PromotionLifecyclePrerequisiteError):
    """The immutable original branch or base changed before promotion."""


@dataclass(frozen=True, slots=True)
class _VerificationAttempt:
    attempt: int
    requirements: tuple[GateRequirement, ...]
    suite: VerificationSuiteResult
    suite_digest: str
    gate_result_digests: tuple[str, ...]
    policy_digest: str
    event_index: int
    full_suite: bool


@dataclass(frozen=True, slots=True)
class _RepairSchedule:
    repair_attempt: int
    source_verification_attempt: int
    source_result_digest: str
    source_verified_commit_sha: str
    origin_node_id: str
    target_node_id: str
    retry_policy_digest: str
    deadline_at: datetime
    event_index: int


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")


class ExecutionStatusView(_StrictFrozenModel):
    """Redaction-safe canonical status derived from durable state."""

    execution_id: ExecutionId
    workflow_name: str = Field(min_length=1)
    current_node_id: str = Field(min_length=1)
    current_state: ExecutionState
    approval_status: ApprovalStatus
    revision: int = Field(ge=0)
    updated_at: datetime


class ExecutionInspection(_StrictFrozenModel):
    """Redaction-safe execution identity and journal summary."""

    status: ExecutionStatusView
    artifact_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    configuration_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    initial_input_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    event_count: int = Field(ge=0)
    event_types: tuple[str, ...]

    @field_validator("event_types", mode="before")
    @classmethod
    def freeze_event_types(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value


class _ContextExecutionEnvelope(_StrictFrozenModel):
    context_request: RetrievalRequest
    graph_input: dict[str, object]

    @field_validator("graph_input", mode="before")
    @classmethod
    def detach_graph_input(cls, value: object) -> dict[str, object]:
        if type(value) is not dict:
            raise TypeError("graph_input must be an exact JSON object")
        return dict(value)


class ExecutionLifecycleService:
    """Coordinate resumable execution over the canonical provider and FSM."""

    def __init__(
        self,
        project_root: Path,
        storage: ResumeStateStorageProvider,
        executors: NodeExecutorRegistry,
        *,
        config_resolver: ConfigResolver | None = None,
        lock_timeout_seconds: float = 30.0,
        clock: Callable[[], datetime] | None = None,
        execution_id_factory: Callable[[], str] | None = None,
        event_id_factory: Callable[[], str] | None = None,
        owner_id_factory: Callable[[], str] | None = None,
        git_identity_provider: Callable[[], tuple[str, str]] | None = None,
        context_assembler: ContextAssembler | None = None,
        model_router_factory: Callable[[Mapping[str, object]], ModelRouter] | None = None,
        verification_worktree_provider: Callable[[str], ProvisionedWorktree] | None = None,
        promotion_manager: PromotionManager | None = None,
        trust_boundary: TrustEvaluationResult | None = None,
    ) -> None:
        if not isinstance(storage, ResumeStateStorageProvider):
            raise TypeError("storage must implement ResumeStateStorageProvider")
        if not isinstance(executors, NodeExecutorRegistry):
            raise TypeError("executors must be a NodeExecutorRegistry")
        if context_assembler is not None and not isinstance(context_assembler, ContextAssembler):
            raise TypeError("context_assembler must be a ContextAssembler")
        if verification_worktree_provider is not None and not callable(verification_worktree_provider):
            raise TypeError("verification_worktree_provider must be callable")
        resolved_project_root = Path(project_root).resolve()
        if promotion_manager is not None and not isinstance(promotion_manager, PromotionManager):
            raise TypeError("promotion_manager must be a PromotionManager")
        if promotion_manager is not None and promotion_manager.project_root != resolved_project_root:
            raise ValueError("promotion_manager project root must match project_root")
        boundary = trust_boundary
        if boundary is None and promotion_manager is not None:
            boundary = promotion_manager.trust_boundary
        if boundary is None:
            boundary = TrustBoundaryEvaluator(resolved_project_root).evaluate()
        if not isinstance(boundary, TrustEvaluationResult):
            raise TypeError("trust_boundary must be a TrustEvaluationResult")
        try:
            boundary.require_root(resolved_project_root)
        except (TrustBoundaryConfigurationError, TrustCapabilityDeniedError) as exc:
            raise ValueError(
                "trust_boundary must authorize the exact project_root"
            ) from exc
        if Path(boundary.repository_root) != resolved_project_root:
            raise ValueError("trust_boundary repository root must match project_root")
        if promotion_manager is not None and promotion_manager.trust_boundary != boundary:
            raise ValueError(
                "promotion_manager and execution lifecycle must share one trust boundary"
            )
        if (
            isinstance(lock_timeout_seconds, bool)
            or not isinstance(lock_timeout_seconds, (int, float))
            or not math.isfinite(lock_timeout_seconds)
            or lock_timeout_seconds < 0
        ):
            raise ValueError("lock_timeout_seconds must be non-negative")
        self.project_root = resolved_project_root
        self._storage = storage
        self._executors = executors
        self._config_resolver = config_resolver or ConfigResolver(self.project_root)
        self._lock_timeout_seconds = float(lock_timeout_seconds)
        self._clock = clock or (lambda: datetime.now(UTC))
        self._execution_id_factory = execution_id_factory or self._default_execution_id
        self._event_id_factory = event_id_factory or (lambda: f"lifecycle-event-{uuid.uuid4().hex}")
        self._owner_id_factory = owner_id_factory or (lambda: f"execution-lifecycle-{uuid.uuid4().hex}")
        self._git_identity_provider = git_identity_provider or self._read_git_identity
        self._context_assembler = context_assembler or ContextAssembler(self.project_root)
        self._trust_boundary = boundary
        self._model_router_factory = model_router_factory or (
            lambda config: ModelRouter.from_effective_config(
                config,
                trust_boundary=self._trust_boundary,
            )
        )
        self._verification_worktree_provider = verification_worktree_provider
        self._promotion_manager = promotion_manager
        self._graph_executor = GraphExecutor(
            storage,
            executors,
            resume_enabled=True,
            approval_handler=self,
            lock_timeout_seconds=self._lock_timeout_seconds,
            clock=self._clock,
            event_id_factory=self._event_id_factory,
            owner_id_factory=self._owner_id_factory,
        )

    def start(
        self,
        compiled_artifact_path: Path,
        *,
        initial_input: dict[str, object],
        execution_id: str | None = None,
        profile_name: str = "default",
        cli_overrides: dict[str, object] | None = None,
        configuration: dict[str, object] | None = None,
    ) -> GraphExecutionResult | GraphExecutionPausedResult:
        """Create one exact revision-zero execution and begin traversal."""
        artifact = MAFAdapter.load_and_validate(Path(compiled_artifact_path))
        context_policy = self._resolved_context_policy(artifact)
        self._resolved_verification_policy(artifact)
        envelope = self._context_envelope(initial_input, artifact) if context_policy is not None else None
        graph_input = envelope.graph_input if envelope is not None else initial_input
        if configuration is not None and cli_overrides is not None:
            raise ExecutionConfigurationError(
                "configuration and cli_overrides cannot be supplied together"
            )
        try:
            effective_configuration = self._config_resolver.resolve(
                profile_name=profile_name,
                cli_overrides=(
                    configuration
                    if configuration is not None
                    else cli_overrides
                ),
            )
            effective_configuration = self._configuration_with_trust_boundary(
                effective_configuration
            )
        except (
            ConfigResolutionError,
            ModelEgressDeniedError,
            ModelRoutingConfigurationError,
        ) as exc:
            raise ExecutionConfigurationError(
                f"effective configuration is invalid: {exc}"
            ) from exc
        try:
            configuration_json = canonical_json_object(effective_configuration)
            initial_input_json = canonical_json_object(initial_input)
        except ValueError as exc:
            raise ExecutionConfigurationError("configuration and initial input must be finite JSON objects") from exc
        selected_id = execution_id or self._execution_id_factory()
        self._graph_executor.preflight(
            artifact,
            graph_input,
            execution_id=selected_id,
        )
        base_commit_sha, original_branch = self._git_identity_provider()
        self._validate_git_identity(base_commit_sha, original_branch)
        timestamp = self._next_timestamp(datetime.min.replace(tzinfo=UTC))
        artifact_json = artifact.canonical_json()
        bundle = ExecutionBundle(
            bundle_schema_version="1.0",
            execution_id=selected_id,
            artifact_digest=canonical_json_digest(artifact_json),
            configuration_digest=canonical_json_digest(configuration_json),
            initial_input_digest=canonical_json_digest(initial_input_json),
            artifact_json=artifact_json,
            configuration_json=configuration_json,
        )
        record = ExecutionRecord(
            record_schema_version=EXECUTION_RECORD_SCHEMA_VERSION,
            revision=0,
            execution_id=selected_id,
            workflow_name=artifact.graph.graph.name,
            artifact_digest=bundle.artifact_digest,
            base_commit_sha=base_commit_sha,
            original_branch=original_branch,
            worktree_path=None,
            current_node_id=artifact.graph.graph.entrypoint,
            current_state=ExecutionState.INITIATED,
            attempt_by_node={},
            created_at=timestamp,
            updated_at=timestamp,
            configuration_digest=bundle.configuration_digest,
            approval_status=ApprovalStatus.NOT_REQUIRED,
            candidate_commit_sha=None,
            promotion_commit_sha=None,
            failure=None,
        )
        self._storage.create_execution_bundle(bundle, initial_input=initial_input)
        self._storage.create_execution(record)
        if context_policy is not None and envelope is not None:
            resolved_policy, policy = context_policy
            self._prepare_context_attempt(
                artifact=artifact,
                execution_id=selected_id,
                request=envelope.context_request,
                resolved_policy=resolved_policy,
                policy=policy,
            )
            self._prepare_plan(
                artifact=artifact,
                execution_id=selected_id,
                request=envelope.context_request,
                graph_input=envelope.graph_input,
                effective_configuration=effective_configuration,
            )
        return self._graph_executor.execute(
            artifact,
            selected_id,
            graph_input,
            defer_completion=True,
        )

    def resume(
        self,
        execution_id: str,
    ) -> GraphExecutionResult | GraphExecutionPausedResult:
        """Resume only from the immutable bundle and canonical journal."""
        record, bundle, artifact = self._prepare_resume(execution_id)
        if record.current_state == ExecutionState.CANCELLED:
            raise ExecutionCancellationError(
                "cancelled execution cannot be resumed",
                execution_id=execution_id,
            )
        context_policy = self._resolved_context_policy(artifact)
        verification_policy = self._resolved_verification_policy(artifact)
        if record.current_state == ExecutionState.VERIFYING:
            return self._resume_verification_repair(
                artifact=artifact,
                execution_id=execution_id,
                record=record,
                verification_policy=verification_policy,
            )
        if context_policy is not None and record.current_state in {
            ExecutionState.INITIATED,
            ExecutionState.CONTEXT_ASSEMBLING,
            ExecutionState.BLOCKED_INSUFFICIENT_CONTEXT,
            ExecutionState.PLANNING,
        }:
            initial_input = self._storage.load_payload(
                execution_id,
                bundle.initial_input_digest,
            )
            envelope = self._context_envelope(initial_input, artifact)
            if record.current_state != ExecutionState.PLANNING:
                resolved_policy, policy = context_policy
                self._prepare_context_attempt(
                    artifact=artifact,
                    execution_id=execution_id,
                    request=envelope.context_request,
                    resolved_policy=resolved_policy,
                    policy=policy,
                )
            effective_configuration = self._configuration_from_bundle(bundle, execution_id)
            self._prepare_plan(
                artifact=artifact,
                execution_id=execution_id,
                request=envelope.context_request,
                graph_input=envelope.graph_input,
                effective_configuration=effective_configuration,
            )
            return self._graph_executor.execute(
                artifact,
                execution_id,
                envelope.graph_input,
                defer_completion=True,
            )
        if record.current_state == ExecutionState.INITIATED:
            initial_input = self._storage.load_payload(
                execution_id,
                bundle.initial_input_digest,
            )
            return self._graph_executor.execute(
                artifact,
                execution_id,
                initial_input,
                defer_completion=True,
            )
        return self._graph_executor.resume(
            artifact,
            execution_id,
            defer_completion=True,
        )

    def verify(self, execution_id: str) -> VerificationSuiteResult:
        """Persist and guard the only policy-derived verification suite."""

        record, _, artifact = self._prepare_resume(execution_id)
        if record.current_state == ExecutionState.COMPLETED:
            raise VerificationLifecycleIntegrityError(
                "completed execution cannot run verification again",
                execution_id=execution_id,
            )
        if record.current_state != ExecutionState.VERIFYING:
            raise VerificationLifecycleIntegrityError(
                "canonical verification requires the VERIFYING state",
                execution_id=execution_id,
            )
        policy_context = self._resolved_verification_policy(artifact)
        if policy_context is None:
            self._block_verification_prerequisite(execution_id)
            raise VerificationLifecyclePrerequisiteError(
                "compiled artifact does not contain a verification policy",
                execution_id=execution_id,
            )
        worktree = self._verification_worktree(execution_id, record)
        if self._promotion_manager is not None:
            candidate_sha = record.candidate_commit_sha
            if (
                candidate_sha is None
                or worktree.reference.worktree_head_sha != candidate_sha
                or record.worktree_path != str(worktree.worktree_path)
            ):
                raise VerificationLifecyclePrerequisiteError(
                    "promotion-enabled verification requires the recorded candidate commit",
                    execution_id=execution_id,
                )
        engine = VerificationEngine(worktree, clock=self._clock)
        return self._verify_execution(
            artifact=artifact,
            execution_id=execution_id,
            engine=engine,
            policy_context=policy_context,
        )

    def prepare_candidate(
        self,
        execution_id: str,
        *,
        message: str | None = None,
    ) -> ExecutionRecord:
        """Create or recover the real candidate commit and bind it durably."""

        manager = self._required_promotion_manager(execution_id)
        lock = self._acquire(execution_id)
        try:
            record = self._recover_approval_locked(execution_id, lock)
            record = self._recover_promotion_fields_locked(execution_id, lock)
            record = self._state_machine(execution_id, lock).recover(lock=lock)
            if record.current_state != ExecutionState.VERIFYING:
                raise PromotionLifecycleIntegrityError(
                    "candidate creation requires the VERIFYING state",
                    execution_id=execution_id,
                )
            if record.candidate_commit_sha is not None:
                try:
                    existing = manager.load_candidate(execution_id)
                except PromotionError:
                    existing = None
                if existing is not None and self._candidate_matches_record(existing, record):
                    return record

            events = self._storage.load_events(execution_id, lock=lock)
            last_timestamp = max(
                record.updated_at,
                events[-1].timestamp if events else record.updated_at,
            )
            started_at = self._next_timestamp(last_timestamp)
            self._append_promotion_event(
                execution_id,
                CANDIDATE_COMMIT_STARTED,
                {
                    "base_commit_sha": record.base_commit_sha,
                    "original_branch": record.original_branch,
                    "fencing_token": lock.fencing_token,
                },
                timestamp=started_at,
                lock=lock,
            )
            try:
                candidate = manager.create_candidate(execution_id, message=message)
            except PromotionError as exc:
                raise PromotionLifecyclePrerequisiteError(
                    "candidate commit could not be created or recovered",
                    execution_id=execution_id,
                ) from exc
            self._validate_candidate_identity(
                candidate,
                record,
                execution_id,
                allow_replacement=True,
            )
            recorded_at = self._next_timestamp(started_at)
            self._append_promotion_event(
                execution_id,
                CANDIDATE_COMMIT_RECORDED,
                {
                    "base_commit_sha": candidate.base_commit_sha,
                    "candidate_commit_sha": candidate.candidate_commit_sha,
                    "original_branch": candidate.original_branch,
                    "worktree_path": str(candidate.worktree_path),
                    "record_revision": record.revision + 1,
                    "fencing_token": lock.fencing_token,
                },
                timestamp=recorded_at,
                lock=lock,
            )
            replacement = self._git_replacement(
                record,
                candidate_commit_sha=candidate.candidate_commit_sha,
                promotion_commit_sha=record.promotion_commit_sha,
                worktree_path=str(candidate.worktree_path),
                revision=record.revision + 1,
                updated_at=recorded_at,
            )
            return self._storage.compare_and_set_execution(
                execution_id,
                record.revision,
                replacement,
                lock=lock,
            )
        except StateStorageError as exc:
            raise PromotionLifecycleIntegrityError(
                "candidate evidence could not be persisted or recovered",
                execution_id=execution_id,
            ) from exc
        finally:
            self._storage.release_execution_lock(lock)

    def promote(self, execution_id: str, *, dry_run: bool = False) -> ExecutionRecord:
        """Promote only an approved, fully verified candidate or record a dry-run."""

        manager = self._required_promotion_manager(execution_id)
        _, _, artifact = self._prepare_resume(execution_id)
        lock = self._acquire(execution_id)
        try:
            record = self._recover_approval_locked(execution_id, lock)
            record = self._recover_promotion_fields_locked(execution_id, lock)
            machine = self._state_machine(execution_id, lock)
            record = machine.recover(lock=lock)
            allowed_states = (
                {ExecutionState.VERIFYING} if dry_run else {ExecutionState.VERIFYING, ExecutionState.PROMOTING}
            )
            if record.current_state not in allowed_states:
                raise PromotionLifecycleIntegrityError(
                    "promotion requires the VERIFYING or recoverable PROMOTING state",
                    execution_id=execution_id,
                )
            if record.approval_status is not ApprovalStatus.APPROVED:
                raise PromotionLifecyclePrerequisiteError(
                    "promotion requires canonical APPROVED status",
                    execution_id=execution_id,
                )
            try:
                candidate = manager.load_candidate(execution_id)
            except PromotionError as exc:
                raise PromotionLifecyclePrerequisiteError(
                    "recorded candidate commit could not be validated",
                    execution_id=execution_id,
                ) from exc
            self._validate_candidate_identity(candidate, record, execution_id)
            self._require_passing_candidate_suite(
                execution_id=execution_id,
                artifact=artifact,
                candidate=candidate,
                lock=lock,
            )

            events = self._storage.load_events(execution_id, lock=lock)
            last_timestamp = max(
                record.updated_at,
                events[-1].timestamp if events else record.updated_at,
            )
            if dry_run:
                already_recorded = any(
                    event.event_type == PROMOTION_DRY_RUN_RECORDED
                    and event.payload.get("candidate_commit_sha") == candidate.candidate_commit_sha
                    for event in events
                )
                if not already_recorded:
                    try:
                        result = manager.promote(candidate, dry_run=True)
                    except PromotionError as exc:
                        raise PromotionLifecyclePrerequisiteError(
                            "dry-run promotion prerequisites changed",
                            execution_id=execution_id,
                        ) from exc
                    if result.promotion_commit_sha is not None:
                        raise PromotionLifecycleIntegrityError(
                            "dry-run promotion unexpectedly reported a live commit",
                            execution_id=execution_id,
                        )
                    last_timestamp = self._next_timestamp(last_timestamp)
                    self._append_promotion_event(
                        execution_id,
                        PROMOTION_DRY_RUN_RECORDED,
                        {
                            "base_commit_sha": candidate.base_commit_sha,
                            "candidate_commit_sha": candidate.candidate_commit_sha,
                            "original_branch": candidate.original_branch,
                            "fencing_token": lock.fencing_token,
                        },
                        timestamp=last_timestamp,
                        lock=lock,
                    )
                return machine.transition_to(
                    ExecutionState.DRY_RUN_COMPLETED,
                    node_id=record.current_node_id,
                    attempt=0,
                    reason="promotion_dry_run_completed",
                    lock=lock,
                )

            if record.current_state == ExecutionState.VERIFYING:
                last_timestamp = self._next_timestamp(last_timestamp)
                self._append_promotion_event(
                    execution_id,
                    PROMOTION_STARTED,
                    {
                        "base_commit_sha": candidate.base_commit_sha,
                        "candidate_commit_sha": candidate.candidate_commit_sha,
                        "original_branch": candidate.original_branch,
                        "fencing_token": lock.fencing_token,
                    },
                    timestamp=last_timestamp,
                    lock=lock,
                )
                record = machine.transition_to(
                    ExecutionState.PROMOTING,
                    node_id=record.current_node_id,
                    attempt=0,
                    reason="promotion_started",
                    lock=lock,
                )

            try:
                result = manager.promote(
                    candidate,
                    dry_run=False,
                    approval_granted=True,
                )
            except PromotionBaseChangedError as exc:
                current = machine.recover(lock=lock)
                if current.current_state == ExecutionState.PROMOTING:
                    machine.transition_to(
                        ExecutionState.BLOCKED_BASE_CHANGED,
                        node_id=current.current_node_id,
                        attempt=0,
                        reason="promotion_base_changed",
                        lock=lock,
                    )
                raise PromotionLifecycleBaseChangedError(
                    "original base changed before exact candidate promotion",
                    execution_id=execution_id,
                ) from exc
            except PromotionError as exc:
                raise PromotionLifecycleIntegrityError(
                    "promotion effect could not be completed or reconciled",
                    execution_id=execution_id,
                ) from exc
            promotion_sha = result.promotion_commit_sha
            if promotion_sha is None:
                raise PromotionLifecycleIntegrityError(
                    "live promotion did not produce a provable commit",
                    execution_id=execution_id,
                )

            record = self._recover_promotion_fields_locked(execution_id, lock)
            record = machine.recover(lock=lock)
            if record.promotion_commit_sha is None:
                events = self._storage.load_events(execution_id, lock=lock)
                last_timestamp = max(
                    record.updated_at,
                    events[-1].timestamp if events else record.updated_at,
                )
                completed_at = self._next_timestamp(last_timestamp)
                self._append_promotion_event(
                    execution_id,
                    PROMOTION_COMPLETED,
                    {
                        "base_commit_sha": candidate.base_commit_sha,
                        "candidate_commit_sha": candidate.candidate_commit_sha,
                        "promotion_commit_sha": promotion_sha,
                        "original_branch": candidate.original_branch,
                        "record_revision": record.revision + 1,
                        "fencing_token": lock.fencing_token,
                    },
                    timestamp=completed_at,
                    lock=lock,
                )
                replacement = self._git_replacement(
                    record,
                    candidate_commit_sha=candidate.candidate_commit_sha,
                    promotion_commit_sha=promotion_sha,
                    worktree_path=record.worktree_path,
                    revision=record.revision + 1,
                    updated_at=completed_at,
                )
                record = self._storage.compare_and_set_execution(
                    execution_id,
                    record.revision,
                    replacement,
                    lock=lock,
                )
            elif record.promotion_commit_sha != promotion_sha:
                raise PromotionLifecycleIntegrityError(
                    "promotion snapshot diverges from the proven Git effect",
                    execution_id=execution_id,
                )
            return machine.transition_to(
                ExecutionState.COMPLETED,
                node_id=record.current_node_id,
                attempt=0,
                reason="promotion_completed",
                lock=lock,
            )
        except StateStorageError as exc:
            raise PromotionLifecycleIntegrityError(
                "promotion evidence could not be persisted or recovered",
                execution_id=execution_id,
            ) from exc
        finally:
            self._storage.release_execution_lock(lock)

    def _required_promotion_manager(self, execution_id: str) -> PromotionManager:
        manager = self._promotion_manager
        if manager is None:
            raise PromotionLifecyclePrerequisiteError(
                "promotion manager is not configured",
                execution_id=execution_id,
            )
        return manager

    @staticmethod
    def _candidate_matches_record(
        candidate: CandidateCommit,
        record: ExecutionRecord,
    ) -> bool:
        return bool(
            candidate.execution_id == record.execution_id
            and candidate.base_commit_sha == record.base_commit_sha
            and candidate.original_branch == record.original_branch
            and candidate.candidate_commit_sha == record.candidate_commit_sha
            and str(candidate.worktree_path) == record.worktree_path
        )

    def _validate_candidate_identity(
        self,
        candidate: CandidateCommit,
        record: ExecutionRecord,
        execution_id: str,
        *,
        allow_replacement: bool = False,
    ) -> None:
        if (
            candidate.execution_id != execution_id
            or candidate.base_commit_sha != record.base_commit_sha
            or candidate.original_branch != record.original_branch
        ):
            raise PromotionLifecycleIntegrityError(
                "candidate identity diverges from the immutable execution",
                execution_id=execution_id,
            )
        if (
            not allow_replacement
            and record.candidate_commit_sha is not None
            and not self._candidate_matches_record(candidate, record)
        ):
            raise PromotionLifecycleIntegrityError(
                "candidate Git state diverges from the durable snapshot",
                execution_id=execution_id,
            )

    def _require_passing_candidate_suite(
        self,
        *,
        execution_id: str,
        artifact: CompiledGraphArtifact,
        candidate: CandidateCommit,
        lock: ExecutionLock,
    ) -> None:
        policy_context = self._resolved_verification_policy(artifact)
        if policy_context is None:
            raise PromotionLifecyclePrerequisiteError(
                "promotion requires the compiled verification policy",
                execution_id=execution_id,
            )
        resolved_policy, policy = policy_context
        policy_digest = canonical_json_digest(canonical_json_object(resolved_policy.model_dump(mode="json")))
        requirements = tuple(GateRequirement(gate_id=gate.id, required=gate.blocking) for gate in policy.required_gates)
        attempts = self._recover_verification_attempts(
            execution_id=execution_id,
            events=self._storage.load_events(execution_id, lock=lock),
            requirements=requirements,
            policy_digest=policy_digest,
            lock=lock,
        )
        if not attempts:
            raise PromotionLifecyclePrerequisiteError(
                "promotion requires a durable verification suite",
                execution_id=execution_id,
            )
        latest = attempts[-1]
        if (
            not latest.full_suite
            or not latest.suite.all_passed
            or latest.suite.verified_commit_sha != candidate.candidate_commit_sha
        ):
            raise PromotionLifecyclePrerequisiteError(
                "promotion requires the latest full suite to pass on the candidate SHA",
                execution_id=execution_id,
            )

    def _recover_promotion_fields_locked(
        self,
        execution_id: str,
        lock: ExecutionLock,
    ) -> ExecutionRecord:
        record = self._storage.load_execution(execution_id, lock=lock)
        latest_candidate: tuple[str, str] | None = None
        latest_promotion: str | None = None
        pending: tuple[ExecutionEvent, str, str | None] | None = None
        last_record_revision = -1
        promotion_types = {
            CANDIDATE_COMMIT_STARTED,
            CANDIDATE_COMMIT_RECORDED,
            PROMOTION_STARTED,
            PROMOTION_COMPLETED,
            PROMOTION_DRY_RUN_RECORDED,
        }
        for event in self._storage.load_events(execution_id, lock=lock):
            if event.event_type not in promotion_types:
                continue
            payload = event.payload
            if event.event_type == CANDIDATE_COMMIT_STARTED:
                expected_keys = {
                    "base_commit_sha",
                    "original_branch",
                    "fencing_token",
                }
            elif event.event_type == CANDIDATE_COMMIT_RECORDED:
                expected_keys = {
                    "base_commit_sha",
                    "candidate_commit_sha",
                    "original_branch",
                    "worktree_path",
                    "record_revision",
                    "fencing_token",
                }
            elif event.event_type == PROMOTION_COMPLETED:
                expected_keys = {
                    "base_commit_sha",
                    "candidate_commit_sha",
                    "promotion_commit_sha",
                    "original_branch",
                    "record_revision",
                    "fencing_token",
                }
            else:
                expected_keys = {
                    "base_commit_sha",
                    "candidate_commit_sha",
                    "original_branch",
                    "fencing_token",
                }
            fencing_token = payload.get("fencing_token")
            if (
                set(payload) != expected_keys
                or payload.get("base_commit_sha") != record.base_commit_sha
                or payload.get("original_branch") != record.original_branch
                or type(fencing_token) is not int
                or fencing_token <= 0
            ):
                raise PromotionLifecycleIntegrityError(
                    "candidate or promotion event identity is invalid",
                    execution_id=execution_id,
                )
            if event.event_type == CANDIDATE_COMMIT_STARTED:
                continue
            candidate_sha = payload.get("candidate_commit_sha")
            if type(candidate_sha) is not str or _GIT_SHA_PATTERN.fullmatch(candidate_sha) is None:
                raise PromotionLifecycleIntegrityError(
                    "promotion event candidate SHA is invalid",
                    execution_id=execution_id,
                )
            if event.event_type in {PROMOTION_STARTED, PROMOTION_DRY_RUN_RECORDED}:
                if latest_candidate is None or candidate_sha != latest_candidate[0]:
                    raise PromotionLifecycleIntegrityError(
                        "promotion event is not bound to the latest candidate",
                        execution_id=execution_id,
                    )
                continue

            revision = payload.get("record_revision")
            if type(revision) is not int or revision < 1 or revision <= last_record_revision:
                raise PromotionLifecycleIntegrityError(
                    "candidate and promotion record revisions must increase",
                    execution_id=execution_id,
                )
            last_record_revision = revision
            worktree_path: str | None = None
            if event.event_type == CANDIDATE_COMMIT_RECORDED:
                observed_path = payload.get("worktree_path")
                if type(observed_path) is not str or not observed_path.strip():
                    raise PromotionLifecycleIntegrityError(
                        "candidate event worktree path is invalid",
                        execution_id=execution_id,
                    )
                worktree_path = observed_path
                outcome_value = candidate_sha
                outcome_kind = "candidate"
            else:
                promotion_sha = payload.get("promotion_commit_sha")
                if (
                    type(promotion_sha) is not str
                    or _GIT_SHA_PATTERN.fullmatch(promotion_sha) is None
                    or latest_candidate is None
                    or candidate_sha != latest_candidate[0]
                ):
                    raise PromotionLifecycleIntegrityError(
                        "promotion outcome identity is invalid",
                        execution_id=execution_id,
                    )
                outcome_value = promotion_sha
                outcome_kind = "promotion"

            if revision <= record.revision:
                if pending is not None:
                    raise PromotionLifecycleIntegrityError(
                        "committed promotion outcome follows a pending outcome",
                        execution_id=execution_id,
                    )
                if outcome_kind == "candidate":
                    latest_candidate = (outcome_value, worktree_path or "")
                else:
                    latest_promotion = outcome_value
            else:
                if pending is not None or revision != record.revision + 1:
                    raise PromotionLifecycleIntegrityError(
                        "promotion outcome is not the next recoverable revision",
                        execution_id=execution_id,
                    )
                pending = (event, outcome_kind, worktree_path)
                if outcome_kind == "candidate":
                    latest_candidate = (outcome_value, worktree_path or "")
                else:
                    latest_promotion = outcome_value

        if pending is not None:
            event, outcome_kind, worktree_path = pending
            payload = event.payload
            candidate_sha = str(payload["candidate_commit_sha"])
            promotion_sha = (
                str(payload["promotion_commit_sha"]) if outcome_kind == "promotion" else record.promotion_commit_sha
            )
            replacement = self._git_replacement(
                record,
                candidate_commit_sha=(candidate_sha if outcome_kind == "candidate" else record.candidate_commit_sha),
                promotion_commit_sha=promotion_sha,
                worktree_path=(worktree_path if outcome_kind == "candidate" else record.worktree_path),
                revision=record.revision + 1,
                updated_at=event.timestamp,
            )
            record = self._storage.compare_and_set_execution(
                execution_id,
                record.revision,
                replacement,
                lock=lock,
            )

        if latest_candidate is None:
            if record.candidate_commit_sha is not None or record.worktree_path is not None:
                raise PromotionLifecycleIntegrityError(
                    "candidate snapshot has no canonical event history",
                    execution_id=execution_id,
                )
        elif record.candidate_commit_sha != latest_candidate[0] or record.worktree_path != latest_candidate[1]:
            raise PromotionLifecycleIntegrityError(
                "candidate snapshot diverges from committed event history",
                execution_id=execution_id,
            )
        if latest_promotion is None:
            if record.promotion_commit_sha is not None:
                raise PromotionLifecycleIntegrityError(
                    "promotion snapshot has no canonical outcome event",
                    execution_id=execution_id,
                )
        elif record.promotion_commit_sha != latest_promotion:
            raise PromotionLifecycleIntegrityError(
                "promotion snapshot diverges from committed event history",
                execution_id=execution_id,
            )
        return record

    def _append_promotion_event(
        self,
        execution_id: str,
        event_type: Literal[
            "CANDIDATE_COMMIT_STARTED",
            "CANDIDATE_COMMIT_RECORDED",
            "PROMOTION_STARTED",
            "PROMOTION_COMPLETED",
            "PROMOTION_DRY_RUN_RECORDED",
        ],
        payload: dict[str, object],
        *,
        timestamp: datetime,
        lock: ExecutionLock,
    ) -> ExecutionEvent:
        try:
            event = ExecutionEvent(
                event_id=self._event_id_factory(),
                execution_id=execution_id,
                event_type=event_type,
                timestamp=timestamp,
                payload=payload,
            )
        except (TypeError, ValueError, ValidationError) as exc:
            raise PromotionLifecycleIntegrityError(
                "cannot construct a canonical promotion event",
                execution_id=execution_id,
            ) from exc
        return self._storage.append_event(execution_id, event, lock=lock)

    @staticmethod
    def _git_replacement(
        record: ExecutionRecord,
        *,
        candidate_commit_sha: str | None,
        promotion_commit_sha: str | None,
        worktree_path: str | None,
        revision: int,
        updated_at: datetime,
    ) -> ExecutionRecord:
        document = record.model_dump(mode="python")
        document.update(
            {
                "candidate_commit_sha": candidate_commit_sha,
                "promotion_commit_sha": promotion_commit_sha,
                "worktree_path": worktree_path,
                "revision": revision,
                "updated_at": updated_at,
            }
        )
        return ExecutionRecord.model_validate(document)

    @staticmethod
    def _resolved_verification_policy(
        artifact: CompiledGraphArtifact,
    ) -> tuple[ResolvedPolicySpec, VerificationPolicySpec] | None:
        matches = tuple(
            resolved
            for resolved in artifact.resolved_policies
            if resolved.requested_reference == _VERIFICATION_POLICY_REFERENCE
        )
        if not matches:
            return None
        if len(matches) != 1:
            raise ExecutionConfigurationError("compiled artifact contains duplicate verification policies")
        resolved = matches[0]
        try:
            policy = VerificationPolicySpec.model_validate(
                {
                    "policy_id": resolved.policy_id,
                    "policy_schema_version": resolved.policy_schema_version,
                    "definition_version": resolved.definition_version,
                    **resolved.effective_policy,
                }
            )
        except (TypeError, ValueError, ValidationError) as exc:
            raise ExecutionConfigurationError("compiled verification policy is invalid") from exc
        if (
            policy.policy_id != resolved.policy_id
            or policy.policy_schema_version != resolved.policy_schema_version
            or policy.definition_version != resolved.definition_version
            or policy.termination_rule != "ALL_REQUIRED_GATES_PASSED"
        ):
            raise ExecutionConfigurationError("compiled verification policy identity or termination rule is invalid")
        return resolved, policy

    @staticmethod
    def _resolved_retry_cost_policy(
        artifact: CompiledGraphArtifact,
    ) -> tuple[ResolvedPolicySpec, RetryCostPolicySpec] | None:
        matches = tuple(
            resolved
            for resolved in artifact.resolved_policies
            if resolved.requested_reference == _RETRY_COST_POLICY_REFERENCE
        )
        if not matches:
            return None
        if len(matches) != 1:
            raise ExecutionConfigurationError("compiled artifact contains duplicate retry cost policies")
        resolved = matches[0]
        try:
            policy = RetryCostPolicySpec.model_validate(
                {
                    "policy_id": resolved.policy_id,
                    "policy_schema_version": resolved.policy_schema_version,
                    "definition_version": resolved.definition_version,
                    **resolved.effective_policy,
                }
            )
        except (TypeError, ValueError, ValidationError) as exc:
            raise ExecutionConfigurationError("compiled retry cost policy is invalid") from exc
        return resolved, policy

    @staticmethod
    def _verification_repair_nodes(
        artifact: CompiledGraphArtifact,
    ) -> tuple[DeterministicNodeSpec, NodeSpec]:
        origins = tuple(
            node
            for node in artifact.graph.nodes
            if isinstance(node, DeterministicNodeSpec) and node.policy_ref == _VERIFICATION_POLICY_REFERENCE
        )
        if len(origins) != 1:
            raise ExecutionConfigurationError("verification repair requires one deterministic policy node")
        origin = origins[0]
        nodes = {node.id: node for node in artifact.graph.nodes}
        target = nodes.get(origin.on_failure)
        if target is None or target.retry_policy is None:
            raise ExecutionConfigurationError("verification correction edge is absent or unbounded")
        return origin, target

    def _resume_verification_repair(
        self,
        *,
        artifact: CompiledGraphArtifact,
        execution_id: str,
        record: ExecutionRecord,
        verification_policy: tuple[ResolvedPolicySpec, VerificationPolicySpec] | None,
    ) -> GraphExecutionResult | GraphExecutionPausedResult:
        if verification_policy is None:
            raise VerificationRequiredError(
                "execution requires canonical verification before resume",
                execution_id=execution_id,
            )
        retry_policy_context = self._resolved_retry_cost_policy(artifact)
        if retry_policy_context is None:
            raise ExecutionConfigurationError(
                "verification repair requires the compiled retry cost policy",
                execution_id=execution_id,
            )
        origin, target = self._verification_repair_nodes(artifact)
        self._verification_worktree(execution_id, record)
        resolved_verification, policy = verification_policy
        verification_digest = canonical_json_digest(
            canonical_json_object(resolved_verification.model_dump(mode="json"))
        )
        requirements = tuple(GateRequirement(gate_id=gate.id, required=gate.blocking) for gate in policy.required_gates)
        resolved_retry, retry_policy = retry_policy_context
        retry_policy_digest = canonical_json_digest(canonical_json_object(resolved_retry.model_dump(mode="json")))

        lock = self._acquire(execution_id)
        try:
            machine = self._state_machine(execution_id, lock)
            current = machine.recover(lock=lock)
            if current.current_state != ExecutionState.VERIFYING:
                raise VerificationLifecycleIntegrityError(
                    "verification repair state changed before scheduling",
                    execution_id=execution_id,
                )
            events = self._storage.load_events(execution_id, lock=lock)
            attempts = self._recover_verification_attempts(
                execution_id=execution_id,
                events=events,
                requirements=requirements,
                policy_digest=verification_digest,
                lock=lock,
            )
            if not attempts:
                raise VerificationRequiredError(
                    "execution requires canonical verification before resume",
                    execution_id=execution_id,
                )
            schedules = self._recover_repair_schedules(
                execution_id=execution_id,
                events=events,
                attempts=attempts,
                retry_policy_digest=retry_policy_digest,
                origin_node_id=origin.id,
                target_node_id=target.id,
            )
            latest = attempts[-1]
            if latest.suite.all_passed or (
                schedules
                and schedules[-1].source_verification_attempt == latest.attempt
                and schedules[-1].event_index > latest.event_index
            ):
                raise VerificationRequiredError(
                    "execution requires canonical verification after its repair",
                    execution_id=execution_id,
                )

            now = self._clock()
            if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
                raise VerificationLifecycleIntegrityError(
                    "verification retry clock must be timezone-aware",
                    execution_id=execution_id,
                )
            now = now.astimezone(UTC)
            deadline = (
                schedules[0].deadline_at
                if schedules
                else now + timedelta(seconds=retry_policy.cost_budget.max_retry_duration_seconds)
            )
            tokens_by_node, consumed_cost = self._verification_retry_usage(
                execution_id=execution_id,
                events=events,
                first_schedule_index=(schedules[0].event_index if schedules else None),
                policy=retry_policy,
            )
            consumed_tokens = tokens_by_node.get(target.id, 0)
            target_retry_policy = target.retry_policy
            if target_retry_policy is None:
                raise VerificationLifecycleIntegrityError(
                    "verification correction node lost its retry policy",
                    execution_id=execution_id,
                )
            reason: str | None = None
            if len(schedules) >= retry_policy.model_routing.retry_max:
                reason = "verification_execution_retry_exhausted"
            elif current.attempt_by_node.get(target.id, 0) + 1 > target_retry_policy.max_iterations:
                reason = "verification_node_retry_exhausted"
            elif any(tokens >= retry_policy.cost_budget.max_tokens_per_node for tokens in tokens_by_node.values()):
                reason = "verification_token_budget_exhausted"
            elif consumed_cost >= Decimal(str(retry_policy.cost_budget.max_cost_per_execution_usd)):
                reason = "verification_cost_budget_exhausted"
            elif now >= deadline:
                reason = "verification_time_budget_exhausted"
            if reason is not None:
                machine.transition_to(
                    ExecutionState.FAILED_RETRY_EXHAUSTED,
                    node_id=target.id,
                    attempt=current.attempt_by_node.get(target.id, 0),
                    reason=reason,
                    lock=lock,
                )
                raise VerificationRetryExhaustedError(
                    "verification repair budget was durably exhausted",
                    execution_id=execution_id,
                )

            failed_results = tuple(
                result
                for result in latest.suite.gate_results
                if result.required and result.status is not GateStatus.PASSED
            )
            if not failed_results:
                raise VerificationLifecycleIntegrityError(
                    "failed verification suite has no failed required gate",
                    execution_id=execution_id,
                )
            remaining_tokens = retry_policy.cost_budget.max_tokens_per_node - consumed_tokens
            remaining_cost = max(
                Decimal(0),
                Decimal(str(retry_policy.cost_budget.max_cost_per_execution_usd)) - consumed_cost,
            )
            remaining_time = (deadline - now).total_seconds()
            stdout = "\n".join(f"[{result.gate_id}]\n{result.stdout}" for result in failed_results)
            stderr = "\n".join(f"[{result.gate_id}]\n{result.stderr}" for result in failed_results)
            context = RetryContext(
                origin_node_id=origin.id,
                current_attempt=current.attempt_by_node.get(target.id, 0) + 1,
                failed_commit_sha=latest.suite.verified_commit_sha,
                model_error=None,
                failed_tool_call=None,
                redacted_stdout=Redactor.redact_text(stdout),
                redacted_stderr=Redactor.redact_text(stderr),
                failed_gates=tuple(result.gate_id for result in failed_results),
                current_diff="",
                remaining_budget=RetryBudget(
                    remaining_tokens=remaining_tokens,
                    remaining_cost_usd=float(remaining_cost),
                    remaining_time_seconds=remaining_time,
                ),
                correction_instruction=Redactor.redact_text(
                    "Correct the failed required gates on commit "
                    f"{latest.suite.verified_commit_sha}: " + ", ".join(result.gate_id for result in failed_results)
                ),
            )
            request = VerificationRepairRequest(
                source_verification_attempt=latest.attempt,
                source_suite_digest=latest.suite_digest,
                source_verified_commit_sha=latest.suite.verified_commit_sha,
                repair_attempt=len(schedules) + 1,
                retry_policy_digest=retry_policy_digest,
                origin_node_id=origin.id,
                target_node_id=target.id,
                deadline_at=deadline,
                retry_context=context,
            )
        finally:
            self._storage.release_execution_lock(lock)

        return self._graph_executor.retry_from_verification(
            artifact,
            execution_id,
            request,
            defer_completion=True,
        )

    def _verification_worktree(
        self,
        execution_id: str,
        record: ExecutionRecord,
    ) -> ProvisionedWorktree:
        provider = self._verification_worktree_provider
        try:
            if provider is None:
                raise VerificationConfigurationError("verification worktree provider is not configured")
            worktree = provider(execution_id)
            if not isinstance(worktree, ProvisionedWorktree):
                raise VerificationConfigurationError("verification worktree provider returned an invalid contract")
            reference = worktree.reference
            if (
                reference.execution_id != execution_id
                or reference.base_commit_sha != record.base_commit_sha
                or reference.original_branch != record.original_branch
            ):
                raise VerificationConfigurationError("verification worktree identity does not match the execution")
            expected_boundary = self._trust_boundary.bind_authorized_root(
                worktree.worktree_path
            )
            if worktree.trust_boundary != expected_boundary:
                raise VerificationConfigurationError(
                    "verification worktree trust boundary does not match the execution"
                )
            self._validate_verification_worktree_commit(
                worktree,
                expected_commit_sha=reference.worktree_head_sha,
            )
            return worktree
        except (VerificationConfigurationError, WorktreeError, OSError, ValueError) as exc:
            self._block_verification_prerequisite(execution_id)
            raise VerificationLifecyclePrerequisiteError(
                "verification worktree could not be validated",
                execution_id=execution_id,
            ) from exc

    def _verify_execution(
        self,
        *,
        artifact: CompiledGraphArtifact,
        execution_id: str,
        engine: VerificationEngine,
        policy_context: tuple[ResolvedPolicySpec, VerificationPolicySpec],
    ) -> VerificationSuiteResult:
        resolved_policy, policy = policy_context
        policy_digest = canonical_json_digest(canonical_json_object(resolved_policy.model_dump(mode="json")))
        full_requirements = tuple(
            GateRequirement(gate_id=gate.id, required=gate.blocking) for gate in policy.required_gates
        )
        verified_commit_sha = engine.worktree.reference.worktree_head_sha
        if verified_commit_sha is None:
            self._block_verification_prerequisite(execution_id)
            raise VerificationLifecyclePrerequisiteError(
                "verification worktree is missing its validated commit",
                execution_id=execution_id,
            )

        lock = self._acquire(execution_id)
        try:
            machine = self._state_machine(execution_id, lock)
            record = machine.recover(lock=lock)
            if record.current_state != ExecutionState.VERIFYING:
                raise VerificationLifecycleIntegrityError(
                    "verification state changed before the canonical suite acquired its lock",
                    execution_id=execution_id,
                )
            events = self._storage.load_events(execution_id, lock=lock)
            recovered = self._recover_verification_attempts(
                execution_id=execution_id,
                events=events,
                requirements=full_requirements,
                policy_digest=policy_digest,
                lock=lock,
            )
            schedules: tuple[_RepairSchedule, ...] = ()
            if any(event.event_type == VERIFICATION_REPAIR_SCHEDULED for event in events):
                retry_context = self._resolved_retry_cost_policy(artifact)
                if retry_context is None:
                    raise VerificationLifecycleIntegrityError(
                        "repair events exist without the compiled retry cost policy",
                        execution_id=execution_id,
                    )
                resolved_retry, _ = retry_context
                retry_digest = canonical_json_digest(canonical_json_object(resolved_retry.model_dump(mode="json")))
                origin, target = self._verification_repair_nodes(artifact)
                schedules = self._recover_repair_schedules(
                    execution_id=execution_id,
                    events=events,
                    attempts=recovered,
                    retry_policy_digest=retry_digest,
                    origin_node_id=origin.id,
                    target_node_id=target.id,
                )
                self._validate_repair_verification_sequence(
                    execution_id=execution_id,
                    attempts=recovered,
                    schedules=schedules,
                    full_requirements=full_requirements,
                )

            requirements_to_run: tuple[GateRequirement, ...] | None
            if not recovered:
                requirements_to_run = full_requirements
            else:
                latest = recovered[-1]
                if latest.full_suite and latest.suite.all_passed:
                    if latest.suite.verified_commit_sha != verified_commit_sha:
                        raise VerificationLifecycleIntegrityError(
                            "verified worktree changed after the passing full suite",
                            execution_id=execution_id,
                        )
                    if self._promotion_manager is None:
                        machine.transition_to(
                            ExecutionState.COMPLETED,
                            node_id=record.current_node_id,
                            attempt=0,
                            reason="verification_passed",
                            lock=lock,
                        )
                    return latest.suite
                if schedules and recovered[-1].event_index < schedules[-1].event_index:
                    source = recovered[-1]
                    if verified_commit_sha == source.suite.verified_commit_sha:
                        raise VerificationLifecycleIntegrityError(
                            "verification repair did not produce a new clean commit",
                            execution_id=execution_id,
                        )
                    requirements_to_run = self._failed_requirements(source)
                elif latest.suite.all_passed and not latest.full_suite:
                    if latest.suite.verified_commit_sha != verified_commit_sha:
                        raise VerificationLifecycleIntegrityError(
                            "worktree changed between targeted and full verification",
                            execution_id=execution_id,
                        )
                    requirements_to_run = full_requirements
                else:
                    return latest.suite

            last_timestamp = max(
                record.updated_at,
                events[-1].timestamp if events else record.updated_at,
            )
            if requirements_to_run is None:
                raise VerificationLifecycleIntegrityError(
                    "verification attempt selection is undefined",
                    execution_id=execution_id,
                )
            attempt_number = len(recovered) + 1
            certified, last_timestamp = self._run_verification_attempt(
                execution_id=execution_id,
                engine=engine,
                requirements=requirements_to_run,
                full_requirements=full_requirements,
                attempt_number=attempt_number,
                policy_digest=policy_digest,
                verified_commit_sha=verified_commit_sha,
                last_timestamp=last_timestamp,
                lock=lock,
                machine=machine,
            )
            if not certified.suite.all_passed or certified.full_suite:
                return certified.suite

            final, _ = self._run_verification_attempt(
                execution_id=execution_id,
                engine=engine,
                requirements=full_requirements,
                full_requirements=full_requirements,
                attempt_number=attempt_number + 1,
                policy_digest=policy_digest,
                verified_commit_sha=verified_commit_sha,
                last_timestamp=last_timestamp,
                lock=lock,
                machine=machine,
            )
            return final.suite
        except StateStorageError as exc:
            raise VerificationLifecycleIntegrityError(
                "verification evidence could not be persisted or recovered",
                execution_id=execution_id,
            ) from exc
        finally:
            self._storage.release_execution_lock(lock)

    @staticmethod
    def _failed_requirements(
        attempt: _VerificationAttempt,
    ) -> tuple[GateRequirement, ...]:
        failed_ids = {
            result.gate_id
            for result in attempt.suite.gate_results
            if result.required and result.status is not GateStatus.PASSED
        }
        selected = tuple(requirement for requirement in attempt.requirements if requirement.gate_id in failed_ids)
        if not selected:
            raise VerificationLifecycleIntegrityError("failed verification attempt has no failed required gate")
        return selected

    @classmethod
    def _validate_repair_verification_sequence(
        cls,
        *,
        execution_id: str,
        attempts: tuple[_VerificationAttempt, ...],
        schedules: tuple[_RepairSchedule, ...],
        full_requirements: tuple[GateRequirement, ...],
    ) -> None:
        for index, schedule in enumerate(schedules):
            source = attempts[schedule.source_verification_attempt - 1]
            next_schedule_index = schedules[index + 1].event_index if index + 1 < len(schedules) else None
            post_attempts = tuple(
                attempt
                for attempt in attempts
                if attempt.event_index > schedule.event_index
                and (next_schedule_index is None or attempt.event_index < next_schedule_index)
            )
            if len(post_attempts) > 2:
                raise VerificationLifecycleIntegrityError(
                    "one repair produced more than targeted and full verification",
                    execution_id=execution_id,
                )
            if not post_attempts:
                continue
            targeted = post_attempts[0]
            if (
                targeted.requirements != cls._failed_requirements(source)
                or targeted.full_suite
                or targeted.suite.verified_commit_sha == source.suite.verified_commit_sha
            ):
                raise VerificationLifecycleIntegrityError(
                    "repair did not produce the exact targeted verification attempt",
                    execution_id=execution_id,
                )
            if len(post_attempts) == 2:
                final = post_attempts[1]
                if (
                    not targeted.suite.all_passed
                    or not final.full_suite
                    or final.requirements != full_requirements
                    or final.suite.verified_commit_sha != targeted.suite.verified_commit_sha
                ):
                    raise VerificationLifecycleIntegrityError(
                        "full verification does not follow a passing targeted attempt",
                        execution_id=execution_id,
                    )

    def _run_verification_attempt(
        self,
        *,
        execution_id: str,
        engine: VerificationEngine,
        requirements: tuple[GateRequirement, ...],
        full_requirements: tuple[GateRequirement, ...],
        attempt_number: int,
        policy_digest: str,
        verified_commit_sha: str,
        last_timestamp: datetime,
        lock: ExecutionLock,
        machine: EventSourcedStateMachine,
    ) -> tuple[_VerificationAttempt, datetime]:
        pending: (
            tuple[
                int,
                GateRequirement,
                ResolvedGateCommand | None,
                int,
            ]
            | None
        ) = None
        gate_result_digests: list[str] = []
        next_gate_index = 0

        def append_event(
            event_type: Literal[
                "VERIFICATION_GATE_STARTED",
                "VERIFICATION_GATE_RECORDED",
                "VERIFICATION_SUITE_RECORDED",
            ],
            payload: dict[str, object],
        ) -> ExecutionEvent:
            nonlocal last_timestamp
            last_timestamp = self._next_timestamp(last_timestamp)
            return self._append_verification_event(
                execution_id,
                event_type,
                payload,
                timestamp=last_timestamp,
                lock=lock,
            )

        def before_gate(
            requirement: GateRequirement,
            command: ResolvedGateCommand | None,
        ) -> None:
            nonlocal pending
            if pending is not None:
                raise VerificationLifecycleIntegrityError(
                    "a verification gate started before the prior outcome was durable",
                    execution_id=execution_id,
                )
            self._validate_verification_worktree_commit(
                engine.worktree,
                expected_commit_sha=verified_commit_sha,
            )
            index = next_gate_index
            append_event(
                VERIFICATION_GATE_STARTED,
                {
                    "attempt": attempt_number,
                    "gate_index": index,
                    "gate_id": requirement.gate_id,
                    "required": requirement.required,
                    "argv": list(command.argv) if command is not None else [],
                    "cwd": command.cwd if command is not None else ".",
                    "policy_digest": policy_digest,
                    "verified_commit_sha": verified_commit_sha,
                    "fencing_token": lock.fencing_token,
                },
            )
            pending = (index, requirement, command, lock.fencing_token)

        def after_gate(result: GateResult) -> None:
            nonlocal pending, next_gate_index
            if pending is None:
                raise VerificationLifecycleIntegrityError(
                    "verification outcome has no matching write-ahead event",
                    execution_id=execution_id,
                )
            self._validate_verification_worktree_commit(
                engine.worktree,
                expected_commit_sha=verified_commit_sha,
            )
            index, requirement, command, fencing_token = pending
            expected_argv = command.argv if command is not None else ()
            if (
                result.gate_id != requirement.gate_id
                or result.required != requirement.required
                or result.argv != expected_argv
                or result.verified_commit_sha != verified_commit_sha
            ):
                raise VerificationLifecycleIntegrityError(
                    "verification outcome diverges from its write-ahead identity",
                    execution_id=execution_id,
                )
            result_digest = self._storage.store_payload(
                execution_id,
                result.model_dump(mode="json"),
                lock=lock,
            )
            append_event(
                VERIFICATION_GATE_RECORDED,
                {
                    "attempt": attempt_number,
                    "gate_index": index,
                    "gate_id": result.gate_id,
                    "required": result.required,
                    "status": result.status.value,
                    "result_digest": result_digest,
                    "policy_digest": policy_digest,
                    "verified_commit_sha": verified_commit_sha,
                    "fencing_token": fencing_token,
                },
            )
            gate_result_digests.append(result_digest)
            next_gate_index += 1
            pending = None

        try:
            suite = engine.verify_requirements(
                requirements,
                before_gate=before_gate,
                after_gate=after_gate,
            )
        except (VerificationConfigurationError, VerificationPrerequisiteError) as exc:
            current = machine.recover(lock=lock)
            if current.current_state == ExecutionState.VERIFYING:
                machine.transition_to(
                    ExecutionState.BLOCKED_PREREQUISITE,
                    node_id=current.current_node_id,
                    attempt=0,
                    reason="verification_prerequisite_invalid",
                    lock=lock,
                )
            raise VerificationLifecyclePrerequisiteError(
                "verification prerequisites failed before suite completion",
                execution_id=execution_id,
            ) from exc
        except (TypeError, ValueError, ValidationError) as exc:
            raise VerificationLifecycleIntegrityError(
                "verification result contract is invalid",
                execution_id=execution_id,
            ) from exc
        if pending is not None or len(gate_result_digests) != len(requirements):
            raise VerificationLifecycleIntegrityError(
                "verification suite ended with incomplete gate persistence",
                execution_id=execution_id,
            )
        suite_digest = self._storage.store_payload(
            execution_id,
            suite.model_dump(mode="json"),
            lock=lock,
        )
        suite_event = append_event(
            VERIFICATION_SUITE_RECORDED,
            {
                "attempt": attempt_number,
                "policy_digest": policy_digest,
                "verified_commit_sha": verified_commit_sha,
                "result_digest": suite_digest,
                "gate_result_digests": gate_result_digests,
                "all_passed": suite.all_passed,
                "fencing_token": lock.fencing_token,
            },
        )
        attempts = self._recover_verification_attempts(
            execution_id=execution_id,
            events=self._storage.load_events(execution_id, lock=lock),
            requirements=full_requirements,
            policy_digest=policy_digest,
            lock=lock,
        )
        certified = attempts[-1]
        if certified.attempt != attempt_number or certified.suite_digest != suite_digest:
            raise VerificationLifecycleIntegrityError(
                "persisted verification attempt could not be recovered",
                execution_id=execution_id,
            )
        if (
            certified.full_suite
            and certified.suite.all_passed
            and self._promotion_manager is None
        ):
            current = machine.recover(lock=lock)
            machine.transition_to(
                ExecutionState.COMPLETED,
                node_id=current.current_node_id,
                attempt=0,
                reason="verification_passed",
                lock=lock,
            )
        return certified, suite_event.timestamp

    @staticmethod
    def _validate_verification_worktree_commit(
        worktree: ProvisionedWorktree,
        *,
        expected_commit_sha: str | None,
    ) -> None:
        if type(expected_commit_sha) is not str or _GIT_SHA_PATTERN.fullmatch(expected_commit_sha) is None:
            raise VerificationConfigurationError("verification worktree commit identity is invalid")
        commands = (
            ("rev-parse", "--show-toplevel"),
            ("rev-parse", "--verify", "HEAD^{commit}"),
            ("status", "--porcelain=v1", "--untracked-files=all"),
        )
        outputs: list[str] = []
        for argv in commands:
            try:
                completed = subprocess.run(
                    ("git", *argv),
                    cwd=worktree.worktree_path,
                    check=False,
                    shell=False,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="strict",
                    timeout=30,
                )
            except (OSError, subprocess.SubprocessError, UnicodeError) as exc:
                raise VerificationConfigurationError("verification worktree Git identity could not be read") from exc
            if completed.returncode != 0:
                raise VerificationConfigurationError("verification worktree Git identity command failed")
            outputs.append(completed.stdout.strip())
        try:
            observed_root = Path(outputs[0]).resolve(strict=True)
            expected_root = worktree.worktree_path.resolve(strict=True)
        except (OSError, RuntimeError, ValueError) as exc:
            raise VerificationConfigurationError("verification worktree Git root could not be resolved") from exc
        if observed_root != expected_root:
            raise VerificationConfigurationError("verification path is not the exact Git worktree root")
        if outputs[1].lower() != expected_commit_sha:
            raise VerificationConfigurationError("verification worktree HEAD changed from the recorded commit")
        if outputs[2]:
            raise VerificationConfigurationError("verification worktree must be clean for commit-bound evidence")

    def _recover_verification_attempts(
        self,
        *,
        execution_id: str,
        events: tuple[ExecutionEvent, ...],
        requirements: tuple[GateRequirement, ...],
        policy_digest: str,
        lock: ExecutionLock,
    ) -> tuple[_VerificationAttempt, ...]:
        verification_events = tuple(
            (index, event) for index, event in enumerate(events) if event.event_type in _VERIFICATION_EVENT_TYPES
        )
        if not verification_events:
            return ()
        requirement_by_id = {requirement.gate_id: requirement for requirement in requirements}
        recovered: list[_VerificationAttempt] = []
        cursor = 0
        expected_attempt = 1
        while cursor < len(verification_events):
            gate_results: list[GateResult] = []
            gate_digests: list[str] = []
            attempt_requirements: list[GateRequirement] = []
            verified_commit_sha: str | None = None
            fencing_token: int | None = None
            gate_index = 0
            while (
                cursor < len(verification_events)
                and verification_events[cursor][1].event_type == VERIFICATION_GATE_STARTED
            ):
                if cursor + 1 >= len(verification_events):
                    raise VerificationLifecycleIntegrityError(
                        "verification journal contains an incomplete or duplicate suite",
                        execution_id=execution_id,
                    )
                _, started = verification_events[cursor]
                _, recorded = verification_events[cursor + 1]
                if (
                    recorded.event_type != VERIFICATION_GATE_RECORDED
                    or set(started.payload) != _VERIFICATION_GATE_STARTED_KEYS
                    or set(recorded.payload) != _VERIFICATION_GATE_RECORDED_KEYS
                ):
                    raise VerificationLifecycleIntegrityError(
                        "verification gate event sequence or payload schema is invalid",
                        execution_id=execution_id,
                    )
                start_payload = started.payload
                result_payload = recorded.payload
                gate_id = start_payload.get("gate_id")
                requirement = requirement_by_id.get(gate_id)  # type: ignore[arg-type]
                observed_fencing = start_payload.get("fencing_token")
                observed_commit = start_payload.get("verified_commit_sha")
                if (
                    requirement is None
                    or requirement in attempt_requirements
                    or start_payload.get("attempt") != expected_attempt
                    or result_payload.get("attempt") != expected_attempt
                    or start_payload.get("gate_index") != gate_index
                    or result_payload.get("gate_index") != gate_index
                    or result_payload.get("gate_id") != gate_id
                    or start_payload.get("required") is not requirement.required
                    or result_payload.get("required") is not requirement.required
                    or start_payload.get("policy_digest") != policy_digest
                    or result_payload.get("policy_digest") != policy_digest
                    or type(observed_fencing) is not int
                    or observed_fencing <= 0
                    or result_payload.get("fencing_token") != observed_fencing
                    or type(observed_commit) is not str
                    or _GIT_SHA_PATTERN.fullmatch(observed_commit) is None
                    or result_payload.get("verified_commit_sha") != observed_commit
                ):
                    raise VerificationLifecycleIntegrityError(
                        "verification gate identity is invalid",
                        execution_id=execution_id,
                    )
                if fencing_token is None:
                    fencing_token = observed_fencing
                elif fencing_token != observed_fencing:
                    raise VerificationLifecycleIntegrityError(
                        "one verification attempt spans multiple fencing tokens",
                        execution_id=execution_id,
                    )
                if verified_commit_sha is None:
                    verified_commit_sha = observed_commit
                elif verified_commit_sha != observed_commit:
                    raise VerificationLifecycleIntegrityError(
                        "one verification attempt spans multiple commits",
                        execution_id=execution_id,
                    )
                argv = start_payload.get("argv")
                cwd = start_payload.get("cwd")
                result_digest = result_payload.get("result_digest")
                if (
                    type(argv) is not list
                    or any(type(part) is not str or not part for part in argv)
                    or type(cwd) is not str
                    or not cwd
                    or type(result_digest) is not str
                    or _DIGEST_PATTERN.fullmatch(result_digest) is None
                ):
                    raise VerificationLifecycleIntegrityError(
                        "verification command or result digest is invalid",
                        execution_id=execution_id,
                    )
                try:
                    gate_result = GateResult.model_validate_json(
                        json.dumps(
                            self._storage.load_payload(
                                execution_id,
                                result_digest,
                                lock=lock,
                            ),
                            ensure_ascii=False,
                            allow_nan=False,
                        )
                    )
                except (TypeError, ValueError, ValidationError) as exc:
                    raise VerificationLifecycleIntegrityError(
                        "persisted gate result violates the F4.7 contract",
                        execution_id=execution_id,
                    ) from exc
                if (
                    gate_result.gate_id != requirement.gate_id
                    or gate_result.required != requirement.required
                    or list(gate_result.argv) != argv
                    or gate_result.cwd != cwd
                    or gate_result.verified_commit_sha != observed_commit
                    or result_payload.get("status") != gate_result.status.value
                ):
                    raise VerificationLifecycleIntegrityError(
                        "persisted gate result diverges from its journal identity",
                        execution_id=execution_id,
                    )
                gate_results.append(gate_result)
                gate_digests.append(result_digest)
                attempt_requirements.append(requirement)
                gate_index += 1
                cursor += 2

            if not gate_results or cursor >= len(verification_events):
                raise VerificationLifecycleIntegrityError(
                    "verification journal contains an incomplete or duplicate suite",
                    execution_id=execution_id,
                )
            suite_event_index, suite_event = verification_events[cursor]
            suite_payload = suite_event.payload
            if (
                suite_event.event_type != VERIFICATION_SUITE_RECORDED
                or set(suite_payload) != _VERIFICATION_SUITE_RECORDED_KEYS
                or suite_payload.get("attempt") != expected_attempt
                or suite_payload.get("policy_digest") != policy_digest
                or suite_payload.get("verified_commit_sha") != verified_commit_sha
                or suite_payload.get("fencing_token") != fencing_token
                or suite_payload.get("gate_result_digests") != gate_digests
                or type(suite_payload.get("all_passed")) is not bool
            ):
                raise VerificationLifecycleIntegrityError(
                    "persisted verification suite event is invalid",
                    execution_id=execution_id,
                )
            suite_digest = suite_payload.get("result_digest")
            if (
                type(suite_digest) is not str
                or _DIGEST_PATTERN.fullmatch(suite_digest) is None
                or verified_commit_sha is None
            ):
                raise VerificationLifecycleIntegrityError(
                    "persisted verification suite digest is invalid",
                    execution_id=execution_id,
                )
            suite = VerificationSuiteResult(
                verified_commit_sha=verified_commit_sha,
                gate_results=tuple(gate_results),
            )
            if (
                self._storage.load_payload(
                    execution_id,
                    suite_digest,
                    lock=lock,
                )
                != suite.model_dump(mode="json")
                or suite.all_passed is not suite_payload["all_passed"]
            ):
                raise VerificationLifecycleIntegrityError(
                    "persisted suite result diverges from gate evidence",
                    execution_id=execution_id,
                )
            ordered_subset = tuple(requirement for requirement in requirements if requirement in attempt_requirements)
            if tuple(attempt_requirements) != ordered_subset:
                raise VerificationLifecycleIntegrityError(
                    "verification attempt gates do not preserve policy order",
                    execution_id=execution_id,
                )
            full_suite = tuple(attempt_requirements) == requirements
            if expected_attempt == 1 and not full_suite:
                raise VerificationLifecycleIntegrityError(
                    "the first verification attempt must be the full policy suite",
                    execution_id=execution_id,
                )
            recovered.append(
                _VerificationAttempt(
                    attempt=expected_attempt,
                    requirements=tuple(attempt_requirements),
                    suite=suite,
                    suite_digest=suite_digest,
                    gate_result_digests=tuple(gate_digests),
                    policy_digest=policy_digest,
                    event_index=suite_event_index,
                    full_suite=full_suite,
                )
            )
            expected_attempt += 1
            cursor += 1
        return tuple(recovered)

    @staticmethod
    def _recover_repair_schedules(
        *,
        execution_id: str,
        events: tuple[ExecutionEvent, ...],
        attempts: tuple[_VerificationAttempt, ...],
        retry_policy_digest: str,
        origin_node_id: str,
        target_node_id: str,
    ) -> tuple[_RepairSchedule, ...]:
        schedules: list[_RepairSchedule] = []
        deadline: datetime | None = None
        for event_index, event in enumerate(events):
            if event.event_type != VERIFICATION_REPAIR_SCHEDULED:
                continue
            payload = event.payload
            source = next(
                (attempt for attempt in reversed(attempts) if attempt.event_index < event_index),
                None,
            )
            try:
                deadline_at = datetime.fromisoformat(str(payload.get("deadline_at")))
            except ValueError as exc:
                raise VerificationLifecycleIntegrityError(
                    "verification repair deadline is invalid",
                    execution_id=execution_id,
                ) from exc
            if (
                source is None
                or source.suite.all_passed
                or payload.get("repair_attempt") != len(schedules) + 1
                or payload.get("source_verification_attempt") != source.attempt
                or payload.get("source_result_digest") != source.suite_digest
                or payload.get("source_verified_commit_sha") != source.suite.verified_commit_sha
                or payload.get("retry_policy_digest") != retry_policy_digest
                or payload.get("origin_node_id") != origin_node_id
                or payload.get("target_node_id") != target_node_id
                or deadline_at.tzinfo is None
                or deadline_at.utcoffset() is None
            ):
                raise VerificationLifecycleIntegrityError(
                    "verification repair schedule diverges from canonical evidence",
                    execution_id=execution_id,
                )
            deadline_at = deadline_at.astimezone(UTC)
            if deadline is None:
                deadline = deadline_at
            elif deadline != deadline_at:
                raise VerificationLifecycleIntegrityError(
                    "verification repair deadline changed across attempts",
                    execution_id=execution_id,
                )
            schedules.append(
                _RepairSchedule(
                    repair_attempt=len(schedules) + 1,
                    source_verification_attempt=source.attempt,
                    source_result_digest=source.suite_digest,
                    source_verified_commit_sha=source.suite.verified_commit_sha,
                    origin_node_id=origin_node_id,
                    target_node_id=target_node_id,
                    retry_policy_digest=retry_policy_digest,
                    deadline_at=deadline_at,
                    event_index=event_index,
                )
            )
        return tuple(schedules)

    @staticmethod
    def _verification_retry_usage(
        *,
        execution_id: str,
        events: tuple[ExecutionEvent, ...],
        first_schedule_index: int | None,
        policy: RetryCostPolicySpec,
    ) -> tuple[dict[str, int], Decimal]:
        if first_schedule_index is None:
            return {}, Decimal(0)
        tokens_by_node: dict[str, int] = {}
        cost = Decimal(0)
        input_rate = Decimal(str(policy.cost_budget.input_cost_per_million_tokens_usd))
        output_rate = Decimal(str(policy.cost_budget.output_cost_per_million_tokens_usd))
        million = Decimal(1_000_000)
        for event_index, event in enumerate(events):
            if event_index <= first_schedule_index or event.event_type not in {
                "NODE_COMPLETED",
                "NODE_FAILED",
            }:
                continue
            raw_calls = event.payload.get("model_calls")
            if raw_calls is None:
                continue
            if type(raw_calls) is not list or not raw_calls:
                raise VerificationLifecycleIntegrityError(
                    "verification retry model usage is malformed",
                    execution_id=execution_id,
                )
            try:
                calls = tuple(ModelCallMetadata.model_validate(call) for call in raw_calls)
            except (TypeError, ValueError, ValidationError) as exc:
                raise VerificationLifecycleIntegrityError(
                    "verification retry model usage is invalid",
                    execution_id=execution_id,
                ) from exc
            node_id = event.payload.get("node_id")
            if type(node_id) is not str or not node_id:
                raise VerificationLifecycleIntegrityError(
                    "verification retry model usage has no node identity",
                    execution_id=execution_id,
                )
            tokens_by_node[node_id] = tokens_by_node.get(node_id, 0) + sum(call.total_tokens for call in calls)
            cost += sum(
                (Decimal(call.prompt_tokens) * input_rate + Decimal(call.completion_tokens) * output_rate) / million
                for call in calls
            )
        return tokens_by_node, cost

    def _recover_verification_suite(
        self,
        *,
        execution_id: str,
        events: tuple[ExecutionEvent, ...],
        requirements: tuple[GateRequirement, ...],
        policy_digest: str,
        verified_commit_sha: str,
        lock: ExecutionLock,
    ) -> VerificationSuiteResult | None:
        verification_events = tuple(event for event in events if event.event_type in _VERIFICATION_EVENT_TYPES)
        if not verification_events:
            return None
        expected_count = len(requirements) * 2 + 1
        if len(verification_events) != expected_count:
            raise VerificationLifecycleIntegrityError(
                "verification journal contains an incomplete or duplicate suite",
                execution_id=execution_id,
            )

        recovered_results: list[GateResult] = []
        recovered_digests: list[str] = []
        observed_fencing_token: int | None = None
        for index, requirement in enumerate(requirements):
            started = verification_events[index * 2]
            recorded = verification_events[index * 2 + 1]
            if (
                started.event_type != VERIFICATION_GATE_STARTED
                or recorded.event_type != VERIFICATION_GATE_RECORDED
                or set(started.payload) != _VERIFICATION_GATE_STARTED_KEYS
                or set(recorded.payload) != _VERIFICATION_GATE_RECORDED_KEYS
            ):
                raise VerificationLifecycleIntegrityError(
                    "verification gate event sequence or payload schema is invalid",
                    execution_id=execution_id,
                )
            start_payload = started.payload
            result_payload = recorded.payload
            fencing_token = start_payload.get("fencing_token")
            if (
                type(fencing_token) is not int
                or fencing_token <= 0
                or result_payload.get("fencing_token") != fencing_token
            ):
                raise VerificationLifecycleIntegrityError(
                    "verification gate fencing identity is invalid",
                    execution_id=execution_id,
                )
            if observed_fencing_token is None:
                observed_fencing_token = fencing_token
            elif observed_fencing_token != fencing_token:
                raise VerificationLifecycleIntegrityError(
                    "one verification suite spans multiple fencing tokens",
                    execution_id=execution_id,
                )
            shared_identity = (
                start_payload.get("attempt") == 1
                and result_payload.get("attempt") == 1
                and start_payload.get("gate_index") == index
                and result_payload.get("gate_index") == index
                and start_payload.get("gate_id") == requirement.gate_id
                and result_payload.get("gate_id") == requirement.gate_id
                and start_payload.get("required") is requirement.required
                and result_payload.get("required") is requirement.required
                and start_payload.get("policy_digest") == policy_digest
                and result_payload.get("policy_digest") == policy_digest
                and start_payload.get("verified_commit_sha") == verified_commit_sha
                and result_payload.get("verified_commit_sha") == verified_commit_sha
            )
            argv = start_payload.get("argv")
            cwd = start_payload.get("cwd")
            result_digest = result_payload.get("result_digest")
            if (
                not shared_identity
                or type(argv) is not list
                or any(type(part) is not str or not part for part in argv)
                or type(cwd) is not str
                or not cwd
                or type(result_digest) is not str
                or _DIGEST_PATTERN.fullmatch(result_digest) is None
            ):
                raise VerificationLifecycleIntegrityError(
                    "verification gate identity or result digest is invalid",
                    execution_id=execution_id,
                )
            try:
                gate_result = GateResult.model_validate_json(
                    json.dumps(
                        self._storage.load_payload(
                            execution_id,
                            result_digest,
                            lock=lock,
                        ),
                        ensure_ascii=False,
                        allow_nan=False,
                    )
                )
            except (TypeError, ValueError, ValidationError) as exc:
                raise VerificationLifecycleIntegrityError(
                    "persisted gate result violates the F4.7 contract",
                    execution_id=execution_id,
                ) from exc
            if (
                gate_result.gate_id != requirement.gate_id
                or gate_result.required != requirement.required
                or list(gate_result.argv) != argv
                or gate_result.cwd != cwd
                or gate_result.verified_commit_sha != verified_commit_sha
                or result_payload.get("status") != gate_result.status.value
            ):
                raise VerificationLifecycleIntegrityError(
                    "persisted gate result diverges from its journal identity",
                    execution_id=execution_id,
                )
            recovered_results.append(gate_result)
            recovered_digests.append(result_digest)

        suite_event = verification_events[-1]
        suite_payload = suite_event.payload
        if (
            suite_event.event_type != VERIFICATION_SUITE_RECORDED
            or set(suite_payload) != _VERIFICATION_SUITE_RECORDED_KEYS
            or suite_payload.get("attempt") != 1
            or suite_payload.get("policy_digest") != policy_digest
            or suite_payload.get("verified_commit_sha") != verified_commit_sha
            or suite_payload.get("fencing_token") != observed_fencing_token
            or suite_payload.get("gate_result_digests") != recovered_digests
            or type(suite_payload.get("all_passed")) is not bool
        ):
            raise VerificationLifecycleIntegrityError(
                "persisted verification suite event is invalid",
                execution_id=execution_id,
            )
        suite_digest = suite_payload.get("result_digest")
        if type(suite_digest) is not str or _DIGEST_PATTERN.fullmatch(suite_digest) is None:
            raise VerificationLifecycleIntegrityError(
                "persisted verification suite digest is invalid",
                execution_id=execution_id,
            )
        suite = VerificationSuiteResult(
            verified_commit_sha=verified_commit_sha,
            gate_results=tuple(recovered_results),
        )
        stored_suite = self._storage.load_payload(
            execution_id,
            suite_digest,
            lock=lock,
        )
        if (
            stored_suite != suite.model_dump(mode="json")
            or suite.all_passed is not suite_payload["all_passed"]
            or tuple(GateRequirement(gate_id=result.gate_id, required=result.required) for result in suite.gate_results)
            != requirements
        ):
            raise VerificationLifecycleIntegrityError(
                "persisted suite result diverges from gate evidence or policy",
                execution_id=execution_id,
            )
        return suite

    def _append_verification_event(
        self,
        execution_id: str,
        event_type: Literal[
            "VERIFICATION_GATE_STARTED",
            "VERIFICATION_GATE_RECORDED",
            "VERIFICATION_SUITE_RECORDED",
        ],
        payload: dict[str, object],
        *,
        timestamp: datetime,
        lock: ExecutionLock,
    ) -> ExecutionEvent:
        try:
            event = ExecutionEvent(
                event_id=self._event_id_factory(),
                execution_id=execution_id,
                event_type=event_type,
                timestamp=timestamp,
                payload=payload,
            )
        except (TypeError, ValueError, ValidationError) as exc:
            raise VerificationLifecycleIntegrityError(
                "cannot construct a canonical verification event",
                execution_id=execution_id,
            ) from exc
        return self._storage.append_event(execution_id, event, lock=lock)

    def _block_verification_prerequisite(self, execution_id: str) -> None:
        lock = self._acquire(execution_id)
        try:
            machine = self._state_machine(execution_id, lock)
            record = machine.recover(lock=lock)
            if record.current_state == ExecutionState.BLOCKED_PREREQUISITE:
                return
            if record.current_state != ExecutionState.VERIFYING:
                raise VerificationLifecycleIntegrityError(
                    "verification prerequisite failure occurred outside VERIFYING",
                    execution_id=execution_id,
                )
            machine.transition_to(
                ExecutionState.BLOCKED_PREREQUISITE,
                node_id=record.current_node_id,
                attempt=0,
                reason="verification_prerequisite_invalid",
                lock=lock,
            )
        finally:
            self._storage.release_execution_lock(lock)

    @staticmethod
    def _resolved_context_policy(
        artifact: CompiledGraphArtifact,
    ) -> tuple[ResolvedPolicySpec, ContextSufficiencyPolicySpec] | None:
        matches = tuple(
            resolved
            for resolved in artifact.resolved_policies
            if resolved.requested_reference == _CONTEXT_POLICY_REFERENCE
        )
        if not matches:
            return None
        if len(matches) != 1:
            raise ExecutionConfigurationError("compiled artifact contains duplicate context sufficiency policies")
        resolved = matches[0]
        try:
            policy = ContextSufficiencyPolicySpec.model_validate(
                {
                    "policy_id": resolved.policy_id,
                    "policy_schema_version": resolved.policy_schema_version,
                    "definition_version": resolved.definition_version,
                    **resolved.effective_policy,
                }
            )
        except (TypeError, ValueError, ValidationError) as exc:
            raise ExecutionConfigurationError("compiled context sufficiency policy is invalid") from exc
        if (
            policy.policy_id != resolved.policy_id
            or policy.policy_schema_version != resolved.policy_schema_version
            or policy.definition_version != resolved.definition_version
        ):
            raise ExecutionConfigurationError("compiled context policy identity does not match its resolved envelope")
        return resolved, policy

    @staticmethod
    def _context_envelope(
        initial_input: dict[str, object],
        artifact: CompiledGraphArtifact,
    ) -> _ContextExecutionEnvelope:
        try:
            envelope = _ContextExecutionEnvelope.model_validate(initial_input)
        except (TypeError, ValueError, ValidationError) as exc:
            raise ExecutionConfigurationError(
                "context-enabled execution requires exactly context_request and graph_input"
            ) from exc
        expected_workflow = envelope.context_request.graph_type.replace("_", "-")
        if artifact.graph.graph.name != expected_workflow:
            raise ExecutionConfigurationError("context graph_type does not match the compiled workflow")
        return envelope

    def _prepare_context_attempt(
        self,
        *,
        artifact: CompiledGraphArtifact,
        execution_id: str,
        request: RetrievalRequest,
        resolved_policy: ResolvedPolicySpec,
        policy: ContextSufficiencyPolicySpec,
    ) -> ContextSufficiencyReport:
        policy_digest = canonical_json_digest(canonical_json_object(resolved_policy.effective_policy))
        lock = self._acquire(execution_id)
        try:
            self._recover_approval_locked(execution_id, lock)
            machine = self._state_machine(execution_id, lock)
            record = machine.recover(lock=lock)
            events = self._storage.load_events(execution_id, lock=lock)
            context_events = self._validated_context_events(
                events,
                execution_id=execution_id,
                commit_sha=record.base_commit_sha,
                policy_digest=policy_digest,
            )
            if record.current_state == ExecutionState.INITIATED:
                if context_events:
                    raise ContextLifecycleIntegrityError(
                        "initiated execution already has context decisions",
                        execution_id=execution_id,
                    )
                attempt = 1
                record = machine.transition_to(
                    ExecutionState.CONTEXT_ASSEMBLING,
                    node_id=record.current_node_id,
                    attempt=attempt,
                    reason="context_assembly_started",
                    lock=lock,
                )
            elif record.current_state == ExecutionState.BLOCKED_INSUFFICIENT_CONTEXT:
                if not context_events:
                    raise ContextLifecycleIntegrityError(
                        "blocked context execution has no durable decision",
                        execution_id=execution_id,
                    )
                if len(context_events) >= policy.max_retrieval_retries + 1:
                    machine.transition_to(
                        ExecutionState.FAILED_RETRY_EXHAUSTED,
                        node_id=record.current_node_id,
                        attempt=len(context_events),
                        reason="context_retry_exhausted",
                        lock=lock,
                    )
                    raise ContextRetryExhaustedError(
                        "context retrieval retry budget is exhausted",
                        execution_id=execution_id,
                    )
                attempt = len(context_events) + 1
                record = machine.transition_to(
                    ExecutionState.CONTEXT_ASSEMBLING,
                    node_id=record.current_node_id,
                    attempt=attempt,
                    reason="context_retrieval_resumed",
                    lock=lock,
                )
                events = self._storage.load_events(execution_id, lock=lock)
            elif record.current_state == ExecutionState.CONTEXT_ASSEMBLING:
                pending = self._pending_context_event(events)
                if pending is not None:
                    return self._recover_context_decision(
                        pending,
                        request=request,
                        record=record,
                        policy_digest=policy_digest,
                        machine=machine,
                        lock=lock,
                    )
                attempt = len(context_events) + 1
            else:
                raise ContextLifecycleIntegrityError(
                    "context attempt requires INITIATED, CONTEXT_ASSEMBLING, or blocked context state",
                    execution_id=execution_id,
                )

            try:
                package = self._context_assembler.assemble(
                    execution_id=execution_id,
                    request=request,
                    workflow_name=artifact.graph.graph.name,
                    commit_sha=record.base_commit_sha,
                    policy=policy,
                    policy_digest=policy_digest,
                    attempt=attempt,
                )
            except InsufficientContextError as exc:
                self._persist_context_decision(
                    record,
                    exc.report,
                    outcome="insufficient",
                    policy_digest=policy_digest,
                    machine=machine,
                    lock=lock,
                )
                raise
            except ContextPrerequisiteError:
                self._transition_context_prerequisite(record, machine=machine, lock=lock)
                raise

            self._persist_context_decision(
                record,
                package.report,
                outcome="sufficient",
                policy_digest=policy_digest,
                machine=machine,
                lock=lock,
            )
            return package.report
        finally:
            self._storage.release_execution_lock(lock)

    def _persist_context_decision(
        self,
        record: ExecutionRecord,
        report: ContextSufficiencyReport,
        *,
        outcome: Literal["sufficient", "insufficient"],
        policy_digest: str,
        machine: EventSourcedStateMachine,
        lock: ExecutionLock,
    ) -> None:
        expected_outcome = "sufficient" if report.is_sufficient else "insufficient"
        if outcome != expected_outcome:
            raise ContextLifecycleIntegrityError(
                "context decision outcome does not match its report",
                execution_id=record.execution_id,
            )
        try:
            payload_digest = self._storage.store_payload(
                record.execution_id,
                report.model_dump(mode="json"),
                lock=lock,
            )
            self._append_context_event(
                record.execution_id,
                {
                    "attempt": report.attempt,
                    "commit_sha": record.base_commit_sha,
                    "outcome": outcome,
                    "payload_digest": payload_digest,
                    "policy_digest": policy_digest,
                },
                timestamp=self._next_timestamp(record.updated_at),
                lock=lock,
            )
        except (ContextLifecycleIntegrityError, StateStorageError) as exc:
            self._transition_context_prerequisite(record, machine=machine, lock=lock)
            raise ContextPrerequisiteError("context decision could not be persisted durably") from exc

        target = ExecutionState.PLANNING if outcome == "sufficient" else ExecutionState.BLOCKED_INSUFFICIENT_CONTEXT
        machine.transition_to(
            target,
            node_id=record.current_node_id,
            attempt=report.attempt,
            reason="context_sufficient" if outcome == "sufficient" else "context_insufficient",
            lock=lock,
        )

    def _recover_context_decision(
        self,
        event: ExecutionEvent,
        *,
        request: RetrievalRequest,
        record: ExecutionRecord,
        policy_digest: str,
        machine: EventSourcedStateMachine,
        lock: ExecutionLock,
    ) -> ContextSufficiencyReport:
        payload = event.payload
        digest = payload["payload_digest"]
        if not isinstance(digest, str):
            raise ContextLifecycleIntegrityError(
                "context event payload digest is invalid",
                execution_id=record.execution_id,
            )
        try:
            document = self._storage.load_payload(record.execution_id, digest, lock=lock)
            report = ContextSufficiencyReport.model_validate(document)
        except (StateStorageError, TypeError, ValueError, ValidationError) as exc:
            self._transition_context_prerequisite(record, machine=machine, lock=lock)
            raise ContextPrerequisiteError("persisted context decision is unavailable or invalid") from exc
        expected_query_digest = "sha256:" + hashlib.sha256(request.query.encode("utf-8")).hexdigest()
        outcome = payload["outcome"]
        if (
            report.commit_sha != record.base_commit_sha
            or report.policy_digest != policy_digest
            or report.attempt != payload["attempt"]
            or report.request.requirement_id != request.requirement_id
            or report.request.graph_type != request.graph_type
            or report.request.query_digest != expected_query_digest
            or report.is_sufficient != (outcome == "sufficient")
        ):
            self._transition_context_prerequisite(record, machine=machine, lock=lock)
            raise ContextPrerequisiteError("persisted context decision does not match the immutable execution")
        target = ExecutionState.PLANNING if report.is_sufficient else ExecutionState.BLOCKED_INSUFFICIENT_CONTEXT
        machine.transition_to(
            target,
            node_id=record.current_node_id,
            attempt=report.attempt,
            reason="context_sufficient" if report.is_sufficient else "context_insufficient",
            lock=lock,
        )
        if not report.is_sufficient:
            raise InsufficientContextError(report)
        return report

    @staticmethod
    def _pending_context_event(events: tuple[ExecutionEvent, ...]) -> ExecutionEvent | None:
        last_context_transition = -1
        last_context_decision = -1
        decision: ExecutionEvent | None = None
        for index, event in enumerate(events):
            if (
                event.event_type == "STATE_TRANSITIONED"
                and event.payload.get("to_state") == ExecutionState.CONTEXT_ASSEMBLING.value
            ):
                last_context_transition = index
            elif event.event_type == CONTEXT_EVALUATED:
                last_context_decision = index
                decision = event
        if last_context_decision > last_context_transition:
            return decision
        return None

    @staticmethod
    def _validated_context_events(
        events: tuple[ExecutionEvent, ...],
        *,
        execution_id: str,
        commit_sha: str,
        policy_digest: str,
    ) -> tuple[ExecutionEvent, ...]:
        decisions: list[ExecutionEvent] = []
        expected_keys = {
            "attempt",
            "commit_sha",
            "outcome",
            "payload_digest",
            "policy_digest",
        }
        for event in events:
            if event.event_type != CONTEXT_EVALUATED:
                continue
            payload = event.payload
            attempt = payload.get("attempt")
            if (
                set(payload) != expected_keys
                or type(attempt) is not int
                or attempt != len(decisions) + 1
                or payload.get("commit_sha") != commit_sha
                or payload.get("policy_digest") != policy_digest
                or payload.get("outcome") not in {"sufficient", "insufficient"}
                or not isinstance(payload.get("payload_digest"), str)
                or _DIGEST_PATTERN.fullmatch(str(payload.get("payload_digest"))) is None
            ):
                raise ContextLifecycleIntegrityError(
                    "context decision event history is invalid",
                    execution_id=execution_id,
                )
            decisions.append(event)
        return tuple(decisions)

    def _append_context_event(
        self,
        execution_id: str,
        payload: dict[str, object],
        *,
        timestamp: datetime,
        lock: ExecutionLock,
    ) -> ExecutionEvent:
        try:
            event = ExecutionEvent(
                event_id=self._event_id_factory(),
                execution_id=execution_id,
                event_type=CONTEXT_EVALUATED,
                timestamp=timestamp,
                payload=payload,
            )
        except (TypeError, ValueError, ValidationError) as exc:
            raise ContextLifecycleIntegrityError(
                "cannot construct a canonical context lifecycle event",
                execution_id=execution_id,
            ) from exc
        return self._storage.append_event(execution_id, event, lock=lock)

    @staticmethod
    def _transition_context_prerequisite(
        record: ExecutionRecord,
        *,
        machine: EventSourcedStateMachine,
        lock: ExecutionLock,
    ) -> None:
        machine.transition_to(
            ExecutionState.BLOCKED_PREREQUISITE,
            node_id=record.current_node_id,
            attempt=record.attempt_by_node.get(record.current_node_id, 0),
            reason="context_prerequisite_invalid",
            lock=lock,
        )

    def _prepare_plan(
        self,
        *,
        artifact: CompiledGraphArtifact,
        execution_id: str,
        request: RetrievalRequest,
        graph_input: dict[str, object],
        effective_configuration: Mapping[str, object],
    ) -> None:
        """Durably generate or recover the only plan authorized for graph traversal."""
        graph_input_digest = canonical_json_digest(canonical_json_object(graph_input))
        lock = self._acquire(execution_id)
        try:
            self._recover_approval_locked(execution_id, lock)
            machine = self._state_machine(execution_id, lock)
            record = machine.recover(lock=lock)
            ambiguous_effect = False
            try:
                if record.current_state != ExecutionState.PLANNING:
                    raise PlanningLifecycleIntegrityError(
                        "planning requires the canonical PLANNING state",
                        execution_id=execution_id,
                    )
                events = self._storage.load_events(execution_id, lock=lock)
                context_digest, report = self._planning_context(
                    artifact=artifact,
                    execution_id=execution_id,
                    request=request,
                    record=record,
                    events=events,
                    lock=lock,
                )
                started, generated = self._validated_plan_events(
                    events,
                    execution_id=execution_id,
                    context_digest=context_digest,
                    graph_input_digest=graph_input_digest,
                    schema_digest=Planner.schema_digest(),
                )
                verification_policy = self._required_resolved_policy(
                    artifact,
                    _VERIFICATION_POLICY_REFERENCE,
                )
                tool_policy = self._required_resolved_policy(
                    artifact,
                    _TOOL_POLICY_REFERENCE,
                )
                router = self._model_router_factory(effective_configuration)
                if not isinstance(router, ModelRouter):
                    raise TypeError("model_router_factory must return ModelRouter")
                planner = Planner(self.project_root, self._storage, router)

                if generated is not None:
                    plan_digest = generated.payload["plan_digest"]
                    assert isinstance(plan_digest, str)
                    planner.recover_plan(
                        execution_id=execution_id,
                        plan_digest=plan_digest,
                        context_digest=context_digest,
                        graph_input_digest=graph_input_digest,
                        workflow_name=record.workflow_name,
                        base_commit_sha=record.base_commit_sha,
                        lock=lock,
                    )
                    return
                if started is not None:
                    ambiguous_effect = True
                    raise PlanningLifecycleIntegrityError(
                        "planning provider effect is ambiguous and cannot be retried automatically",
                        execution_id=execution_id,
                    )

                planner.validate_route()
                minimum = max(
                    record.updated_at,
                    events[-1].timestamp if events else record.updated_at,
                )
                started = self._append_plan_event(
                    execution_id,
                    PLAN_GENERATION_STARTED,
                    {
                        "attempt": 1,
                        "context_digest": context_digest,
                        "graph_input_digest": graph_input_digest,
                        "schema_digest": Planner.schema_digest(),
                    },
                    timestamp=self._next_timestamp(minimum),
                    lock=lock,
                )
                result = planner.create_plan(
                    execution_id=execution_id,
                    context_report=report,
                    context_digest=context_digest,
                    context_request=request,
                    graph_input=graph_input,
                    workflow_name=record.workflow_name,
                    base_commit_sha=record.base_commit_sha,
                    verification_policy=verification_policy,
                    tool_policy=tool_policy,
                    active_node_ids=tuple(node.id for node in artifact.graph.nodes),
                    lock=lock,
                )
                response = result.response
                self._append_plan_event(
                    execution_id,
                    PLAN_GENERATED,
                    {
                        "attempt": 1,
                        "completion_tokens": response.completion_tokens,
                        "context_digest": context_digest,
                        "graph_input_digest": graph_input_digest,
                        "model_name": response.model_name,
                        "plan_digest": result.plan_digest,
                        "prompt_tokens": response.prompt_tokens,
                        "provider": response.provider,
                        "request_id": response.request_id,
                        "response_id": response.response_id,
                        "total_tokens": response.total_tokens,
                    },
                    timestamp=self._next_timestamp(started.timestamp),
                    lock=lock,
                )
            except (
                PlanPrerequisiteError,
                PlanningLifecycleIntegrityError,
                StateStorageError,
                TypeError,
                ValueError,
                ValidationError,
            ) as exc:
                current = machine.recover(lock=lock)
                if current.current_state == ExecutionState.PLANNING:
                    self._transition_planning_prerequisite(
                        current,
                        machine=machine,
                        lock=lock,
                        ambiguous=ambiguous_effect,
                    )
                raise PlanningPrerequisiteError(
                    "execution planning failed before graph traversal",
                    execution_id=execution_id,
                ) from exc
        finally:
            self._storage.release_execution_lock(lock)

    def _planning_context(
        self,
        *,
        artifact: CompiledGraphArtifact,
        execution_id: str,
        request: RetrievalRequest,
        record: ExecutionRecord,
        events: tuple[ExecutionEvent, ...],
        lock: ExecutionLock,
    ) -> tuple[str, ContextSufficiencyReport]:
        context_policy = self._resolved_context_policy(artifact)
        if context_policy is None:
            raise PlanningLifecycleIntegrityError(
                "planning activation requires the compiled context policy",
                execution_id=execution_id,
            )
        resolved, _ = context_policy
        policy_digest = canonical_json_digest(canonical_json_object(resolved.effective_policy))
        decisions = self._validated_context_events(
            events,
            execution_id=execution_id,
            commit_sha=record.base_commit_sha,
            policy_digest=policy_digest,
        )
        if not decisions or decisions[-1].payload.get("outcome") != "sufficient":
            raise PlanningLifecycleIntegrityError(
                "planning has no sufficient canonical context decision",
                execution_id=execution_id,
            )
        event = decisions[-1]
        context_digest = event.payload.get("payload_digest")
        if type(context_digest) is not str:
            raise PlanningLifecycleIntegrityError(
                "planning context digest is invalid",
                execution_id=execution_id,
            )
        try:
            report = ContextSufficiencyReport.model_validate(
                self._storage.load_payload(execution_id, context_digest, lock=lock)
            )
        except (StateStorageError, TypeError, ValueError, ValidationError) as exc:
            raise PlanningLifecycleIntegrityError(
                "planning context payload is unavailable or invalid",
                execution_id=execution_id,
            ) from exc
        query_digest = "sha256:" + hashlib.sha256(request.query.encode("utf-8")).hexdigest()
        if (
            not report.is_sufficient
            or report.recommended_action != "proceed"
            or report.gaps
            or report.attempt != event.payload.get("attempt")
            or report.commit_sha != record.base_commit_sha
            or report.workflow_name != record.workflow_name
            or report.policy_digest != policy_digest
            or report.request.requirement_id != request.requirement_id
            or report.request.graph_type != request.graph_type
            or report.request.query_digest != query_digest
        ):
            raise PlanningLifecycleIntegrityError(
                "planning context does not match the immutable execution",
                execution_id=execution_id,
            )
        return context_digest, report

    @staticmethod
    def _required_resolved_policy(
        artifact: CompiledGraphArtifact,
        reference: str,
    ) -> ResolvedPolicySpec:
        matches = tuple(policy for policy in artifact.resolved_policies if policy.requested_reference == reference)
        if len(matches) != 1:
            raise PlanningLifecycleIntegrityError(f"compiled planning policy must appear exactly once: {reference}")
        return matches[0]

    @staticmethod
    def _validated_plan_events(
        events: tuple[ExecutionEvent, ...],
        *,
        execution_id: str,
        context_digest: str,
        graph_input_digest: str,
        schema_digest: str,
    ) -> tuple[ExecutionEvent | None, ExecutionEvent | None]:
        started_events = tuple(
            (index, event) for index, event in enumerate(events) if event.event_type == PLAN_GENERATION_STARTED
        )
        generated_events = tuple(
            (index, event) for index, event in enumerate(events) if event.event_type == PLAN_GENERATED
        )
        if len(started_events) > 1 or len(generated_events) > 1:
            raise PlanningLifecycleIntegrityError(
                "planning attempt or outcome is duplicated",
                execution_id=execution_id,
            )
        started = started_events[0][1] if started_events else None
        generated = generated_events[0][1] if generated_events else None
        if generated is not None and (started is None or generated_events[0][0] <= started_events[0][0]):
            raise PlanningLifecycleIntegrityError(
                "planning outcome has no preceding attempt",
                execution_id=execution_id,
            )
        if started is not None:
            payload = started.payload
            if (
                set(payload) != {"attempt", "context_digest", "graph_input_digest", "schema_digest"}
                or payload.get("attempt") != 1
                or payload.get("context_digest") != context_digest
                or payload.get("graph_input_digest") != graph_input_digest
                or payload.get("schema_digest") != schema_digest
            ):
                raise PlanningLifecycleIntegrityError(
                    "planning start event is invalid",
                    execution_id=execution_id,
                )
        if generated is not None:
            payload = generated.payload
            expected_keys = {
                "attempt",
                "completion_tokens",
                "context_digest",
                "graph_input_digest",
                "model_name",
                "plan_digest",
                "prompt_tokens",
                "provider",
                "request_id",
                "response_id",
                "total_tokens",
            }
            request_id = payload.get("request_id")
            if (
                set(payload) != expected_keys
                or payload.get("attempt") != 1
                or payload.get("context_digest") != context_digest
                or payload.get("graph_input_digest") != graph_input_digest
                or type(payload.get("plan_digest")) is not str
                or _DIGEST_PATTERN.fullmatch(str(payload.get("plan_digest"))) is None
                or not ExecutionLifecycleService._is_trimmed_string(payload.get("provider"))
                or not ExecutionLifecycleService._is_trimmed_string(payload.get("model_name"))
                or not ExecutionLifecycleService._is_trimmed_string(payload.get("response_id"))
                or (request_id is not None and not ExecutionLifecycleService._is_trimmed_string(request_id))
                or any(
                    type(payload.get(key)) is not int or int(payload[key]) < 0
                    for key in ("prompt_tokens", "completion_tokens", "total_tokens")
                )
                or payload.get("total_tokens")
                != int(payload.get("prompt_tokens", -1)) + int(payload.get("completion_tokens", -1))
            ):
                raise PlanningLifecycleIntegrityError(
                    "planning outcome event is invalid",
                    execution_id=execution_id,
                )
        return started, generated

    def _append_plan_event(
        self,
        execution_id: str,
        event_type: Literal["PLAN_GENERATION_STARTED", "PLAN_GENERATED"],
        payload: dict[str, object],
        *,
        timestamp: datetime,
        lock: ExecutionLock,
    ) -> ExecutionEvent:
        try:
            event = ExecutionEvent(
                event_id=self._event_id_factory(),
                execution_id=execution_id,
                event_type=event_type,
                timestamp=timestamp,
                payload=payload,
            )
        except (TypeError, ValueError, ValidationError) as exc:
            raise PlanningLifecycleIntegrityError(
                "cannot construct a canonical planning lifecycle event",
                execution_id=execution_id,
            ) from exc
        return self._storage.append_event(execution_id, event, lock=lock)

    @staticmethod
    def _transition_planning_prerequisite(
        record: ExecutionRecord,
        *,
        machine: EventSourcedStateMachine,
        lock: ExecutionLock,
        ambiguous: bool,
    ) -> None:
        machine.transition_to(
            ExecutionState.BLOCKED_PREREQUISITE,
            node_id=record.current_node_id,
            attempt=record.attempt_by_node.get(record.current_node_id, 0),
            reason=("planning_effect_ambiguous" if ambiguous else "planning_prerequisite_invalid"),
            lock=lock,
        )

    def _configuration_from_bundle(
        self,
        bundle: ExecutionBundle,
        execution_id: str,
    ) -> dict[str, object]:
        try:
            configuration = json.loads(bundle.configuration_json)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ExecutionConfigurationError(
                "stored effective configuration is unavailable or invalid",
                execution_id=execution_id,
            ) from exc
        if type(configuration) is not dict:
            raise ExecutionConfigurationError(
                "stored effective configuration is not a JSON object",
                execution_id=execution_id,
            )
        try:
            validated = self._config_resolver.validate_persisted(configuration)
            canonical = canonical_json_object(validated)
        except (ModelEgressDeniedError, ValueError) as exc:
            raise ExecutionConfigurationError(
                "stored effective configuration is not a typed redacted projection",
                execution_id=execution_id,
            ) from exc
        if canonical != bundle.configuration_json:
            raise ExecutionConfigurationError(
                "stored effective configuration changed during typed validation",
                execution_id=execution_id,
            )
        self._validate_persisted_trust_boundary(validated, execution_id)
        return validated

    def _configuration_with_trust_boundary(
        self,
        configuration: Mapping[str, object],
    ) -> dict[str, object]:
        projected = dict(configuration)
        project_value = projected.get("project", {})
        if type(project_value) is not dict:
            raise ExecutionConfigurationError(
                "effective configuration project section must be an object"
            )
        project = dict(project_value)
        project["_trust_boundary"] = self._trust_boundary.snapshot()
        projected["project"] = project
        return projected

    def _validate_persisted_trust_boundary(
        self,
        configuration: Mapping[str, object],
        execution_id: str,
    ) -> None:
        try:
            self._trust_boundary.require_root(self.project_root)
        except (TrustBoundaryConfigurationError, TrustCapabilityDeniedError) as exc:
            raise ExecutionConfigurationError(
                "active trust boundary diverges from repository state",
                execution_id=execution_id,
            ) from exc
        project = configuration.get("project")
        raw_boundary = project.get("_trust_boundary") if type(project) is dict else None
        if raw_boundary is None:
            boundary = self._trust_boundary
            if (
                boundary.mode != "restricted"
                or boundary.marker_present
                or boundary.python_contracts
                or boundary.executable_aliases
                or boundary.secret_grants
                or boundary.hook_ids
                or boundary.promotion_allowed
                or boundary.repository_root != boundary.authorized_root
            ):
                raise ExecutionConfigurationError(
                    "legacy execution has no trust snapshot for the active boundary",
                    execution_id=execution_id,
                )
            return
        try:
            persisted = TrustEvaluationResult.from_snapshot(raw_boundary)
        except TrustBoundaryConfigurationError as exc:
            raise ExecutionConfigurationError(
                "stored trust boundary is invalid",
                execution_id=execution_id,
            ) from exc
        if persisted != self._trust_boundary:
            raise ExecutionConfigurationError(
                "stored trust boundary diverges from the active boundary",
                execution_id=execution_id,
            )

    @staticmethod
    def _is_trimmed_string(value: object) -> bool:
        return type(value) is str and bool(value.strip()) and value == value.strip()

    def approve(self, execution_id: str, *, approver: str) -> ExecutionRecord:
        """Approve exactly the currently paused immutable subject."""
        if type(approver) is not str or not approver.strip() or approver != approver.strip():
            raise ApprovalSubjectMismatchError(
                "approver must be a non-empty trimmed identifier",
                execution_id=execution_id,
            )
        lock = self._acquire(execution_id)
        try:
            record = self._recover_approval_locked(execution_id, lock)
            machine = self._state_machine(execution_id, lock)
            record = machine.recover(lock=lock)
            if record.current_state != ExecutionState.PAUSED_AWAITING_APPROVAL:
                raise ApprovalSubjectMismatchError(
                    "execution is not paused for approval",
                    execution_id=execution_id,
                )
            bundle = self._storage.load_execution_bundle(execution_id, lock=lock)
            self._configuration_from_bundle(bundle, execution_id)
            artifact = MAFAdapter.validate_snapshot(
                bundle.artifact_json,
                expected_digest=record.artifact_digest,
            )
            node = self._human_node(artifact, record.current_node_id, execution_id)
            request = self._latest_approval_request(execution_id, lock)
            subject_digest = self._approval_subject_digest(
                record,
                node_id=node.id,
                input_digest=request["input_digest"],
            )
            if request["subject_digest"] != subject_digest:
                raise ApprovalSubjectMismatchError(
                    "approval request does not match the current subject",
                    execution_id=execution_id,
                )
            existing = self._latest_approval_grant(execution_id, lock)
            if record.approval_status == ApprovalStatus.APPROVED:
                if existing is None or existing["approver"] != approver:
                    raise ApprovalSubjectMismatchError(
                        "execution was approved by a different approver",
                        execution_id=execution_id,
                    )
                return record
            if record.approval_status != ApprovalStatus.PENDING:
                raise ApprovalSubjectMismatchError(
                    "execution approval status is not pending",
                    execution_id=execution_id,
                )
            timestamp = self._next_timestamp(record.updated_at)
            target_revision = record.revision + 1
            self._append_lifecycle_event(
                execution_id,
                EXECUTION_APPROVED,
                {
                    "approver": approver,
                    "fencing_token": lock.fencing_token,
                    "node_id": node.id,
                    "record_revision": target_revision,
                    "subject_digest": subject_digest,
                },
                timestamp=timestamp,
                lock=lock,
            )
            replacement = self._approval_replacement(
                record,
                status=ApprovalStatus.APPROVED,
                revision=target_revision,
                updated_at=timestamp,
            )
            return self._storage.compare_and_set_execution(
                execution_id,
                record.revision,
                replacement,
                lock=lock,
            )
        finally:
            self._storage.release_execution_lock(lock)

    def cancel(self, execution_id: str) -> ExecutionRecord:
        """Transition a cancelable execution to the final CANCELLED state."""
        lock = self._acquire(execution_id)
        try:
            record = self._recover_approval_locked(execution_id, lock)
            machine = self._state_machine(execution_id, lock)
            record = machine.recover(lock=lock)
            if record.current_state == ExecutionState.CANCELLED:
                return record
            if not VALID_STATE_TRANSITIONS[record.current_state] or (
                ExecutionState.CANCELLED not in VALID_STATE_TRANSITIONS[record.current_state]
            ):
                raise ExecutionCancellationError(
                    "execution state cannot transition to CANCELLED",
                    execution_id=execution_id,
                )
            if record.approval_status in {
                ApprovalStatus.PENDING,
                ApprovalStatus.APPROVED,
            }:
                request = self._latest_approval_request(execution_id, lock)
                timestamp = self._next_timestamp(record.updated_at)
                target_revision = record.revision + 1
                self._append_lifecycle_event(
                    execution_id,
                    APPROVAL_INVALIDATED,
                    {
                        "fencing_token": lock.fencing_token,
                        "node_id": request["node_id"],
                        "reason": "execution_cancelled",
                        "record_revision": target_revision,
                        "subject_digest": request["subject_digest"],
                    },
                    timestamp=timestamp,
                    lock=lock,
                )
                record = self._storage.compare_and_set_execution(
                    execution_id,
                    record.revision,
                    self._approval_replacement(
                        record,
                        status=ApprovalStatus.INVALIDATED,
                        revision=target_revision,
                        updated_at=timestamp,
                    ),
                    lock=lock,
                )
            return machine.transition_to(
                ExecutionState.CANCELLED,
                node_id=record.current_node_id,
                attempt=record.attempt_by_node.get(record.current_node_id, 0),
                reason="execution_cancelled",
                lock=lock,
            )
        finally:
            self._storage.release_execution_lock(lock)

    def status(self, execution_id: str) -> ExecutionStatusView:
        """Return a redaction-safe canonical execution status."""
        record = self._load_recovered_record(execution_id)
        return self._status_view(record)

    def inspect(self, execution_id: str) -> ExecutionInspection:
        """Return canonical identity and event metadata without payload content."""
        lock = self._acquire(execution_id)
        try:
            record = self._recover_approval_locked(execution_id, lock)
            record = self._state_machine(execution_id, lock).recover(lock=lock)
            bundle = self._storage.load_execution_bundle(execution_id, lock=lock)
            events = self._storage.load_events(execution_id, lock=lock)
            return ExecutionInspection(
                status=self._status_view(record),
                artifact_digest=bundle.artifact_digest,
                configuration_digest=bundle.configuration_digest,
                initial_input_digest=bundle.initial_input_digest,
                event_count=len(events),
                event_types=tuple(event.event_type for event in events),
            )
        finally:
            self._storage.release_execution_lock(lock)

    def pause_for_approval(
        self,
        *,
        artifact: CompiledGraphArtifact,
        record: ExecutionRecord,
        node: HumanApprovalNodeSpec,
        input_digest: str,
        executed_node_ids: tuple[str, ...],
        lock: ExecutionLock,
    ) -> GraphExecutionPausedResult:
        """Persist an approval request and pause under the executor's lock."""
        current = self._recover_approval_locked(record.execution_id, lock)
        if current.revision != record.revision or current.current_node_id != node.id:
            raise ApprovalLifecycleIntegrityError(
                "approval pause snapshot changed under lock",
                execution_id=record.execution_id,
            )
        if current.current_state != ExecutionState.EXECUTING:
            raise ApprovalLifecycleIntegrityError(
                "approval pause requires EXECUTING state",
                execution_id=record.execution_id,
            )
        artifact_digest = canonical_json_digest(artifact.canonical_json())
        if artifact_digest != current.artifact_digest:
            raise ApprovalSubjectMismatchError(
                "approval artifact does not match the execution",
                execution_id=record.execution_id,
            )
        subject_digest = self._approval_subject_digest(
            current,
            node_id=node.id,
            input_digest=input_digest,
        )
        timestamp = self._next_timestamp(current.updated_at)
        target_revision = current.revision + 1
        self._append_lifecycle_event(
            current.execution_id,
            APPROVAL_REQUESTED,
            {
                "fencing_token": lock.fencing_token,
                "input_digest": input_digest,
                "node_id": node.id,
                "record_revision": target_revision,
                "subject_digest": subject_digest,
            },
            timestamp=timestamp,
            lock=lock,
        )
        current = self._storage.compare_and_set_execution(
            current.execution_id,
            current.revision,
            self._approval_replacement(
                current,
                status=ApprovalStatus.PENDING,
                revision=target_revision,
                updated_at=timestamp,
            ),
            lock=lock,
        )
        current = self._state_machine(current.execution_id, lock).transition_to(
            ExecutionState.PAUSED_AWAITING_APPROVAL,
            node_id=node.id,
            attempt=current.attempt_by_node.get(node.id, 0) + 1,
            reason="human_approval_requested",
            lock=lock,
        )
        return GraphExecutionPausedResult(
            execution_id=current.execution_id,
            node_id=node.id,
            approval_subject_digest=subject_digest,
            executed_node_ids=executed_node_ids,
            final_revision=current.revision,
            fencing_token=lock.fencing_token,
        )

    def is_approval_granted(
        self,
        *,
        record: ExecutionRecord,
        node: HumanApprovalNodeSpec,
        input_digest: str,
        lock: ExecutionLock,
    ) -> bool:
        """Check a grant against the exact current subject without mutating state."""
        if record.approval_status != ApprovalStatus.APPROVED:
            return False
        request = self._latest_approval_request(record.execution_id, lock)
        grant = self._latest_approval_grant(record.execution_id, lock)
        if grant is None:
            return False
        subject = self._approval_subject_digest(
            record,
            node_id=node.id,
            input_digest=input_digest,
        )
        return bool(
            request["node_id"] == node.id
            and request["input_digest"] == input_digest
            and request["subject_digest"] == subject
            and grant["node_id"] == node.id
            and grant["subject_digest"] == subject
        )

    def _prepare_resume(
        self,
        execution_id: str,
    ) -> tuple[ExecutionRecord, ExecutionBundle, CompiledGraphArtifact]:
        lock = self._acquire(execution_id)
        try:
            record = self._recover_approval_locked(execution_id, lock)
            machine = self._state_machine(execution_id, lock)
            record = machine.recover(lock=lock)
            bundle = self._storage.load_execution_bundle(execution_id, lock=lock)
            artifact = MAFAdapter.validate_snapshot(
                bundle.artifact_json,
                expected_digest=record.artifact_digest,
            )
            if bundle.configuration_digest != record.configuration_digest:
                raise ExecutionConfigurationError(
                    "stored configuration digest does not match the execution",
                    execution_id=execution_id,
                )
            self._configuration_from_bundle(bundle, execution_id)
            if record.current_state == ExecutionState.EXECUTING and (record.approval_status == ApprovalStatus.PENDING):
                node = self._human_node(artifact, record.current_node_id, execution_id)
                record = machine.transition_to(
                    ExecutionState.PAUSED_AWAITING_APPROVAL,
                    node_id=node.id,
                    attempt=record.attempt_by_node.get(node.id, 0) + 1,
                    reason="human_approval_requested",
                    lock=lock,
                )
            if record.current_state == ExecutionState.PAUSED_AWAITING_APPROVAL:
                if record.approval_status != ApprovalStatus.APPROVED:
                    raise ExecutionApprovalRequiredError(
                        "execution requires canonical approval before resume",
                        execution_id=execution_id,
                    )
                record = machine.transition_to(
                    ExecutionState.EXECUTING,
                    node_id=record.current_node_id,
                    attempt=record.attempt_by_node.get(record.current_node_id, 0) + 1,
                    reason="human_approval_resumed",
                    lock=lock,
                )
            return record, bundle, artifact
        finally:
            self._storage.release_execution_lock(lock)

    def _load_recovered_record(self, execution_id: str) -> ExecutionRecord:
        lock = self._acquire(execution_id)
        try:
            self._recover_approval_locked(execution_id, lock)
            return self._state_machine(execution_id, lock).recover(lock=lock)
        finally:
            self._storage.release_execution_lock(lock)

    def _recover_approval_locked(
        self,
        execution_id: str,
        lock: ExecutionLock,
    ) -> ExecutionRecord:
        record = self._storage.load_execution(execution_id, lock=lock)
        status = ApprovalStatus.NOT_REQUIRED
        committed_status = ApprovalStatus.NOT_REQUIRED
        active_subject: str | None = None
        active_node: str | None = None
        last_revision = -1
        last_fencing_token = 0
        pending: tuple[ExecutionEvent, ApprovalStatus] | None = None
        saw_event = False
        for event in self._storage.load_events(execution_id, lock=lock):
            if event.event_type not in _APPROVAL_EVENT_TYPES:
                continue
            saw_event = True
            payload = event.payload
            if event.event_type == APPROVAL_REQUESTED:
                expected_keys = {
                    "fencing_token",
                    "input_digest",
                    "node_id",
                    "record_revision",
                    "subject_digest",
                }
                if set(payload) != expected_keys or status not in {
                    ApprovalStatus.NOT_REQUIRED,
                    ApprovalStatus.APPROVED,
                    ApprovalStatus.INVALIDATED,
                }:
                    raise ApprovalLifecycleIntegrityError(
                        "approval request history is invalid",
                        execution_id=execution_id,
                    )
                self._require_digest(payload["input_digest"], execution_id)
                active_subject = self._require_digest(payload["subject_digest"], execution_id)
                active_node = self._require_string(payload["node_id"], execution_id)
                next_status = ApprovalStatus.PENDING
            elif event.event_type == EXECUTION_APPROVED:
                expected_keys = {
                    "approver",
                    "fencing_token",
                    "node_id",
                    "record_revision",
                    "subject_digest",
                }
                if set(payload) != expected_keys or status != ApprovalStatus.PENDING:
                    raise ApprovalLifecycleIntegrityError(
                        "approval grant history is invalid",
                        execution_id=execution_id,
                    )
                self._require_string(payload["approver"], execution_id)
                subject = self._require_digest(payload["subject_digest"], execution_id)
                node_id = self._require_string(payload["node_id"], execution_id)
                if subject != active_subject or node_id != active_node:
                    raise ApprovalSubjectMismatchError(
                        "approval grant subject does not match its request",
                        execution_id=execution_id,
                    )
                next_status = ApprovalStatus.APPROVED
            else:
                expected_keys = {
                    "fencing_token",
                    "node_id",
                    "reason",
                    "record_revision",
                    "subject_digest",
                }
                if set(payload) != expected_keys or status not in {
                    ApprovalStatus.PENDING,
                    ApprovalStatus.APPROVED,
                }:
                    raise ApprovalLifecycleIntegrityError(
                        "approval invalidation history is invalid",
                        execution_id=execution_id,
                    )
                if payload["reason"] != "execution_cancelled":
                    raise ApprovalLifecycleIntegrityError(
                        "approval invalidation reason is invalid",
                        execution_id=execution_id,
                    )
                subject = self._require_digest(payload["subject_digest"], execution_id)
                node_id = self._require_string(payload["node_id"], execution_id)
                if subject != active_subject or node_id != active_node:
                    raise ApprovalSubjectMismatchError(
                        "approval invalidation subject does not match",
                        execution_id=execution_id,
                    )
                next_status = ApprovalStatus.INVALIDATED
            revision = self._require_integer(payload["record_revision"], execution_id, minimum=1)
            fencing_token = self._require_integer(payload["fencing_token"], execution_id, minimum=1)
            if revision <= last_revision or fencing_token <= last_fencing_token:
                raise ApprovalLifecycleIntegrityError(
                    "approval revisions and fencing tokens must increase strictly",
                    execution_id=execution_id,
                )
            status = next_status
            last_revision = revision
            last_fencing_token = fencing_token
            if revision <= record.revision:
                if pending is not None:
                    raise ApprovalLifecycleIntegrityError(
                        "committed approval event follows a pending event",
                        execution_id=execution_id,
                    )
                committed_status = next_status
            else:
                if pending is not None or revision != record.revision + 1:
                    raise ApprovalLifecycleIntegrityError(
                        "approval event is not the next recoverable revision",
                        execution_id=execution_id,
                    )
                pending = (event, next_status)

        if not saw_event:
            if record.approval_status != ApprovalStatus.NOT_REQUIRED:
                raise ApprovalLifecycleIntegrityError(
                    "approval status has no canonical event history",
                    execution_id=execution_id,
                )
            return record
        if committed_status != record.approval_status:
            raise ApprovalLifecycleIntegrityError(
                "approval snapshot does not match committed event history",
                execution_id=execution_id,
            )
        if pending is None:
            return record
        event, next_status = pending
        replacement = self._approval_replacement(
            record,
            status=next_status,
            revision=record.revision + 1,
            updated_at=event.timestamp,
        )
        return self._storage.compare_and_set_execution(
            execution_id,
            record.revision,
            replacement,
            lock=lock,
        )

    def _latest_approval_request(
        self,
        execution_id: str,
        lock: ExecutionLock,
    ) -> Mapping[str, object]:
        requests = [
            event.payload
            for event in self._storage.load_events(execution_id, lock=lock)
            if event.event_type == APPROVAL_REQUESTED
        ]
        if not requests:
            raise ApprovalLifecycleIntegrityError(
                "approval request event is missing",
                execution_id=execution_id,
            )
        return requests[-1]

    def _latest_approval_grant(
        self,
        execution_id: str,
        lock: ExecutionLock,
    ) -> Mapping[str, object] | None:
        grants = [
            event.payload
            for event in self._storage.load_events(execution_id, lock=lock)
            if event.event_type == EXECUTION_APPROVED
        ]
        return grants[-1] if grants else None

    def _append_lifecycle_event(
        self,
        execution_id: str,
        event_type: Literal[
            "APPROVAL_REQUESTED",
            "EXECUTION_APPROVED",
            "APPROVAL_INVALIDATED",
        ],
        payload: dict[str, object],
        *,
        timestamp: datetime,
        lock: ExecutionLock,
    ) -> ExecutionEvent:
        try:
            event = ExecutionEvent(
                event_id=self._event_id_factory(),
                execution_id=execution_id,
                event_type=event_type,
                timestamp=timestamp,
                payload=payload,
            )
        except (TypeError, ValueError, ValidationError) as exc:
            raise ApprovalLifecycleIntegrityError(
                "cannot construct a canonical lifecycle event",
                execution_id=execution_id,
            ) from exc
        return self._storage.append_event(execution_id, event, lock=lock)

    def _state_machine(
        self,
        execution_id: str,
        lock: ExecutionLock,
    ) -> EventSourcedStateMachine:
        return EventSourcedStateMachine(
            self._storage,
            execution_id,
            lock_timeout_seconds=self._lock_timeout_seconds,
            clock=self._clock,
            event_id_factory=self._event_id_factory,
            owner_id_factory=self._owner_id_factory,
            lock=lock,
        )

    def _acquire(self, execution_id: str) -> ExecutionLock:
        return self._storage.acquire_execution_lock(
            execution_id,
            self._owner_id_factory(),
            timeout_seconds=self._lock_timeout_seconds,
        )

    def _next_timestamp(self, minimum: datetime) -> datetime:
        observed = self._clock()
        if (
            not isinstance(observed, datetime)
            or observed.tzinfo is None
            or observed.utcoffset() is None
            or observed.utcoffset() != timedelta(0)
            or observed < minimum
        ):
            raise ExecutionLifecycleError("lifecycle clock must be UTC and cannot regress")
        return observed.astimezone(UTC)

    @staticmethod
    def _approval_replacement(
        record: ExecutionRecord,
        *,
        status: ApprovalStatus,
        revision: int,
        updated_at: datetime,
    ) -> ExecutionRecord:
        document = record.model_dump(mode="python")
        document.update(
            {
                "approval_status": status,
                "revision": revision,
                "updated_at": updated_at,
            }
        )
        return ExecutionRecord.model_validate(document)

    @staticmethod
    def _status_view(record: ExecutionRecord) -> ExecutionStatusView:
        return ExecutionStatusView(
            execution_id=record.execution_id,
            workflow_name=record.workflow_name,
            current_node_id=record.current_node_id,
            current_state=record.current_state,
            approval_status=record.approval_status,
            revision=record.revision,
            updated_at=record.updated_at,
        )

    @staticmethod
    def _human_node(
        artifact: CompiledGraphArtifact,
        node_id: str,
        execution_id: str,
    ) -> HumanApprovalNodeSpec:
        node = next((item for item in artifact.graph.nodes if item.id == node_id), None)
        if not isinstance(node, HumanApprovalNodeSpec):
            raise ApprovalSubjectMismatchError(
                "current node is not an explicit human-approval node",
                execution_id=execution_id,
            )
        return node

    @staticmethod
    def _approval_subject_digest(
        record: ExecutionRecord,
        *,
        node_id: str,
        input_digest: object,
    ) -> str:
        digest = ExecutionLifecycleService._require_digest(
            input_digest,
            record.execution_id,
        )
        return canonical_json_digest(
            canonical_json_object(
                {
                    "artifact_digest": record.artifact_digest,
                    "configuration_digest": record.configuration_digest,
                    "execution_id": record.execution_id,
                    "input_digest": digest,
                    "node_id": node_id,
                }
            )
        )

    def _read_git_identity(self) -> tuple[str, str]:
        try:
            commit = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=self.project_root,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            branch = subprocess.run(
                ["git", "branch", "--show-current"],
                cwd=self.project_root,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        except (OSError, subprocess.CalledProcessError) as exc:
            raise ExecutionGitIdentityError("cannot establish starting Git identity") from exc
        return commit, branch

    @staticmethod
    def _validate_git_identity(commit: str, branch: str) -> None:
        if _GIT_SHA_PATTERN.fullmatch(commit) is None:
            raise ExecutionGitIdentityError("base commit must be a full lowercase Git SHA")
        if type(branch) is not str or not branch.strip() or branch != branch.strip():
            raise ExecutionGitIdentityError("original branch must be non-empty")

    def _default_execution_id(self) -> str:
        timestamp = self._next_timestamp(datetime.min.replace(tzinfo=UTC)).strftime("%Y%m%d%H%M%S")
        return f"exec-{timestamp}-{uuid.uuid4().hex[:12]}"

    @staticmethod
    def _require_string(value: object, execution_id: str) -> str:
        if type(value) is not str or not value.strip() or value != value.strip():
            raise ApprovalLifecycleIntegrityError(
                "approval payload string is invalid",
                execution_id=execution_id,
            )
        return value

    @staticmethod
    def _require_digest(value: object, execution_id: str) -> str:
        string = ExecutionLifecycleService._require_string(value, execution_id)
        if _DIGEST_PATTERN.fullmatch(string) is None:
            raise ApprovalLifecycleIntegrityError(
                "approval payload digest is invalid",
                execution_id=execution_id,
            )
        return string

    @staticmethod
    def _require_integer(value: object, execution_id: str, *, minimum: int) -> int:
        if type(value) is not int or value < minimum:
            raise ApprovalLifecycleIntegrityError(
                "approval payload integer is invalid",
                execution_id=execution_id,
            )
        return value


__all__ = [
    "APPROVAL_INVALIDATED",
    "APPROVAL_REQUESTED",
    "CANDIDATE_COMMIT_RECORDED",
    "CANDIDATE_COMMIT_STARTED",
    "EXECUTION_APPROVED",
    "PROMOTION_COMPLETED",
    "PROMOTION_DRY_RUN_RECORDED",
    "PROMOTION_STARTED",
    "ApprovalLifecycleIntegrityError",
    "ApprovalSubjectMismatchError",
    "ExecutionApprovalRequiredError",
    "ExecutionCancellationError",
    "ExecutionConfigurationError",
    "ExecutionGitIdentityError",
    "ExecutionInspection",
    "ExecutionLifecycleError",
    "ExecutionLifecycleService",
    "ExecutionStatusView",
    "PromotionLifecycleBaseChangedError",
    "PromotionLifecycleError",
    "PromotionLifecycleIntegrityError",
    "PromotionLifecyclePrerequisiteError",
    "VerificationRetryExhaustedError",
]
