"""F3.7 end-to-end lifecycle composition over real Git repositories."""

from __future__ import annotations

import subprocess
from collections.abc import Collection
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ai_engineering_harness.compiler import GraphCompiler
from ai_engineering_harness.contracts import ApprovalStatus, ExecutionState
from ai_engineering_harness.contracts.execution import ExecutionRecord
from ai_engineering_harness.governance import (
    ApprovalContent,
    ApprovalGateResult,
    ApprovalManager,
)
from ai_engineering_harness.persistence import (
    AtomicFileStateStorage,
    ExecutionLock,
    StateWriteError,
)
from ai_engineering_harness.runtime import (
    CANDIDATE_COMMIT_RECORDED,
    CANDIDATE_COMMIT_STARTED,
    PROMOTION_APPROVAL_INVALIDATED,
    PROMOTION_APPROVAL_REQUESTED,
    PROMOTION_APPROVED,
    PROMOTION_COMPLETED,
    PROMOTION_DRY_RUN_RECORDED,
    PROMOTION_STARTED,
    ApprovalLifecycleIntegrityError,
    DeterministicNodeExecutor,
    ExecutionLifecycleService,
    GraphExecutionPausedResult,
    NodeExecutionContext,
    NodeExecutionResult,
    NodeExecutorRegistry,
    PromotionApprovalRequiredError,
    PromotionEffectAmbiguousError,
    PromotionLifecycleBaseChangedError,
    PromotionLifecycleIntegrityError,
    PromotionManager,
)
from ai_engineering_harness.security import (
    SecretGrant,
    TrustAuthorization,
    TrustBoundaryEvaluator,
)
from ai_engineering_harness.workspace import ExternalWorktreeManager


