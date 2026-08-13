"""Focused F2.5 lifecycle tests over immutable execution snapshots."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from ai_engineering_harness.compiler import GraphCompiler
from ai_engineering_harness.contracts.events import ExecutionEvent
from ai_engineering_harness.contracts.execution import (
    ApprovalStatus,
    ExecutionRecord,
    ExecutionState,
)
from ai_engineering_harness.core import ConfigResolver
from ai_engineering_harness.persistence import (
    AtomicFileStateStorage,
    ExecutionLock,
    StateWriteError,
)
from ai_engineering_harness.runtime import (
    ApprovalLifecycleIntegrityError,
    ApprovalSubjectMismatchError,
    DeterministicNodeExecutor,
    ExecutionCancellationError,
    ExecutionConfigurationError,
    ExecutionGitIdentityError,
    ExecutionLifecycleService,
    GraphExecutionPausedResult,
    GraphExecutionResult,
    NodeExecutionContext,
    NodeExecutionResult,
    NodeExecutorRegistry,
    NodeExecutorUnavailableError,
    VerificationLifecyclePrerequisiteError,
)
from ai_engineering_harness.security import (
    TrustBoundaryEvaluator,
    TrustEvaluationResult,
)

_BASE_TIME = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)


class _Clock:
    def __init__(self) -> None:
        self.value = _BASE_TIME

    def __call__(self) -> datetime:
        self.value += timedelta(seconds=1)
        return self.value


class _Ids:
    def __init__(self) -> None:
        self.value = 0

    def __call__(self) -> str:
        self.value += 1
        return f"lifecycle-test-event-{self.value}"


class _CountingConfigResolver(ConfigResolver):
    def __init__(self, project_root: Path) -> None:
        super().__init__(project_root)
        self.resolve_calls = 0

    def resolve(
        self,
        profile_name: str = "default",
        cli_overrides: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.resolve_calls += 1
        return super().resolve(profile_name, cli_overrides)


@dataclass
class _TraceBackend:
    calls: list[str]

    def execute(self, context: NodeExecutionContext) -> NodeExecutionResult:
        self.calls.append(context.node.id)
        return NodeExecutionResult.completed(
            {"completed_by": context.node.id, "source": context.input_payload}
        )


class _FailOnceCasStorage(AtomicFileStateStorage):
    def __init__(self, project_root: Path) -> None:
        super().__init__(project_root)
        self.fail_next_cas = False

    def compare_and_set_execution(
        self,
        execution_id: str,
        expected_revision: int,
        replacement: ExecutionRecord,
        *,
        lock: ExecutionLock | None = None,
    ) -> ExecutionRecord:
        if self.fail_next_cas:
            self.fail_next_cas = False
            raise StateWriteError("controlled lifecycle CAS failure")
        return super().compare_and_set_execution(
            execution_id,
            expected_revision,
            replacement,
            lock=lock,
        )


def _compiled_graph(
    project_root: Path,
    *,
    workflow: str,
    human_approval: bool = False,
) -> Path:
    node = (
        "  - id: approval\n"
        "    type: human_approval\n"
        "    approval_strategy: explicit\n"
        "    on_success: completed\n"
        "    on_failure: failed\n"
        if human_approval
        else "  - id: execute\n"
        "    type: deterministic\n"
        "    executor: deterministic_gate\n"
        "    gate_name: lifecycle\n"
        "    on_success: completed\n"
        "    on_failure: failed\n"
    )
    entrypoint = "approval" if human_approval else "execute"
    spec = project_root / f"{workflow}.yaml"
    spec.write_text(
        f"""graph:
  name: {workflow}
  graph_schema_version: "1.0"
  definition_version: "1.0.0"
  entrypoint: {entrypoint}
  status: stable
nodes:
{node}terminal_states:
  - id: completed
    outcome: success
  - id: failed
    outcome: failure
