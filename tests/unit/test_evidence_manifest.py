"""Focused F6.3 regressions for canonical terminal evidence."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from ai_engineering_harness.compiler import GraphCompiler
from ai_engineering_harness.contracts.events import EventType, ExecutionEvent
from ai_engineering_harness.contracts.evidence import (
    ApprovalEvidence,
    BudgetEvidence,
    EvidenceApplicability,
    EvidenceDigest,
    EvidenceFile,
    EvidenceManifest,
    GateEvidence,
    KnowledgeEvidence,
    PromotionEvidence,
)
from ai_engineering_harness.contracts.execution import (
    EXECUTION_RECORD_SCHEMA_VERSION,
    ApprovalStatus,
    ExecutionRecord,
    ExecutionState,
)
from ai_engineering_harness.observability import (
    EvidenceIntegrityError,
    EvidenceManifestManager,
)
from ai_engineering_harness.persistence import (
    AtomicFileStateStorage,
    EvidenceManifestIntegrityError,
    EvidenceManifestNotFoundError,
    ExecutionBundle,
    canonical_json_digest,
    canonical_json_object,
)
from ai_engineering_harness.runtime import EventSourcedStateMachine
from ai_engineering_harness.runtime.maf_adapter import MAFAdapter


class _Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 8, 15, 18, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        self.value += timedelta(seconds=1)
        return self.value


class _Ids:
    def __init__(self) -> None:
        self.value = 0

    def __call__(self) -> str:
        self.value += 1
        return f"evidence-event-{self.value}"


def _contract_manifest() -> EvidenceManifest:
    return EvidenceManifest(
        execution_id="exec-evidence-contract",
        final_result="VERIFIED",
        base_commit_sha="a" * 40,
        promotion=PromotionEvidence(
            status=EvidenceApplicability.NOT_APPLICABLE,
            reason="promotion_manager_not_used",
        ),
        artifact_digest="sha256:" + "1" * 64,
        configuration_digest="sha256:" + "2" * 64,
        plan=EvidenceDigest(
            status=EvidenceApplicability.NOT_APPLICABLE,
            reason="plan_not_generated",
        ),
        context=EvidenceDigest(
            status=EvidenceApplicability.NOT_APPLICABLE,
            reason="context_policy_not_used",
        ),
        diff=EvidenceDigest(
            status=EvidenceApplicability.NOT_APPLICABLE,
            reason="promotion_not_performed",
        ),
        gates=(
            GateEvidence(
                gate_id="unit_test",
                required=True,
                status="PASSED",
                result_digest="sha256:" + "3" * 64,
            ),
        ),
        approval=ApprovalEvidence(
            status=ApprovalStatus.NOT_REQUIRED,
            reason="approval_not_required",
        ),
        models=(),
        budget=BudgetEvidence(
            status=EvidenceApplicability.NOT_APPLICABLE,
            reason="budget_boundary_not_used",
        ),
        knowledge=KnowledgeEvidence(
            status=EvidenceApplicability.NOT_APPLICABLE,
            reason="knowledge_sync_not_run",
        ),
        journal_final_hash="4" * 64,
        journal_final_sequence=7,
        files=(
            EvidenceFile(
                path=(
                    ".harness/artifacts/executions/exec-evidence-contract/"
                    "artifact.json"
                ),
                digest="sha256:" + "5" * 64,
                size_bytes=10,
            ),
        ),
    )


def _artifact(project_root: Path):
    spec = project_root / "evidence.yaml"
    spec.write_text(
        """graph:
  name: evidence-rich
  graph_schema_version: "1.0"
  definition_version: "1.0.0"
  entrypoint: execute
  status: stable
nodes:
  - id: execute
    type: deterministic
    executor: deterministic_gate
    gate_name: evidence
    on_success: completed
    on_failure: failed
terminal_states:
  - id: completed
    outcome: success
  - id: failed
    outcome: failure