def _git(repository: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ("git", *arguments),
        cwd=repository,
        check=True,
        shell=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


_MUTATING_GIT_COMMANDS = frozenset(
    {
        "add",
        "am",
        "apply",
        "checkout",
        "cherry-pick",
        "commit",
        "merge",
        "rebase",
        "reset",
        "restore",
        "revert",
        "switch",
        "update-ref",
    }
)


def _record_mutating_git_operations(
    manager: PromotionManager,
    monkeypatch: pytest.MonkeyPatch,
) -> list[tuple[str, ...]]:
    operations: list[tuple[str, ...]] = []
    run_git = manager._run_git

    def record_git_operation(
        arguments: Collection[str],
        *,
        cwd: Path,
        allowed_returncodes: Collection[int] = (0,),
    ) -> subprocess.CompletedProcess[str]:
        operation = tuple(arguments)
        if operation and operation[0] in _MUTATING_GIT_COMMANDS:
            operations.append(operation)
        return run_git(
            arguments,
            cwd=cwd,
            allowed_returncodes=allowed_returncodes,
        )

    monkeypatch.setattr(manager, "_run_git", record_git_operation)
    return operations


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
            raise StateWriteError("controlled promotion CAS failure")
        return super().compare_and_set_execution(
            execution_id,
            expected_revision,
            replacement,
            lock=lock,
        )


class _FailPromotionOutcomeCasStorage(AtomicFileStateStorage):
    def __init__(self, project_root: Path) -> None:
        super().__init__(project_root)
        self.fail_promotion_outcome = True

    def compare_and_set_execution(
        self,
        execution_id: str,
        expected_revision: int,
        replacement: ExecutionRecord,
        *,
        lock: ExecutionLock | None = None,
    ) -> ExecutionRecord:
        if self.fail_promotion_outcome and replacement.promotion_commit_sha is not None:
            self.fail_promotion_outcome = False
            raise StateWriteError("controlled promotion outcome CAS failure")
        return super().compare_and_set_execution(
            execution_id,
            expected_revision,
            replacement,
            lock=lock,
        )


class _InterruptAfterGitPromotion(PromotionManager):
    def __init__(
        self,
        project_root: Path,
        worktree_manager: ExternalWorktreeManager,
    ) -> None:
        super().__init__(project_root, worktree_manager)
        self.interrupt_once = True

    def promote(  # type: ignore[no-untyped-def]
        self,
        candidate,
        *,
        dry_run: bool,
        approval_granted: bool = False,
    ):
        result = super().promote(
            candidate,
            dry_run=dry_run,
            approval_granted=approval_granted,
        )
        if not dry_run and self.interrupt_once and not result.recovered:
            self.interrupt_once = False
            raise PromotionEffectAmbiguousError("controlled post-Git interruption")
        return result


@dataclass(frozen=True, slots=True)
class _Backend:
    def execute(self, context: NodeExecutionContext) -> NodeExecutionResult:
        return NodeExecutionResult.completed({"node": context.node.id})


class _Clock:
    def __init__(self) -> None:
        self.current = datetime(2026, 8, 14, 12, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.current

    def advance(self, delta: timedelta) -> None:
        self.current += delta


@dataclass(frozen=True, slots=True)
class _Fixture:
    repository: Path
    artifact: Path
    base_sha: str
    branch: str
    worktrees: ExternalWorktreeManager


def _fixture(tmp_path: Path, *, human_approval: bool = True) -> _Fixture:
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / ".harness" / "policies").mkdir(parents=True)
    (repository / "tests").mkdir()
    (repository / ".gitignore").write_text(
        ".harness/state/\n.harness/artifacts/\n__pycache__/\n*.pyc\n",
        encoding="utf-8",
    )
    (repository / "tracked.txt").write_text("base\n", encoding="utf-8")
    (repository / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\naddopts = '-p no:cacheprovider'\n",
        encoding="utf-8",
    )
    (repository / "tests" / "test_target.py").write_text(
        "def test_target():\n    assert True\n",
        encoding="utf-8",
    )
    (repository / ".harness" / "policies" / "verification_policy.yaml").write_text(
        """policy_id: promotion-verification-v1
policy_schema_version: "1.0"
definition_version: "1.0.0"
applies_to:
  - f3-7-promotion
required_gates:
  - id: unit_test
    executor: deterministic
    command: "python -m pytest"
    blocking: true
termination_rule: ALL_REQUIRED_GATES_PASSED
on_failure: route_to_failure_classifier
""",
        encoding="utf-8",
    )
    graph = repository / "graph.yaml"
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
        "    gate_name: promotion\n"
        "    on_success: completed\n"
        "    on_failure: failed\n"
    )
    entrypoint = "approval" if human_approval else "execute"
    graph.write_text(
        f"""graph:
  name: f3-7-promotion
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
policies:
  - policies/verification_policy.yaml
contracts: []
""",
        encoding="utf-8",
    )
    _git(repository, "init", "--quiet")
    _git(repository, "config", "user.name", "Promotion Lifecycle Test")
    _git(repository, "config", "user.email", "promotion-lifecycle@example.invalid")
    _git(repository, "add", "--all", "--", ".")
    _git(repository, "commit", "--quiet", "-m", "base")
    base_sha = _git(repository, "rev-parse", "HEAD").stdout.strip().lower()
    branch = _git(repository, "branch", "--show-current").stdout.strip()
    boundary = TrustBoundaryEvaluator(
        repository,
        authorization=TrustAuthorization(
            repository_root=str(repository.resolve()),
            executable_aliases=("git", "python"),
            secret_grants=tuple(
                SecretGrant(name=name, consumers=("terminal:python",))
                for name in ("PATH", "Path", "SYSTEMROOT", "SystemRoot")
            ),
            promotion_allowed=True,
        ),
    ).evaluate()
    artifact = GraphCompiler(repository).compile_graph(graph, "f3-7-promotion")
    worktrees = ExternalWorktreeManager(
        repository,
        "promotion-lifecycle-tests",
        external_base_dir=tmp_path / "external-worktrees",
        trust_boundary=boundary,
    )
    return _Fixture(repository, artifact, base_sha, branch, worktrees)