policies: []
contracts: []
""",
        encoding="utf-8",
    )
    return GraphCompiler(project_root).compile_graph(spec, workflow)


def _service(
    project_root: Path,
    storage: AtomicFileStateStorage | None = None,
    *,
    trace: list[str] | None = None,
    trust_boundary: TrustEvaluationResult | None = None,
) -> tuple[ExecutionLifecycleService, AtomicFileStateStorage, list[str]]:
    selected_storage = storage or AtomicFileStateStorage(project_root)
    selected_trace = trace if trace is not None else []
    service = ExecutionLifecycleService(
        project_root,
        selected_storage,
        NodeExecutorRegistry(
            deterministic=DeterministicNodeExecutor(_TraceBackend(selected_trace)),
        ),
        clock=_Clock(),
        event_id_factory=_Ids(),
        execution_id_factory=lambda: "exec-generated-lifecycle",
        owner_id_factory=lambda: "lifecycle-test-owner",
        git_identity_provider=lambda: ("a" * 40, "task/f2.5-execution-resume"),
        trust_boundary=trust_boundary,
    )
    return service, selected_storage, selected_trace


def test_resume_fails_when_the_active_trust_boundary_diverges(
    tmp_path: Path,
) -> None:
    artifact = _compiled_graph(
        tmp_path,
        workflow="trust-boundary-resume",
        human_approval=True,
    )
    original_boundary = TrustBoundaryEvaluator(tmp_path).evaluate()
    service, storage, _ = _service(
        tmp_path,
        trust_boundary=original_boundary,
    )
    paused = service.start(
        artifact,
        execution_id="exec-trust-boundary-resume",
        initial_input={},
        configuration={},
    )
    assert isinstance(paused, GraphExecutionPausedResult)
    bundle = storage.load_execution_bundle("exec-trust-boundary-resume")
    persisted = json.loads(bundle.configuration_json)["project"]["_trust_boundary"]
    assert persisted == original_boundary.snapshot()

    marker = tmp_path / ".harness" / "trusted_repository"
    marker.touch()

    with pytest.raises(ExecutionConfigurationError, match="boundary diverges"):
        service.resume("exec-trust-boundary-resume")


def test_start_bundle_payload_status_inspect_and_public_views(tmp_path: Path) -> None:
    artifact = _compiled_graph(tmp_path, workflow="start-public")
    service, storage, trace = _service(tmp_path)

    result = service.start(
        artifact,
        execution_id="exec-start-public",
        initial_input={"intent": "deliver"},
        configuration={"project": {"test_label": "isolated"}},
    )

    assert isinstance(result, GraphExecutionResult)
    assert result.outcome == "success"
    assert trace == ["execute"]
    record = storage.load_execution("exec-start-public")
    bundle = storage.load_execution_bundle("exec-start-public")
    assert record.artifact_digest == bundle.artifact_digest
    assert record.configuration_digest == bundle.configuration_digest
    assert storage.load_payload(
        "exec-start-public", bundle.initial_input_digest
    ) == {"intent": "deliver"}

    status = service.status("exec-start-public")
    inspection = service.inspect("exec-start-public")
    assert status.current_state == ExecutionState.VERIFYING
    assert status.approval_status == ApprovalStatus.NOT_REQUIRED
    assert inspection.status == status
    assert inspection.event_count == len(storage.load_events("exec-start-public"))
    rendered = inspection.model_dump_json()
    assert "deliver" not in rendered
    assert "isolated" not in rendered


def test_lifecycle_without_verification_policy_cannot_complete(tmp_path: Path) -> None:
    artifact = _compiled_graph(tmp_path, workflow="missing-verification-policy")
    service, storage, _ = _service(tmp_path)
    service.start(
        artifact,
        execution_id="exec-missing-verification-policy",
        initial_input={},
        configuration={},
    )

    with pytest.raises(
        VerificationLifecyclePrerequisiteError,
        match="does not contain a verification policy",
    ):
        service.verify("exec-missing-verification-policy")

    assert storage.load_execution(
        "exec-missing-verification-policy"
    ).current_state == ExecutionState.BLOCKED_PREREQUISITE


def test_start_unavailable_backend_fails_before_any_bundle_or_record(tmp_path: Path) -> None:
    artifact = _compiled_graph(tmp_path, workflow="unavailable-start")
    storage = AtomicFileStateStorage(tmp_path)
    service = ExecutionLifecycleService(
        tmp_path,
        storage,
        NodeExecutorRegistry(),
        git_identity_provider=lambda: ("a" * 40, "main"),
    )

    with pytest.raises(NodeExecutorUnavailableError):
        service.start(
            artifact,
            execution_id="exec-unavailable-start",
            initial_input={},
            configuration={},
        )

    assert storage.list_executions() == ()
    assert not (
        tmp_path / ".harness" / "artifacts" / "executions" / "exec-unavailable-start"
    ).exists()


def test_start_persists_only_typed_redacted_effective_configuration(
    tmp_path: Path,
) -> None:
    artifact = _compiled_graph(tmp_path, workflow="redacted-configuration")
    service, storage, _ = _service(tmp_path)
    raw_secret = "must-never-reach-the-execution-bundle"

    service.start(
        artifact,
        execution_id="exec-redacted-configuration",
        initial_input={},
        configuration={"project": {"deployment_token": raw_secret}},
    )

    bundle = storage.load_execution_bundle("exec-redacted-configuration")
    effective = json.loads(bundle.configuration_json)
    assert effective["project"]["deployment_token"] == "[REDACTED_SECRET]"
    assert effective["models"]["providers"]["openai"]["api_key_env"] == "OPENAI_API_KEY"
    execution_dir = (
        tmp_path
        / ".harness"
        / "artifacts"
        / "executions"
        / "exec-redacted-configuration"
    )
    assert all(
        raw_secret.encode("utf-8") not in path.read_bytes()
        for path in execution_dir.rglob("*")
        if path.is_file()
    )


def test_invalid_typed_configuration_fails_before_persistent_mutation(
    tmp_path: Path,
) -> None:
    artifact = _compiled_graph(tmp_path, workflow="invalid-typed-configuration")
    service, storage, _ = _service(tmp_path)

    with pytest.raises(ExecutionConfigurationError, match="effective configuration"):
        service.start(
            artifact,
            execution_id="exec-invalid-typed-configuration",
            initial_input={},
            cli_overrides={"context_sufficiency_threshold": "not-a-number"},
        )

    assert storage.list_executions() == ()


@pytest.mark.parametrize(
    "configuration",
    [
        {"api_key": "raw-secret"},
        {"nested": [{"token": "raw-secret"}]},
    ],
)
def test_start_secret_configuration_is_rejected_without_mutation(
    tmp_path: Path,
    configuration: dict[str, object],
) -> None:
    artifact = _compiled_graph(tmp_path, workflow="secret-configuration")
    service, storage, _ = _service(tmp_path)

    with pytest.raises(ExecutionConfigurationError):
        service.start(
            artifact,
            execution_id="exec-secret-configuration",
            initial_input={},
            configuration=configuration,
        )

    assert storage.list_executions() == ()


def test_start_invalid_git_identity_is_rejected_without_mutation(tmp_path: Path) -> None:
    artifact = _compiled_graph(tmp_path, workflow="git-identity")
    storage = AtomicFileStateStorage(tmp_path)
    service = ExecutionLifecycleService(
        tmp_path,
        storage,
        NodeExecutorRegistry(
            deterministic=DeterministicNodeExecutor(_TraceBackend([])),
        ),
        git_identity_provider=lambda: ("HEAD", "main"),
    )

    with pytest.raises(ExecutionGitIdentityError):
        service.start(
            artifact,
            execution_id="exec-invalid-git",
            initial_input={},
            configuration={},
        )

    assert storage.list_executions() == ()


def test_approval_pause_approve_resume_uses_immutable_snapshot(tmp_path: Path) -> None:
    artifact = _compiled_graph(
        tmp_path,
        workflow="approval-resume",
        human_approval=True,
    )
    service, storage, trace = _service(tmp_path)

    paused = service.start(
        artifact,
        execution_id="exec-approval-resume",
        initial_input={"change": "bounded"},
        configuration={"project": {"test_label": "frozen"}},
    )
    assert isinstance(paused, GraphExecutionPausedResult)
    status = service.status("exec-approval-resume")
    assert status.current_state == ExecutionState.PAUSED_AWAITING_APPROVAL
    assert status.approval_status == ApprovalStatus.PENDING
    assert trace == []

    artifact.write_text("{}\n", encoding="utf-8")
    approved = service.approve("exec-approval-resume", approver="reviewer-1")
    assert approved.approval_status == ApprovalStatus.APPROVED
    result = service.resume("exec-approval-resume")

    assert isinstance(result, GraphExecutionResult)
    assert result.outcome == "success"
    assert result.executed_node_ids == ("approval",)
    assert trace == []
    final = storage.load_execution("exec-approval-resume")
    assert final.current_state == ExecutionState.VERIFYING
    events = storage.load_events("exec-approval-resume")
    assert [event.event_type for event in events].count("APPROVAL_REQUESTED") == 1
    assert [event.event_type for event in events].count("EXECUTION_APPROVED") == 1


def test_resume_validates_bundle_without_reresolving_changed_live_configuration(
    tmp_path: Path,
) -> None:
    artifact = _compiled_graph(
        tmp_path,
        workflow="configuration-resume",
        human_approval=True,
    )
    storage = AtomicFileStateStorage(tmp_path)
    resolver = _CountingConfigResolver(tmp_path)
    service = ExecutionLifecycleService(
        tmp_path,
        storage,
        NodeExecutorRegistry(
            deterministic=DeterministicNodeExecutor(_TraceBackend([])),
        ),
        config_resolver=resolver,
        clock=_Clock(),
        event_id_factory=_Ids(),
        owner_id_factory=lambda: "configuration-resume-owner",
        git_identity_provider=lambda: ("a" * 40, "task/f5.1-resolve-config"),
    )
    paused = service.start(
        artifact,
        execution_id="exec-configuration-resume",
        initial_input={},
        cli_overrides={"context_sufficiency_threshold": 0.83},
    )
    assert isinstance(paused, GraphExecutionPausedResult)
    bundle_before = storage.load_execution_bundle("exec-configuration-resume")
    assert resolver.resolve_calls == 1

    profile_dir = tmp_path / ".harness" / "profiles"
    profile_dir.mkdir(parents=True, exist_ok=True)
    (profile_dir / "default.yaml").write_text(
        "context_sufficiency_threshold: 0.1\n",
        encoding="utf-8",
    )
    service.approve("exec-configuration-resume", approver="reviewer-f51")
    result = service.resume("exec-configuration-resume")

    assert isinstance(result, GraphExecutionResult)
    assert result.outcome == "success"
    assert resolver.resolve_calls == 1
    assert storage.load_execution_bundle("exec-configuration-resume") == bundle_before
    assert json.loads(bundle_before.configuration_json)["context_sufficiency_threshold"] == 0.83


def test_approval_event_before_cas_is_recovered_idempotently(tmp_path: Path) -> None:
    artifact = _compiled_graph(tmp_path, workflow="approval-crash", human_approval=True)
    storage = _FailOnceCasStorage(tmp_path)
    service, _, _ = _service(tmp_path, storage)
    service.start(
        artifact,
        execution_id="exec-approval-crash",
        initial_input={},
        configuration={},
    )
    storage.fail_next_cas = True

    with pytest.raises(StateWriteError, match="controlled"):
        service.approve("exec-approval-crash", approver="reviewer-1")

    before = storage.load_events("exec-approval-crash")
    approved = service.approve("exec-approval-crash", approver="reviewer-1")
    after = storage.load_events("exec-approval-crash")
    assert approved.approval_status == ApprovalStatus.APPROVED
    assert before == after
    assert [event.event_type for event in after].count("EXECUTION_APPROVED") == 1


def test_approval_mismatch_does_not_mutate_bytes(tmp_path: Path) -> None:
    artifact = _compiled_graph(tmp_path, workflow="approval-mismatch", human_approval=True)
    service, _, _ = _service(tmp_path)
    service.start(
        artifact,
        execution_id="exec-approval-mismatch",
        initial_input={},
        configuration={},
    )
    service.approve("exec-approval-mismatch", approver="reviewer-1")
    record_path = (
        tmp_path
        / ".harness"
        / "state"
        / "executions"
        / "exec-approval-mismatch"
        / "execution.json"
    )
    journal_path = record_path.with_name("event-journal.jsonl")
    before = (record_path.read_bytes(), journal_path.read_bytes())

    with pytest.raises(ApprovalSubjectMismatchError):
        service.approve("exec-approval-mismatch", approver="reviewer-2")

    assert (record_path.read_bytes(), journal_path.read_bytes()) == before


def test_approval_tampered_fencing_token_fails_closed(tmp_path: Path) -> None:
    artifact = _compiled_graph(tmp_path, workflow="approval-tamper", human_approval=True)
    service, storage, _ = _service(tmp_path)
    service.start(
        artifact,
        execution_id="exec-approval-tamper",
        initial_input={},
        configuration={},
    )
    record = storage.load_execution("exec-approval-tamper")
    request = next(
        event
        for event in storage.load_events("exec-approval-tamper")
        if event.event_type == "APPROVAL_REQUESTED"
    )
    storage.append_event(
        "exec-approval-tamper",
        ExecutionEvent(
            event_id="forged-approval-event",
            execution_id="exec-approval-tamper",
            event_type="EXECUTION_APPROVED",
            timestamp=record.updated_at + timedelta(seconds=1),
            payload={
                "approver": "forged-reviewer",
                "fencing_token": request.payload["fencing_token"],
                "node_id": request.payload["node_id"],
                "record_revision": record.revision + 1,
                "subject_digest": request.payload["subject_digest"],
            },
        ),
    )
    journal_before = storage.load_events("exec-approval-tamper")

    with pytest.raises(ApprovalLifecycleIntegrityError, match="fencing"):
        service.status("exec-approval-tamper")

    assert storage.load_events("exec-approval-tamper") == journal_before


def test_cancel_paused_invalidates_approval_and_is_idempotent(tmp_path: Path) -> None:
    artifact = _compiled_graph(tmp_path, workflow="cancel-paused", human_approval=True)
    service, storage, _ = _service(tmp_path)
    service.start(
        artifact,
        execution_id="exec-cancel-paused",
        initial_input={},
        configuration={},
    )

    cancelled = service.cancel("exec-cancel-paused")
    repeated = service.cancel("exec-cancel-paused")
    assert cancelled.current_state == ExecutionState.CANCELLED
    assert cancelled.approval_status == ApprovalStatus.INVALIDATED
    assert repeated == cancelled
    events = storage.load_events("exec-cancel-paused")
    assert [event.event_type for event in events].count("APPROVAL_INVALIDATED") == 1
    with pytest.raises(ExecutionCancellationError):
        service.resume("exec-cancel-paused")


def test_lifecycle_rejects_nonfinite_lock_timeout() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        ExecutionLifecycleService(
            Path.cwd(),
            AtomicFileStateStorage(Path.cwd()),
            NodeExecutorRegistry(),
            lock_timeout_seconds=float("nan"),
        )
