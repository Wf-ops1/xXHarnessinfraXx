"""Testes unitários para a Fase 7 (Knowledge Transaction, Audit Trail e Rollback)."""

import json
from pathlib import Path

import pytest

from ai_engineering_harness.artifacts.generator import ArtifactGenerator
from ai_engineering_harness.cli.commands.rollback import RollbackManager
from ai_engineering_harness.knowledge.transaction import KnowledgeTransactionManager, TransactionState
from ai_engineering_harness.observability.audit import AuditTrailManager
from ai_engineering_harness.runtime import RollbackPrerequisiteError
from ai_engineering_harness.security import TrustAuthorization, TrustBoundaryEvaluator


def test_knowledge_transaction_5_steps(tmp_path: Path):
    mgr = KnowledgeTransactionManager(project_root=tmp_path)
    state = mgr.execute_transaction("tx-123", {"id": "ki-auth", "content": "ADR Auth"})
    assert state == TransactionState.COMMITTED.value

    current_file = tmp_path / ".harness" / "knowledge" / "current.json"
    assert current_file.is_file()
    data = json.loads(current_file.read_text(encoding="utf-8"))
    assert data["current_tx_id"] == "tx-123"

def test_audit_trail_linear_hash_chain(tmp_path: Path):
    audit = AuditTrailManager(project_root=tmp_path, execution_id="exec-hash-1")
    audit.log_event("STEP_1", {"action": "create"})
    audit.log_event("STEP_2", {"action": "update"})

    is_valid, msg = audit.verify_integrity()
    assert is_valid is True
    assert "100% verificada" in msg

def test_audit_trail_tamper_detection(tmp_path: Path):
    audit = AuditTrailManager(project_root=tmp_path, execution_id="exec-hash-2")
    audit.log_event("STEP_1", {"action": "create"})
    audit.log_event("STEP_2", {"action": "update"})

    # Adulterar arquivo manualmente
    journal_file = tmp_path / ".harness" / "state" / "executions" / "exec-hash-2" / "event-journal.jsonl"
    text = journal_file.read_text(encoding="utf-8")
    tampered_text = text.replace("create", "hack_create")
    journal_file.write_text(tampered_text, encoding="utf-8")

    # Audit deve detectar a alteração!
    is_valid, msg = audit.verify_integrity()
    assert is_valid is False
    assert "Adulteração detectada" in msg or "Quebra de corrente" in msg

def test_destructive_rollback_requires_approval(tmp_path: Path):
    harness_dir = tmp_path / ".harness"
    harness_dir.mkdir()
    (harness_dir / "trusted_repository").touch()
    boundary = TrustBoundaryEvaluator(
        tmp_path,
        authorization=TrustAuthorization(
            repository_root=str(tmp_path.resolve()),
            executable_aliases=("git",),
            hook_ids=("rollback-compensation",),
        ),
    ).evaluate()
    calls: list[str] = []
    mgr = RollbackManager(
        project_root=tmp_path,
        trust_boundary=boundary,
        compensation_hook=lambda result: calls.append(result.promotion_commit_sha),
        hook_id="rollback-compensation",
        hook_destructive=True,
    )

    with pytest.raises(RollbackPrerequisiteError, match="not explicitly authorized"):
        mgr.rollback(
            promotion_commit_sha="a" * 40,
            original_branch="main",
        )

    assert calls == []


def test_restricted_rollback_denies_hook_before_adapter_effect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del monkeypatch
    calls: list[str] = []
    manager = RollbackManager(
        project_root=tmp_path,
        compensation_hook=lambda result: calls.append(result.promotion_commit_sha),
        hook_id="rollback-compensation",
    )

    with pytest.raises(RollbackPrerequisiteError, match="not explicitly authorized"):
        manager.rollback(
            promotion_commit_sha="a" * 40,
            original_branch="main",
        )

    assert calls == []

def test_artifact_generator_latest(tmp_path: Path):
    gen = ArtifactGenerator(project_root=tmp_path)
    path = gen.generate_latest_report("exec-art-1", {"status": "SUCCESS"})
    assert path.is_file()
    assert path.name == "latest.json"