def _service(
    fixture: _Fixture,
    storage: AtomicFileStateStorage,
    execution_id: str,
    *,
    promotion_manager: PromotionManager | None = None,
    clock: _Clock | None = None,
) -> tuple[ExecutionLifecycleService, PromotionManager]:
    manager = promotion_manager or PromotionManager(
        fixture.repository,
        fixture.worktrees,
    )
    service = ExecutionLifecycleService(
        fixture.repository,
        storage,
        NodeExecutorRegistry(
            deterministic=DeterministicNodeExecutor(_Backend()),
        ),
        git_identity_provider=lambda: (fixture.base_sha, fixture.branch),
        verification_worktree_provider=lambda selected: (
            fixture.worktrees.load_worktree(selected)
            if selected == execution_id
            else pytest.fail("unexpected execution id")
        ),
        promotion_manager=manager,
        clock=clock,
    )
    return service, manager


def _approved_candidate(
    fixture: _Fixture,
    storage: AtomicFileStateStorage,
    execution_id: str,
    *,
    promotion_manager: PromotionManager | None = None,
    clock: _Clock | None = None,
) -> tuple[ExecutionLifecycleService, PromotionManager, ExecutionRecord]:
    service, manager = _service(
        fixture,
        storage,
        execution_id,
        promotion_manager=promotion_manager,
        clock=clock,
    )
    paused = service.start(
        fixture.artifact,
        execution_id=execution_id,
        initial_input={"change": "bounded"},
        configuration={},
    )
    assert isinstance(paused, GraphExecutionPausedResult)
    service.approve(execution_id, approver="reviewer-f37")
    service.resume(execution_id)
    worktree = fixture.worktrees.create_worktree(
        execution_id,
        expected_base_commit_sha=fixture.base_sha,
    )
    (worktree.worktree_path / "tracked.txt").write_text(
        "candidate\n",
        encoding="utf-8",
    )
    record = service.prepare_candidate(execution_id, message="feat: safe candidate")
    return service, manager, record