policies: []
contracts: []
""",
        encoding="utf-8",
    )
    return MAFAdapter.load_and_validate(
        GraphCompiler(project_root).compile_graph(spec, "evidence-rich")
    )


def _append(
    storage: AtomicFileStateStorage,
    execution_id: str,
    event_type: str,
    details: dict[str, object],
    *,
    clock: _Clock,
    ids: _Ids,
    lock,
    node_id: str | None = None,
    attempt: int = 0,
) -> ExecutionEvent:
    return storage.append_event(
        execution_id,
        ExecutionEvent(
            event_id=ids(),
            execution_id=execution_id,
            sequence_number=0,
            event_type=EventType(event_type),
            timestamp=clock(),
            graph_name="evidence-rich",
            node_id=node_id,
            attempt=attempt,
            actor="evidence-test",
            details=details,
        ),
        lock=lock,
    )


def _rich_promoted_execution(
    project_root: Path,
    *,
    observable_canary: str | None = None,
) -> tuple[AtomicFileStateStorage, EvidenceManifestManager, EvidenceManifest]:
    execution_id = "exec-evidence-rich"
    artifact = _artifact(project_root)
    artifact_json = artifact.canonical_json()
    configuration_json = canonical_json_object({})
    initial_input = {"intent": "prove evidence"}
    initial_json = canonical_json_object(initial_input)
    storage = AtomicFileStateStorage(project_root)
    storage.create_execution_bundle(
        ExecutionBundle(
            bundle_schema_version="1.0",
            execution_id=execution_id,
            artifact_digest=canonical_json_digest(artifact_json),
            configuration_digest=canonical_json_digest(configuration_json),
            initial_input_digest=canonical_json_digest(initial_json),
            artifact_json=artifact_json,
            configuration_json=configuration_json,
        ),
        initial_input=initial_input,
    )
    clock = _Clock()
    ids = _Ids()
    record = ExecutionRecord(
        record_schema_version=EXECUTION_RECORD_SCHEMA_VERSION,
        revision=0,
        execution_id=execution_id,
        workflow_name="evidence-rich",
        artifact_digest=canonical_json_digest(artifact_json),
        base_commit_sha="a" * 40,
        original_branch="main",
        worktree_path=None,
        current_node_id="execute",
        current_state=ExecutionState.INITIATED,
        attempt_by_node={},
        created_at=clock(),
        updated_at=clock(),
        configuration_digest=canonical_json_digest(configuration_json),
        approval_status=ApprovalStatus.APPROVED,
        candidate_commit_sha="c" * 40,
        promotion_commit_sha="d" * 40,
        failure=None,
    )
    storage.create_execution(record)
    manager = EvidenceManifestManager(project_root, storage)
    lock = storage.acquire_execution_lock(execution_id, "evidence-test-owner", timeout_seconds=1)
    try:
        machine = EventSourcedStateMachine(
            storage,
            execution_id,
            clock=clock,
            event_id_factory=ids,
            owner_id_factory=lambda: "unused-owner",
            completed_transition_handler=manager.ensure_terminal_manifest,
            lock=lock,
        )
        machine.transition_to(
            ExecutionState.EXECUTING,
            node_id="execute",
            attempt=1,
            reason="execution_started",
            lock=lock,
        )
        machine.transition_to(
            ExecutionState.VERIFYING,
            node_id="execute",
            attempt=1,
            reason="execution_succeeded",
            lock=lock,
        )
        context_digest = storage.store_payload(
            execution_id,
            {"context": "bounded"},
            lock=lock,
        )
        plan_digest = storage.store_payload(
            execution_id,
            {"plan": "verified"},
            lock=lock,
        )
        gate_digest = storage.store_payload(
            execution_id,
            {"gate_id": "unit_test", "status": "PASSED"},
            lock=lock,
        )
        _append(
            storage,
            execution_id,
            "CONTEXT_EVALUATED",
            {"outcome": "sufficient", "payload_digest": context_digest},
            clock=clock,
            ids=ids,
            lock=lock,
        )
        _append(
            storage,
            execution_id,
            "PLAN_GENERATED",
            {
                "plan_digest": plan_digest,
                "provider": observable_canary or "openai",
                "model_name": "planning-model",
            },
            clock=clock,
            ids=ids,
            lock=lock,
        )
        _append(
            storage,
            execution_id,
            "NODE_COMPLETED",
            {
                "model_calls": [
                    {
                        "provider_id": "local",
                        "model_name": "execution-model",
                    }
                ]
            },
            clock=clock,
            ids=ids,
            lock=lock,
            node_id="execute",
            attempt=1,
        )
        _append(
            storage,
            execution_id,
            "BUDGET_COMMITTED",
            {
                "actual": {
                    "prompt_tokens": 2,
                    "completion_tokens": 3,
                    "total_tokens": 5,
                    "tool_calls": 1,
                    "duration_ms": 7,
                    "attempts": 1,
                    "estimated_cost_usd": "0.25",
                    "unpriced_operations": 0,
                }
            },
            clock=clock,
            ids=ids,
            lock=lock,
            node_id="execute",
            attempt=1,
        )
        _append(
            storage,
            execution_id,
            "VERIFICATION_GATE_RECORDED",
            {
                "gate_id": "unit_test",
                "required": True,
                "status": "PASSED",
                "result_digest": gate_digest,
            },
            clock=clock,
            ids=ids,
            lock=lock,
        )
        _append(
            storage,
            execution_id,
            "VERIFICATION_SUITE_RECORDED",
            {"all_passed": True, "gate_result_digests": [gate_digest]},
            clock=clock,
            ids=ids,
            lock=lock,
        )
        diff_digest = "sha256:" + "6" * 64
        subject_digest = "sha256:" + "7" * 64
        _append(
            storage,
            execution_id,
            "PROMOTION_APPROVAL_REQUESTED",
            {"request": {"diff_digest": diff_digest, "subject_digest": subject_digest}},
            clock=clock,
            ids=ids,
            lock=lock,
        )
        _append(
            storage,
            execution_id,
            "PROMOTION_APPROVED",
            {"request": {"subject_digest": subject_digest}},
            clock=clock,
            ids=ids,
            lock=lock,
        )
        _append(
            storage,
            execution_id,
            "KNOWLEDGE_SYNC",
            {"tx_id": observable_canary or "knowledge-tx-1", "status": "COMMITTED"},
            clock=clock,
            ids=ids,
            lock=lock,
        )
        machine.transition_to(
            ExecutionState.PROMOTING,
            node_id="execute",
            attempt=0,
            reason="promotion_started",
            lock=lock,
        )
        machine.transition_to(
            ExecutionState.GENERATING_EVIDENCE,
            node_id="execute",
            attempt=0,
            reason="evidence_generation_started",
            lock=lock,
        )
        machine.transition_to(
            ExecutionState.COMPLETED,
            node_id="execute",
            attempt=0,
            reason="promotion_completed",
            lock=lock,
        )
    finally:
        storage.release_execution_lock(lock)
    return storage, manager, manager.load_and_verify(execution_id)


def test_contract_is_canonical_strict_and_omits_ambiguous_nulls() -> None:
    manifest = _contract_manifest()
    raw = manifest.canonical_json()

    assert EvidenceManifest.model_validate_json(raw) == manifest
    assert "null" not in raw
    assert raw.endswith("\n")
    assert raw == manifest.canonical_json()

    with pytest.raises(ValidationError, match="canonical POSIX-relative"):
        EvidenceFile(
            path="../escape.json",
            digest="sha256:" + "8" * 64,
            size_bytes=1,
        )
    with pytest.raises(ValidationError, match="verified result cannot claim"):
        EvidenceManifest.model_validate(
            {
                **manifest.model_dump(mode="python"),
                "promotion": PromotionEvidence(
                    status=EvidenceApplicability.RECORDED,
                    commit_sha="b" * 40,
                ),
            }
        )
    with pytest.raises(ValidationError, match="reason"):
        EvidenceDigest.model_validate(
            {"status": "NOT_APPLICABLE", "reason": "unknown_reason"}
        )
    with pytest.raises(ValidationError, match="identities must be unique"):
        EvidenceManifest.model_validate(
            {
                **manifest.model_dump(mode="python"),
                "gates": (manifest.gates[0], manifest.gates[0]),
            }
        )


def test_rich_promoted_manifest_records_every_required_dimension(tmp_path: Path) -> None:
    storage, manager, manifest = _rich_promoted_execution(tmp_path)

    assert manifest.final_result == "PROMOTED"
    assert manifest.promotion.commit_sha == "d" * 40
    assert manifest.plan.status is EvidenceApplicability.RECORDED
    assert manifest.context.status is EvidenceApplicability.RECORDED
    assert manifest.diff.digest == "sha256:" + "6" * 64
    assert manifest.gates[0].status == "PASSED"
    assert manifest.approval.status is ApprovalStatus.APPROVED
    assert [(item.provider, item.model) for item in manifest.models] == [
        ("local", "execution-model"),
        ("openai", "planning-model"),
    ]
    assert manifest.budget.total_tokens == 5
    assert manifest.budget.estimated_cost_usd == "0.25"
    assert manifest.knowledge.transaction_status == "COMMITTED"
    assert manifest.journal_final_sequence == len(storage.load_events(manifest.execution_id))
    assert manager.load_and_verify(manifest.execution_id) == manifest
    assert storage.publish_evidence_manifest(manifest) == manifest

    divergent = manifest.model_copy(update={"journal_final_hash": "9" * 64})
    with pytest.raises(EvidenceManifestIntegrityError, match="diverges"):
        storage.publish_evidence_manifest(divergent)


def test_manifest_and_referenced_file_tampering_fail_closed(tmp_path: Path) -> None:
    storage, manager, manifest = _rich_promoted_execution(tmp_path)
    evidence_path = (
        tmp_path
        / ".harness"
        / "state"
        / "executions"
        / manifest.execution_id
        / "evidence.json"
    )
    evidence_path.write_text(evidence_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(EvidenceManifestIntegrityError, match="invalid|canonical"):
        storage.load_evidence_manifest(manifest.execution_id)

    other_root = tmp_path / "referenced-file"
    other_root.mkdir()
    storage, manager, manifest = _rich_promoted_execution(other_root)
    recorded_payload = next(
        item
        for item in manifest.files
        if manifest.plan.digest is not None
        and item.path.endswith(f"{manifest.plan.digest.removeprefix('sha256:')}.json")
    )
    (other_root / recorded_payload.path).write_text('{"tampered":true}\n', encoding="utf-8")
    with pytest.raises(EvidenceIntegrityError, match="diverges"):
        manager.load_and_verify(manifest.execution_id)


def test_manifest_absence_recovery_and_ambiguous_temps_fail_closed(tmp_path: Path) -> None:
    storage, _, manifest = _rich_promoted_execution(tmp_path)
    evidence_path = (
        tmp_path
        / ".harness"
        / "state"
        / "executions"
        / manifest.execution_id
        / "evidence.json"
    )
    exact = evidence_path.read_bytes()
    evidence_path.unlink()
    with pytest.raises(EvidenceManifestNotFoundError, match="does not exist"):
        storage.load_evidence_manifest(manifest.execution_id)

    recovered_temp = evidence_path.with_name(".evidence.json.interrupted.tmp")
    recovered_temp.write_bytes(exact)
    assert storage.load_evidence_manifest(manifest.execution_id) == manifest
    assert evidence_path.read_bytes() == exact
    assert not recovered_temp.exists()

    evidence_path.unlink()
    evidence_path.with_name(".evidence.json.first.tmp").write_bytes(exact)
    evidence_path.with_name(".evidence.json.second.tmp").write_bytes(exact)
    with pytest.raises(EvidenceManifestIntegrityError, match="multiple abandoned"):
        storage.load_evidence_manifest(manifest.execution_id)
    assert not evidence_path.exists()


def test_journal_anchor_and_missing_reference_fail_closed(tmp_path: Path) -> None:
    anchor_root = tmp_path / "anchor"
    anchor_root.mkdir()
    _, manager, manifest = _rich_promoted_execution(anchor_root)
    evidence_path = (
        anchor_root
        / ".harness"
        / "state"
        / "executions"
        / manifest.execution_id
        / "evidence.json"
    )
    evidence_path.write_bytes(
        manifest.model_copy(update={"journal_final_hash": "9" * 64})
        .canonical_json()
        .encode("utf-8")
    )
    with pytest.raises(EvidenceIntegrityError, match="journal hash"):
        manager.load_and_verify(manifest.execution_id)

    reference_root = tmp_path / "reference"
    reference_root.mkdir()
    _, manager, manifest = _rich_promoted_execution(reference_root)
    assert manifest.plan.digest is not None
    plan_path = next(
        reference_root / item.path
        for item in manifest.files
        if item.path.endswith(f"{manifest.plan.digest.removeprefix('sha256:')}.json")
    )
    plan_path.unlink()
    with pytest.raises(EvidenceIntegrityError, match="no referenced immutable payload"):
        manager.load_and_verify(manifest.execution_id)


def test_reparse_and_toctou_file_evidence_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reparse_root = tmp_path / "reparse"
    reparse_root.mkdir()
    _, manager, manifest = _rich_promoted_execution(reparse_root)
    target = reparse_root / manifest.files[0].path
    real_lstat = os.lstat

    def reparse_lstat(path: os.PathLike[str] | str):
        metadata = real_lstat(path)
        if Path(path) == target:
            return SimpleNamespace(
                st_mode=metadata.st_mode,
                st_file_attributes=0x400,
            )
        return metadata

    monkeypatch.setattr(os, "lstat", reparse_lstat)
    with pytest.raises(EvidenceIntegrityError, match="symlink or reparse"):
        manager.load_and_verify(manifest.execution_id)
    monkeypatch.undo()

    race_root = tmp_path / "race"
    race_root.mkdir()
    _, manager, manifest = _rich_promoted_execution(race_root)
    target = race_root / manifest.files[0].path
    real_stat = Path.stat
    target_calls = 0

    def racing_stat(path: Path, *args, **kwargs):
        nonlocal target_calls
        metadata = real_stat(path, *args, **kwargs)
        if path != target or kwargs.get("follow_symlinks") is not False:
            return metadata
        target_calls += 1
        if target_calls < 3:
            return metadata
        return SimpleNamespace(
            st_dev=metadata.st_dev,
            st_ino=metadata.st_ino,
            st_mode=metadata.st_mode,
            st_size=metadata.st_size,
            st_mtime_ns=metadata.st_mtime_ns + 1,
        )

    monkeypatch.setattr(Path, "stat", racing_stat)
    with pytest.raises(EvidenceIntegrityError, match="changed while being hashed"):
        manager.load_and_verify(manifest.execution_id)


def test_observable_secret_canary_is_redacted_from_manifest_bytes(tmp_path: Path) -> None:
    canary = "sk-" + "Z" * 40
    _, _, manifest = _rich_promoted_execution(
        tmp_path,
        observable_canary=canary,
    )
    raw = manifest.canonical_json()

    assert canary not in raw
    assert canary not in repr(manifest)
    assert "[REDACTED_SECRET]" in raw
