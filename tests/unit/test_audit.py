"""F6.2 canonical audit journal, checkpoint, export, and concurrency tests."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from pathlib import Path
from typing import Any

import pytest

from ai_engineering_harness.contracts.events import ExecutionEvent
from ai_engineering_harness.contracts.execution import (
    EXECUTION_RECORD_SCHEMA_VERSION,
    ApprovalStatus,
    ExecutionRecord,
    ExecutionState,
)
from ai_engineering_harness.observability import (
    AuditCheckpoint,
    AuditConfigurationError,
    AuditIntegrityError,
    AuditTrailManager,
    AuditWriteError,
)
from ai_engineering_harness.persistence import AtomicFileStateStorage

_CREATED_AT = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)
_ARTIFACT_DIGEST = f"sha256:{'a' * 64}"
_CONFIGURATION_DIGEST = f"sha256:{'b' * 64}"
_BASE_SHA = "c" * 40
_WORKFLOW = "audit-workflow"


def _record(execution_id: str) -> ExecutionRecord:
    return ExecutionRecord(
        record_schema_version=EXECUTION_RECORD_SCHEMA_VERSION,
        revision=0,
        execution_id=execution_id,
        workflow_name=_WORKFLOW,
        artifact_digest=_ARTIFACT_DIGEST,
        base_commit_sha=_BASE_SHA,
        original_branch="main",
        worktree_path=None,
        current_node_id="audit",
        current_state=ExecutionState.INITIATED,
        attempt_by_node={"audit": 0},
        created_at=_CREATED_AT,
        updated_at=_CREATED_AT,
        configuration_digest=_CONFIGURATION_DIGEST,
        approval_status=ApprovalStatus.NOT_REQUIRED,
        candidate_commit_sha=None,
        promotion_commit_sha=None,
        failure=None,
    )


def _draft(
    event_id: str,
    execution_id: str,
    *,
    event_type: str = "EXECUTION_CREATED",
    timestamp_offset: int = 0,
) -> ExecutionEvent:
    return ExecutionEvent.model_validate(
        {
            "event_id": event_id,
            "execution_id": execution_id,
            "sequence_number": 0,
            "event_type": event_type,
            "timestamp": _CREATED_AT + timedelta(seconds=timestamp_offset),
            "graph_name": _WORKFLOW,
            "node_id": None,
            "attempt": 0,
            "actor": "audit-test",
            "details": {"event_id": event_id, "status": "recorded"},
            "previous_hash": None,
            "current_hash": None,
        }
    )


def _manager(root: Path, execution_id: str = "exec-audit") -> AuditTrailManager:
    AtomicFileStateStorage(root).create_execution(_record(execution_id))
    return AuditTrailManager(root, execution_id)


def _canonical_line(document: dict[str, object]) -> bytes:
    return (
        json.dumps(
            document,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def test_audit_uses_only_canonical_execution_events_and_exact_identity(
    tmp_path: Path,
) -> None:
    execution_id = "exec-audit-identity"
    manager = _manager(tmp_path, execution_id)

    first = manager.log_event(_draft("audit-event-1", execution_id))
    second = manager.append_event(
        _draft(
            "audit-event-2",
            execution_id,
            event_type="EXECUTION_COMPLETED",
            timestamp_offset=1,
        )
    )

    assert manager.execution_id == execution_id
    assert [first.sequence_number, second.sequence_number] == [1, 2]
    assert first.previous_hash == "0" * 64
    assert second.previous_hash == first.current_hash
    assert manager.load_events() == (first, second)
    valid, message = manager.verify_integrity()
    assert valid is True
    assert "2 evento(s)" in message
    assert "tamper-evident local" in message

    raw_events = [
        json.loads(line)
        for line in manager.journal_file.read_text(encoding="utf-8").splitlines()
    ]
    assert all(set(document) == set(ExecutionEvent.model_fields) for document in raw_events)
    assert all(document["execution_id"] == execution_id for document in raw_events)
    assert all("payload" not in document for document in raw_events)

    json_export = json.loads(manager.export_json())
    assert json_export["execution_id"] == execution_id
    assert json_export["total_events"] == 2
    assert json_export["events"] == raw_events
    assert json_export["integrity"]["checkpoint"]["protection"] == "tamper-evident-local"

    sarif_export = json.loads(manager.export_sarif())
    run = sarif_export["runs"][0]
    assert run["automationDetails"]["id"] == execution_id
    assert run["properties"]["execution_id"] == execution_id
    assert all(
        result["properties"]["execution_id"] == execution_id
        for result in run["results"]
    )
    assert all(
        result["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]
        == f".harness/state/executions/{execution_id}/event-journal.jsonl"
        for result in run["results"]
    )


def test_legacy_parallel_envelope_is_rejected(tmp_path: Path) -> None:
    manager = _manager(tmp_path, "exec-audit-legacy")

    with pytest.raises(TypeError):
        manager.log_event("STEP_1", {"action": "create"})  # type: ignore[call-arg]
    with pytest.raises(AuditWriteError, match="canonical ExecutionEvent"):
        manager.log_event({"event_type": "STEP_1"})  # type: ignore[arg-type]
    assert not manager.journal_file.exists()


def test_missing_execution_fails_without_creating_state(tmp_path: Path) -> None:
    manager = AuditTrailManager(tmp_path, "exec-audit-missing")

    with pytest.raises(AuditIntegrityError, match="exec-audit-missing") as raised:
        manager.load_events()

    assert raised.value.execution_id == "exec-audit-missing"
    assert not manager.exec_dir.exists()


def test_invalid_journal_error_does_not_echo_raw_secret_content(tmp_path: Path) -> None:
    execution_id = "exec-audit-invalid-secret"
    manager = _manager(tmp_path, execution_id)
    raw_secret = "audit-invalid-secret-value"
    manager.journal_file.write_bytes(
        f'{{"password":"{raw_secret}",'.encode() + b"\n"
    )

    with pytest.raises(AuditIntegrityError, match="line 1 is invalid") as raised:
        manager.load_events()

    assert "schema or JSON validation failed" in str(raised.value)
    assert raw_secret not in str(raised.value)


@pytest.mark.parametrize(
    ("corruption", "expected"),
    [
        ("truncated", "complete LF-terminated lines"),
        ("invalid-json", "line 1 is invalid"),
        ("invalid-schema", "line 1 is invalid"),
        ("hash", "hash chain is invalid at line 1"),
        ("gap", "sequence is invalid at line 1"),
        ("duplicate-sequence", "sequence is invalid at line 2"),
        ("duplicate-event-id", "duplicate event_id"),
    ],
)
def test_corrupt_journal_raises_typed_error_without_mutation(
    tmp_path: Path,
    corruption: str,
    expected: str,
) -> None:
    execution_id = f"exec-audit-corrupt-{corruption}"
    manager = _manager(tmp_path, execution_id)
    manager.append_event(_draft(f"{corruption}-event-1", execution_id))
    manager.append_event(
        _draft(
            f"{corruption}-event-2",
            execution_id,
            event_type="EXECUTION_COMPLETED",
            timestamp_offset=1,
        )
    )
    documents = [
        json.loads(line)
        for line in manager.journal_file.read_text(encoding="utf-8").splitlines()
    ]

    if corruption == "truncated":
        corrupted = manager.journal_file.read_bytes()[:-1]
    elif corruption == "invalid-json":
        corrupted = b"{broken\n"
    else:
        if corruption == "invalid-schema":
            documents[0].pop("actor")
        elif corruption == "hash":
            documents[0]["current_hash"] = "f" * 64
        elif corruption == "gap":
            documents[0]["sequence_number"] = 2
        elif corruption == "duplicate-sequence":
            documents[1]["sequence_number"] = 1
        elif corruption == "duplicate-event-id":
            documents[1]["event_id"] = documents[0]["event_id"]
        corrupted = b"".join(_canonical_line(document) for document in documents)
    manager.journal_file.write_bytes(corrupted)
    before = manager.journal_file.read_bytes()

    with pytest.raises(AuditIntegrityError, match=expected) as raised:
        manager.load_events()

    assert raised.value.execution_id == execution_id
    assert manager.journal_file.read_bytes() == before
    with pytest.raises(AuditIntegrityError):
        manager.export_json()
    with pytest.raises(AuditIntegrityError):
        manager.export_sarif()
    assert manager.journal_file.read_bytes() == before


def test_concurrent_managers_produce_contiguous_monotonic_sequence_20_of_20(
    tmp_path: Path,
) -> None:
    execution_id = "exec-audit-concurrent"
    AtomicFileStateStorage(tmp_path).create_execution(_record(execution_id))

    for round_number in range(20):
        drafts = [
            _draft(
                f"audit-r{round_number:02d}-e{worker}",
                execution_id,
                timestamp_offset=round_number * 4 + worker,
            )
            for worker in range(4)
        ]
        with ThreadPoolExecutor(max_workers=4) as executor:
            persisted = tuple(
                executor.map(
                    lambda draft: AuditTrailManager(
                        tmp_path,
                        execution_id,
                    ).append_event(draft),
                    drafts,
                )
            )
        assert len({event.sequence_number for event in persisted}) == 4
        events = AuditTrailManager(tmp_path, execution_id).load_events()
        assert [event.sequence_number for event in events] == list(
            range(1, (round_number + 1) * 4 + 1)
        )
        assert len({event.event_id for event in events}) == len(events)
        assert all(
            current.previous_hash == previous.current_hash
            for previous, current in pairwise(events)
        )


def test_unsigned_and_hmac_checkpoints_fail_closed_without_secret_exposure(
    tmp_path: Path,
) -> None:
    execution_id = "exec-audit-checkpoint"
    manager = _manager(tmp_path, execution_id)
    manager.append_event(_draft("audit-checkpoint-1", execution_id))

    unsigned = manager.create_checkpoint()
    assert unsigned.protection == "tamper-evident-local"
    assert unsigned.hmac_sha256 is None
    manager.verify_checkpoint(unsigned)
    manager.verify_checkpoint(unsigned.to_dict())

    secret_key = b"audit-test-secret-key-material-32b"
    signed_manager = AuditTrailManager(tmp_path, execution_id, hmac_key=secret_key)
    signed = signed_manager.create_checkpoint()
    assert signed.protection == "hmac-sha256"
    assert signed.hmac_sha256 is not None
    assert signed.hmac_sha256.startswith("sha256:")
    signed_manager.verify_checkpoint(signed)
    signed_manager.verify_checkpoint(AuditCheckpoint.from_mapping(signed.to_dict()))

    wrong_key_manager = AuditTrailManager(
        tmp_path,
        execution_id,
        hmac_key=b"wrong-audit-key-material-exactly-32",
    )
    with pytest.raises(AuditIntegrityError, match="HMAC verification failed") as raised:
        wrong_key_manager.verify_checkpoint(signed)
    assert secret_key.decode("ascii") not in str(raised.value)

    tampered = signed.to_dict()
    tampered["total_events"] = 2
    tampered["last_sequence_number"] = 2
    with pytest.raises(AuditIntegrityError, match="does not match"):
        signed_manager.verify_checkpoint(tampered)

    observable = repr(signed_manager) + signed_manager.export_json() + signed_manager.export_sarif()
    assert secret_key.decode("ascii") not in observable


@pytest.mark.parametrize("key", [b"", b"short", bytearray(b"x" * 32)])
def test_invalid_hmac_configuration_is_rejected(tmp_path: Path, key: Any) -> None:
    with pytest.raises(AuditConfigurationError, match="at least 32 bytes"):
        AuditTrailManager(tmp_path, "exec-audit-key", hmac_key=key)


def test_checkpoint_mapping_validation_is_strict(tmp_path: Path) -> None:
    manager = _manager(tmp_path, "exec-audit-mapping")
    checkpoint = manager.create_checkpoint().to_dict()
    checkpoint["extra"] = True

    with pytest.raises(AuditIntegrityError, match="fields are invalid"):
        manager.verify_checkpoint(checkpoint)

    invalid_dataclass = AuditCheckpoint(
        checkpoint_schema_version="1.0",
        execution_id="exec-audit-mapping",
        total_events=1,
        last_sequence_number=1,
        last_event_hash=None,
        protection="tamper-evident-local",
        hmac_sha256=None,
    )
    with pytest.raises(AuditIntegrityError, match="last event hash"):
        manager.verify_checkpoint(invalid_dataclass)