def _approve_exact_candidate(
    service: ExecutionLifecycleService,
    execution_id: str,
) -> None:
    request = service.request_promotion_approval(
        execution_id,
        reason="Promote the exact verified candidate",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    approved = service.approve(
        execution_id,
        approver="reviewer-f56",
        comment="Candidate, plan, diff and gates reviewed",
    )
    assert request.status is ApprovalStatus.PENDING
    assert approved.approval_status is ApprovalStatus.APPROVED


def test_approved_verified_candidate_is_promoted_by_one_real_cherry_pick(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path)
    storage = AtomicFileStateStorage(fixture.repository)
    execution_id = "exec-f37-live"
    service, manager, candidate_record = _approved_candidate(
        fixture,
        storage,
        execution_id,
    )
    mutating_operations = _record_mutating_git_operations(manager, monkeypatch)

    suite = service.verify(execution_id)
    _approve_exact_candidate(service, execution_id)
    verified = storage.load_execution(execution_id)
    promoted = service.promote(execution_id)

    assert candidate_record.candidate_commit_sha is not None
    assert suite.all_passed is True
    assert suite.verified_commit_sha == candidate_record.candidate_commit_sha
    assert verified.current_state is ExecutionState.VERIFYING
    assert verified.approval_status is ApprovalStatus.APPROVED
    assert promoted.current_state is ExecutionState.COMPLETED
    assert promoted.promotion_commit_sha is not None
    assert mutating_operations == [
        ("cherry-pick", candidate_record.candidate_commit_sha)
    ]
    assert _git(fixture.repository, "rev-parse", "HEAD^").stdout.strip().lower() == (fixture.base_sha)
    assert (fixture.repository / "tracked.txt").read_text(encoding="utf-8") == ("candidate\n")
    event_types = tuple(event.event_type for event in storage.load_events(execution_id))
    assert CANDIDATE_COMMIT_STARTED in event_types
    assert CANDIDATE_COMMIT_RECORDED in event_types
    assert PROMOTION_APPROVAL_REQUESTED in event_types
    assert PROMOTION_APPROVED in event_types
    assert PROMOTION_STARTED in event_types
    assert PROMOTION_COMPLETED in event_types
    approval = ApprovalManager(fixture.repository).load(execution_id)
    assert approval is not None
    assert approval.status is ApprovalStatus.APPROVED
    assert approval.candidate_commit_sha == candidate_record.candidate_commit_sha
    assert approval.gate_results[0].status == "PASSED"
    assert approval.approver_id == "reviewer-f56"


def test_dry_run_records_terminal_no_effect_without_promotion_sha(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    storage = AtomicFileStateStorage(fixture.repository)
    execution_id = "exec-f37-dry"
    service, _, _ = _approved_candidate(fixture, storage, execution_id)
    service.verify(execution_id)
    _approve_exact_candidate(service, execution_id)

    completed = service.promote(execution_id, dry_run=True)

    assert completed.current_state is ExecutionState.DRY_RUN_COMPLETED
    assert completed.candidate_commit_sha is not None
    assert completed.promotion_commit_sha is None
    assert _git(fixture.repository, "rev-parse", "HEAD").stdout.strip().lower() == (fixture.base_sha)
    assert (fixture.repository / "tracked.txt").read_text(encoding="utf-8") == "base\n"
    assert PROMOTION_DRY_RUN_RECORDED in {event.event_type for event in storage.load_events(execution_id)}


def test_original_base_advance_transitions_to_blocked_without_candidate_effect(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    storage = AtomicFileStateStorage(fixture.repository)
    execution_id = "exec-f37-base-change"
    service, _, _ = _approved_candidate(fixture, storage, execution_id)
    service.verify(execution_id)
    _approve_exact_candidate(service, execution_id)
    (fixture.repository / "advanced.txt").write_text("advanced\n", encoding="utf-8")
    _git(fixture.repository, "add", "--all", "--", ".")
    _git(fixture.repository, "commit", "--quiet", "-m", "advance base")
    advanced_sha = _git(fixture.repository, "rev-parse", "HEAD").stdout.strip().lower()

    with pytest.raises(PromotionLifecycleBaseChangedError):
        service.promote(execution_id)

    blocked = storage.load_execution(execution_id)
    assert blocked.current_state is ExecutionState.BLOCKED_BASE_CHANGED
    assert blocked.promotion_commit_sha is None
    assert _git(fixture.repository, "rev-parse", "HEAD").stdout.strip().lower() == (advanced_sha)
    assert (fixture.repository / "tracked.txt").read_text(encoding="utf-8") == "base\n"


def test_interrupted_live_effect_is_recovered_without_second_cherry_pick(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    storage = AtomicFileStateStorage(fixture.repository)
    execution_id = "exec-f37-recover-effect"
    interrupting = _InterruptAfterGitPromotion(
        fixture.repository,
        fixture.worktrees,
    )
    service, _, _ = _approved_candidate(
        fixture,
        storage,
        execution_id,
        promotion_manager=interrupting,
    )
    service.verify(execution_id)
    _approve_exact_candidate(service, execution_id)

    with pytest.raises(PromotionLifecycleIntegrityError):
        service.promote(execution_id)
    effect_sha = _git(fixture.repository, "rev-parse", "HEAD").stdout.strip().lower()
    assert storage.load_execution(execution_id).current_state is ExecutionState.PROMOTING

    completed = service.promote(execution_id)

    assert completed.current_state is ExecutionState.COMPLETED
    assert completed.promotion_commit_sha == effect_sha
    assert _git(fixture.repository, "rev-list", "--count", "HEAD").stdout.strip() == "2"


def test_candidate_outcome_before_cas_is_recovered_without_duplicate_git_effect(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    storage = _FailOnceCasStorage(fixture.repository)
    execution_id = "exec-f37-recover-candidate"
    service, _ = _service(fixture, storage, execution_id)
    service.start(
        fixture.artifact,
        execution_id=execution_id,
        initial_input={},
        configuration={},
    )
    service.approve(execution_id, approver="reviewer-f37")
    service.resume(execution_id)
    worktree = fixture.worktrees.create_worktree(
        execution_id,
        expected_base_commit_sha=fixture.base_sha,
    )
    (worktree.worktree_path / "tracked.txt").write_text(
        "candidate\n",
        encoding="utf-8",
    )
    storage.fail_next_cas = True

    with pytest.raises(PromotionLifecycleIntegrityError):
        service.prepare_candidate(execution_id)
    candidate_sha = _git(worktree.worktree_path, "rev-parse", "HEAD").stdout.strip().lower()
    before = storage.load_events(execution_id)

    recovered = service.prepare_candidate(execution_id)

    after = storage.load_events(execution_id)
    assert recovered.candidate_commit_sha == candidate_sha
    assert before == after
    assert [event.event_type for event in after].count(CANDIDATE_COMMIT_RECORDED) == 1


def test_approval_request_event_before_cas_recovers_without_duplicate_request(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    storage = _FailOnceCasStorage(fixture.repository)
    execution_id = "exec-f56-recover-request"
    service, _, _ = _approved_candidate(fixture, storage, execution_id)
    service.verify(execution_id)
    expires_at = datetime.now(UTC) + timedelta(hours=1)
    storage.fail_next_cas = True

    with pytest.raises(ApprovalLifecycleIntegrityError):
        service.request_promotion_approval(
            execution_id,
            reason="Recover exact approval request",
            expires_at=expires_at,
        )
    before = storage.load_events(execution_id)

    request = service.request_promotion_approval(
        execution_id,
        reason="Recover exact approval request",
        expires_at=expires_at,
    )
    after = storage.load_events(execution_id)

    assert request.status is ApprovalStatus.PENDING
    assert before == after
    assert [event.event_type for event in after].count(PROMOTION_APPROVAL_REQUESTED) == 1
    assert ApprovalManager(fixture.repository).load(execution_id) == request


def test_promotion_outcome_before_cas_is_recovered_without_duplicate_event(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    storage = _FailPromotionOutcomeCasStorage(fixture.repository)
    execution_id = "exec-f37-recover-outcome"
    service, _, _ = _approved_candidate(fixture, storage, execution_id)
    service.verify(execution_id)
    _approve_exact_candidate(service, execution_id)

    with pytest.raises(PromotionLifecycleIntegrityError):
        service.promote(execution_id)
    effect_sha = _git(fixture.repository, "rev-parse", "HEAD").stdout.strip().lower()
    before = storage.load_events(execution_id)
    assert [event.event_type for event in before].count(PROMOTION_COMPLETED) == 1

    recovered = service.promote(execution_id)

    after = storage.load_events(execution_id)
    assert recovered.current_state is ExecutionState.COMPLETED
    assert recovered.promotion_commit_sha == effect_sha
    assert [event.event_type for event in after].count(PROMOTION_COMPLETED) == 1


def test_promotion_requires_explicit_approval_even_after_full_suite(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path, human_approval=False)
    storage = AtomicFileStateStorage(fixture.repository)
    execution_id = "exec-f37-approval-required"
    service, _ = _service(fixture, storage, execution_id)
    service.start(
        fixture.artifact,
        execution_id=execution_id,
        initial_input={},
        configuration={},
    )
    worktree = fixture.worktrees.create_worktree(
        execution_id,
        expected_base_commit_sha=fixture.base_sha,
    )
    (worktree.worktree_path / "tracked.txt").write_text(
        "candidate\n",
        encoding="utf-8",
    )
    service.prepare_candidate(execution_id)
    service.verify(execution_id)

    with pytest.raises(PromotionApprovalRequiredError, match="content-bound"):
        service.promote(execution_id)

    record = storage.load_execution(execution_id)
    assert record.current_state is ExecutionState.VERIFYING
    assert record.approval_status is ApprovalStatus.NOT_REQUIRED
    assert record.promotion_commit_sha is None
    assert _git(fixture.repository, "rev-parse", "HEAD").stdout.strip().lower() == (
        fixture.base_sha
    )


def test_workflow_node_approval_alone_never_authorizes_promotion(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    storage = AtomicFileStateStorage(fixture.repository)
    execution_id = "exec-f56-node-approval-only"
    service, _, _ = _approved_candidate(fixture, storage, execution_id)
    service.verify(execution_id)

    assert storage.load_execution(execution_id).approval_status is ApprovalStatus.APPROVED
    with pytest.raises(PromotionApprovalRequiredError, match="content-bound"):
        service.promote(execution_id)

    assert _git(fixture.repository, "rev-parse", "HEAD").stdout.strip().lower() == (
        fixture.base_sha
    )


def test_candidate_change_invalidates_approval_before_any_git_effect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path)
    storage = AtomicFileStateStorage(fixture.repository)
    execution_id = "exec-f56-candidate-mismatch"
    service, manager, original = _approved_candidate(fixture, storage, execution_id)
    service.verify(execution_id)
    _approve_exact_candidate(service, execution_id)
    mutating_operations = _record_mutating_git_operations(manager, monkeypatch)
    worktree = fixture.worktrees.load_worktree(execution_id)
    (worktree.worktree_path / "tracked.txt").write_text(
        "candidate-v2\n",
        encoding="utf-8",
    )
    changed = service.prepare_candidate(execution_id, message="feat: changed candidate")

    assert changed.candidate_commit_sha != original.candidate_commit_sha
    with pytest.raises(PromotionApprovalRequiredError, match="identity changed"):
        service.promote(execution_id)

    request = ApprovalManager(fixture.repository).load(execution_id)
    assert request is not None
    assert request.status is ApprovalStatus.INVALIDATED
    assert storage.load_execution(execution_id).approval_status is ApprovalStatus.INVALIDATED
    assert PROMOTION_APPROVAL_INVALIDATED in {
        event.event_type for event in storage.load_events(execution_id)
    }
    assert mutating_operations == []
    assert _git(fixture.repository, "rev-parse", "HEAD").stdout.strip().lower() == (
        fixture.base_sha
    )


def test_changed_gate_binding_invalidates_prior_decision_before_promotion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path)
    storage = AtomicFileStateStorage(fixture.repository)
    execution_id = "exec-f56-gate-mismatch"
    service, manager, _ = _approved_candidate(fixture, storage, execution_id)
    service.verify(execution_id)
    _approve_exact_candidate(service, execution_id)
    current_content = service._current_promotion_approval_content

    def changed_gate_content(**kwargs) -> ApprovalContent:  # type: ignore[no-untyped-def]
        content = current_content(**kwargs)
        first = content.gate_results[0]
        changed = ApprovalGateResult(
            gate_id=first.gate_id,
            required=first.required,
            status=first.status,
            result_digest="sha256:" + "f" * 64,
        )
        return ApprovalContent.model_validate(
            {
                **content.model_dump(mode="python"),
                "gate_results": (changed, *content.gate_results[1:]),
            }
        )

    monkeypatch.setattr(
        service,
        "_current_promotion_approval_content",
        changed_gate_content,
    )
    mutating_operations = _record_mutating_git_operations(manager, monkeypatch)

    with pytest.raises(PromotionApprovalRequiredError, match="content changed"):
        service.promote(execution_id)

    request = ApprovalManager(fixture.repository).load(execution_id)
    assert request is not None
    assert request.status is ApprovalStatus.INVALIDATED
    assert mutating_operations == []
    assert _git(fixture.repository, "rev-parse", "HEAD").stdout.strip().lower() == (
        fixture.base_sha
    )


def test_expired_request_cannot_be_decided_or_promoted(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    storage = AtomicFileStateStorage(fixture.repository)
    execution_id = "exec-f56-expired"
    clock = _Clock()
    service, _, _ = _approved_candidate(
        fixture,
        storage,
        execution_id,
        clock=clock,
    )
    service.verify(execution_id)
    request = service.request_promotion_approval(
        execution_id,
        reason="Short-lived exact promotion request",
        expires_at=clock.current + timedelta(hours=1),
    )
    clock.advance(timedelta(hours=2))

    with pytest.raises(PromotionApprovalRequiredError, match="expired"):
        service.approve(execution_id, approver="late-reviewer")

    expired = ApprovalManager(fixture.repository).load(execution_id)
    assert expired is not None
    assert expired.subject_digest == request.subject_digest
    assert expired.status is ApprovalStatus.EXPIRED
    assert storage.load_execution(execution_id).approval_status is ApprovalStatus.EXPIRED
    assert _git(fixture.repository, "rev-parse", "HEAD").stdout.strip().lower() == (
        fixture.base_sha
    )


def test_approval_expiring_after_decision_blocks_promotion(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    storage = AtomicFileStateStorage(fixture.repository)
    execution_id = "exec-f56-expired-after-decision"
    clock = _Clock()
    service, _, _ = _approved_candidate(
        fixture,
        storage,
        execution_id,
        clock=clock,
    )
    service.verify(execution_id)
    service.request_promotion_approval(
        execution_id,
        reason="Decision expires before delayed promotion",
        expires_at=clock.current + timedelta(hours=1),
    )
    service.approve(execution_id, approver="reviewer-before-expiry")
    clock.advance(timedelta(hours=2))

    with pytest.raises(PromotionApprovalRequiredError, match="expired"):
        service.promote(execution_id)

    expired = ApprovalManager(fixture.repository).load(execution_id)
    assert expired is not None
    assert expired.status is ApprovalStatus.EXPIRED
    assert storage.load_execution(execution_id).approval_status is ApprovalStatus.EXPIRED
    assert _git(fixture.repository, "rev-parse", "HEAD").stdout.strip().lower() == (
        fixture.base_sha
    )


def test_tampered_approval_projection_blocks_before_git_effect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path)
    storage = AtomicFileStateStorage(fixture.repository)
    execution_id = "exec-f56-tampered-projection"
    service, manager, _ = _approved_candidate(fixture, storage, execution_id)
    service.verify(execution_id)
    _approve_exact_candidate(service, execution_id)
    mutating_operations = _record_mutating_git_operations(manager, monkeypatch)
    approval_path = (
        fixture.repository
        / ".harness"
        / "state"
        / "executions"
        / execution_id
        / "approval-request.json"
    )
    approval_path.write_text(
        approval_path.read_text(encoding="utf-8") + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ApprovalLifecycleIntegrityError, match="projection"):
        service.promote(execution_id)

    assert mutating_operations == []
    assert _git(fixture.repository, "rev-parse", "HEAD").stdout.strip().lower() == (
        fixture.base_sha
    )


def test_real_change_reaches_original_only_after_approval_and_full_suite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path)
    storage = AtomicFileStateStorage(fixture.repository)
    execution_id = "exec-f37-e2e"
    service, manager, candidate = _approved_candidate(
        fixture,
        storage,
        execution_id,
    )
    mutating_operations = _record_mutating_git_operations(manager, monkeypatch)

    assert candidate.candidate_commit_sha is not None
    assert _git(fixture.repository, "rev-parse", "HEAD").stdout.strip().lower() == (
        fixture.base_sha
    )
    suite = service.verify(execution_id)
    _approve_exact_candidate(service, execution_id)
    verified = storage.load_execution(execution_id)
    promoted = service.promote(execution_id)

    assert suite.all_passed is True
    assert suite.verified_commit_sha == candidate.candidate_commit_sha
    assert verified.current_state is ExecutionState.VERIFYING
    assert verified.approval_status is ApprovalStatus.APPROVED
    assert promoted.current_state is ExecutionState.COMPLETED
    assert promoted.promotion_commit_sha is not None
    assert mutating_operations == [("cherry-pick", candidate.candidate_commit_sha)]
    assert _git(fixture.repository, "rev-parse", "HEAD").stdout.strip().lower() == (
        promoted.promotion_commit_sha
    )
    assert (fixture.repository / "tracked.txt").read_text(encoding="utf-8") == (
        "candidate\n"
    )
    event_types = tuple(event.event_type for event in storage.load_events(execution_id))
    assert CANDIDATE_COMMIT_RECORDED in event_types
    assert PROMOTION_STARTED in event_types
    assert PROMOTION_COMPLETED in event_types
