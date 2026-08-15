"""F2.2 state provider, concurrency, journal, and recovery tests."""

from __future__ import annotations

import errno
import hashlib
import json
import multiprocessing
import os
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Self

import pytest
from pydantic import ValidationError

import ai_engineering_harness.persistence.atomic_file as ATOMIC_FILE_MODULE
import ai_engineering_harness.persistence.locks as LOCKS_MODULE
from ai_engineering_harness.contracts import (
    CompiledGraphArtifact,
    GraphSpec,
    SourceManifestEntry,
)
from ai_engineering_harness.contracts.events import (
    EXECUTION_EVENT_SCHEMA_VERSION,
    ExecutionEvent,
)
from ai_engineering_harness.contracts.execution import (
    EXECUTION_RECORD_SCHEMA_VERSION,
    ApprovalStatus,
    ExecutionRecord,
    ExecutionState,
)
from ai_engineering_harness.persistence import (
    AtomicFileStateStorage,
    DuplicateEventError,
    EventJournalStateStorageProvider,
    ExecutionAlreadyExistsError,
    ExecutionBundle,
    ExecutionBundleAlreadyExistsError,
    ExecutionBundleIntegrityError,
    ExecutionBundleWriteError,
    ExecutionIdentityMismatchError,
    ExecutionLock,
    ExecutionNotFoundError,
    JournalIntegrityError,
    LockAcquisitionTimeoutError,
    LockOwnershipError,
    LockUnavailableError,
    RecoveryConflictError,
    ResumeStateStorageProvider,
    RevisionConflictError,
    StateIntegrityError,
    StateStorageError,
    StateStorageProvider,
    StateWriteError,
    canonical_json_digest,
    canonical_json_object,
    execution_record_path,
    load_execution_record,
    save_execution_record,
)

_CREATED_AT = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)
_UPDATED_AT = _CREATED_AT + timedelta(minutes=1)
_ARTIFACT_DIGEST = f"sha256:{'a' * 64}"
_CONFIGURATION_DIGEST = f"sha256:{'b' * 64}"
_BASE_SHA = "c" * 40


def _record_data(execution_id: str = "exec-f2-2", **overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "record_schema_version": EXECUTION_RECORD_SCHEMA_VERSION,
        "revision": 0,
        "execution_id": execution_id,
        "workflow_name": "new-feature",
        "artifact_digest": _ARTIFACT_DIGEST,
        "base_commit_sha": _BASE_SHA,
        "original_branch": "main",
        "worktree_path": None,
        "current_node_id": "analyze_requirements",
        "current_state": ExecutionState.INITIATED,
        "attempt_by_node": {"analyze_requirements": 0},
        "created_at": _CREATED_AT,
        "updated_at": _UPDATED_AT,
        "configuration_digest": _CONFIGURATION_DIGEST,
        "approval_status": ApprovalStatus.NOT_REQUIRED,
        "candidate_commit_sha": None,
        "promotion_commit_sha": None,
        "failure": None,
    }
    data.update(overrides)
    return data


def _record(execution_id: str = "exec-f2-2", **overrides: object) -> ExecutionRecord:
    return ExecutionRecord.model_validate(_record_data(execution_id, **overrides))


def _replacement(record: ExecutionRecord, **overrides: object) -> ExecutionRecord:
    data = record.model_dump()
    data.update(
        {
            "revision": record.revision + 1,
            "updated_at": record.updated_at + timedelta(seconds=1),
        }
    )
    data.update(overrides)
    return ExecutionRecord.model_validate(data)


def _event(event_id: str, execution_id: str = "exec-f2-2", **overrides: object) -> ExecutionEvent:
    data: dict[str, object] = {
        "event_schema_version": EXECUTION_EVENT_SCHEMA_VERSION,
        "event_id": event_id,
        "execution_id": execution_id,
        "sequence_number": 0,
        "event_type": "NODE_STARTED",
        "timestamp": _UPDATED_AT,
        "graph_name": "new-feature",
        "node_id": "analyze_requirements",
        "attempt": 1,
        "actor": "state_storage_test",
        "payload": {"node_id": "analyze_requirements", "attempt": 1},
        "previous_hash": None,
        "current_hash": None,
    }
    data.update(overrides)
    return ExecutionEvent.model_validate(data)


def _journal_path(root: Path, execution_id: str) -> Path:
    return execution_record_path(root, execution_id).with_name("event-journal.jsonl")


def _record_temp(root: Path, execution_id: str, suffix: str) -> Path:
    return execution_record_path(root, execution_id).with_name(
        f".execution.json.{suffix}.tmp"
    )


def _cas_worker(
    root: str,
    replacement_json: str,
    start_event: Any,
    result_queue: Any,
) -> None:
    provider = AtomicFileStateStorage(Path(root))
    replacement_record = ExecutionRecord.model_validate_json(replacement_json)
    start_event.wait(10)
    try:
        stored = provider.compare_and_set_execution(
            replacement_record.execution_id,
            0,
            replacement_record,
        )
    except RevisionConflictError:
        result_queue.put(("conflict", None))
    else:
        result_queue.put(("success", stored.revision))


def _append_worker(
    root: str,
    event_json: str,
    start_event: Any,
    result_queue: Any,
) -> None:
    provider = AtomicFileStateStorage(Path(root))
    event = ExecutionEvent.model_validate_json(event_json)
    start_event.wait(10)
    stored = provider.append_event(event.execution_id, event)
    result_queue.put(("success", stored.event_id))


def _lock_holder_worker(
    root: str,
    execution_id: str,
    ready_queue: Any,
    release_event: Any,
) -> None:
    provider = AtomicFileStateStorage(Path(root))
    lock = provider.acquire_execution_lock(execution_id, "holder", timeout_seconds=2)
    ready_queue.put(lock.fencing_token)
    release_event.wait(10)
    provider.release_execution_lock(lock)


def _crash_lock_worker(root: str, execution_id: str, connection: Any) -> None:
    provider = AtomicFileStateStorage(Path(root))
    lock = provider.acquire_execution_lock(execution_id, "crasher", timeout_seconds=2)
    connection.send(lock.fencing_token)
    connection.close()
    os._exit(0)


def _payload_worker(
    root: str,
    execution_id: str,
    start_event: Any,
    result_queue: Any,
) -> None:
    provider = AtomicFileStateStorage(Path(root))
    start_event.wait(10)
    result_queue.put(provider.store_payload(execution_id, {"worker": "shared"}))


def test_interface_has_exact_operations_and_public_exports(tmp_path: Path) -> None:
    expected = {
        "create_execution",
        "load_execution",
        "compare_and_set_execution",
        "append_event",
        "list_executions",
        "acquire_execution_lock",
        "release_execution_lock",
    }
    operations = {
        name
        for name, value in vars(StateStorageProvider).items()
        if not name.startswith("_") and callable(value)
    }
    journal_operations = {
        name
        for name, value in vars(EventJournalStateStorageProvider).items()
        if not name.startswith("_") and callable(value)
    }
    resume_operations = {
        name
        for name, value in vars(ResumeStateStorageProvider).items()
        if not name.startswith("_") and callable(value)
    }
    provider = AtomicFileStateStorage(tmp_path)

    assert operations == expected
    assert journal_operations == {"load_events"}
    assert resume_operations == {
        "create_execution_bundle",
        "load_execution_bundle",
        "load_payload",
        "store_payload",
    }
    assert isinstance(provider, StateStorageProvider)
    assert isinstance(provider, EventJournalStateStorageProvider)
    assert isinstance(provider, ResumeStateStorageProvider)
    assert issubclass(RevisionConflictError, StateStorageError)
    assert issubclass(JournalIntegrityError, StateStorageError)

    from ai_engineering_harness import persistence

    assert persistence.AtomicFileStateStorage is AtomicFileStateStorage
    assert (
        persistence.EventJournalStateStorageProvider
        is EventJournalStateStorageProvider
    )
    assert persistence.StateStorageProvider is StateStorageProvider
    assert persistence.ResumeStateStorageProvider is ResumeStateStorageProvider
    assert persistence.ExecutionLock is ExecutionLock
    assert persistence.save_execution_record is save_execution_record
    assert persistence.load_execution_record is load_execution_record


def test_create_load_and_list_are_canonical_and_sorted(tmp_path: Path) -> None:
    provider = AtomicFileStateStorage(tmp_path)
    second = _record("exec-z")
    first = _record("exec-a")

    assert provider.create_execution(second) == second
    assert provider.create_execution(first) == first
    assert provider.load_execution(first.execution_id) == first
    assert provider.list_executions() == (first, second)
    assert execution_record_path(tmp_path, first.execution_id).read_text(
        encoding="utf-8"
    ) == first.canonical_json()


def test_list_ignores_legacy_directory_and_locks_do_not_create_phantoms(
    tmp_path: Path,
) -> None:
    provider = AtomicFileStateStorage(tmp_path)
    lock = provider.acquire_execution_lock("exec-lock-only", "owner", timeout_seconds=0)
    provider.release_execution_lock(lock)
    legacy = tmp_path / ".harness" / "state" / "executions" / "exec-legacy"
    legacy.mkdir(parents=True)
    (legacy / "workflow-state.json").write_text("{}", encoding="utf-8")

    assert provider.list_executions() == ()
    assert not (
        tmp_path / ".harness" / "state" / "executions" / "exec-lock-only"
    ).exists()


def test_duplicate_create_never_overwrites_bytes(tmp_path: Path) -> None:
    provider = AtomicFileStateStorage(tmp_path)
    original = _record()
    provider.create_execution(original)
    path = execution_record_path(tmp_path, original.execution_id)
    previous = path.read_bytes()

    with pytest.raises(ExecutionAlreadyExistsError):
        provider.create_execution(
            _record(current_node_id="different-node", updated_at=_UPDATED_AT + timedelta(seconds=1))
        )

    assert path.read_bytes() == previous


def test_create_wrong_revision_and_load_missing_fail_typed(tmp_path: Path) -> None:
    provider = AtomicFileStateStorage(tmp_path)
    with pytest.raises(RevisionConflictError):
        provider.create_execution(_record(revision=1))
    with pytest.raises(ExecutionNotFoundError):
        provider.load_execution("exec-missing")


def test_cas_success_increments_exactly_once(tmp_path: Path) -> None:
    provider = AtomicFileStateStorage(tmp_path)
    original = _record()
    provider.create_execution(original)
    replacement_record = _replacement(
        original,
        current_node_id="generate_plan",
        current_state=ExecutionState.PLANNING,
    )

    assert provider.compare_and_set_execution(
        original.execution_id,
        0,
        replacement_record,
    ) == replacement_record
    assert provider.load_execution(original.execution_id) == replacement_record


def test_stale_cas_and_wrong_revision_preserve_bytes(tmp_path: Path) -> None:
    provider = AtomicFileStateStorage(tmp_path)
    original = _record()
    provider.create_execution(original)
    replacement_record = _replacement(original)
    provider.compare_and_set_execution(original.execution_id, 0, replacement_record)
    path = execution_record_path(tmp_path, original.execution_id)
    previous = path.read_bytes()

    with pytest.raises(RevisionConflictError) as stale:
        provider.compare_and_set_execution(
            original.execution_id,
            0,
            replacement_record,
        )
    assert stale.value.actual_revision == 1

    wrong_next = _replacement(replacement_record, revision=4)
    with pytest.raises(RevisionConflictError):
        provider.compare_and_set_execution(original.execution_id, 1, wrong_next)

    assert path.read_bytes() == previous


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("execution_id", "exec-other"),
        ("workflow_name", "other-workflow"),
        ("artifact_digest", f"sha256:{'d' * 64}"),
        ("base_commit_sha", "e" * 40),
        ("original_branch", "release"),
        ("configuration_digest", f"sha256:{'f' * 64}"),
        ("created_at", _CREATED_AT + timedelta(seconds=1)),
        ("updated_at", _UPDATED_AT - timedelta(seconds=1)),
    ],
)
def test_cas_identity_mismatch_is_rejected_without_write(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    provider = AtomicFileStateStorage(tmp_path)
    original = _record()
    provider.create_execution(original)
    replacement_record = _replacement(original, **{field: value})
    path = execution_record_path(tmp_path, original.execution_id)
    previous = path.read_bytes()

    with pytest.raises(ExecutionIdentityMismatchError):
        provider.compare_and_set_execution(original.execution_id, 0, replacement_record)

    assert path.read_bytes() == previous


def test_explicit_lock_allows_append_and_cas_under_one_exclusion(tmp_path: Path) -> None:
    provider = AtomicFileStateStorage(tmp_path)
    original = _record()
    provider.create_execution(original)
    lock = provider.acquire_execution_lock(original.execution_id, "fsm-owner", timeout_seconds=0)
    try:
        stored_event = provider.append_event(
            original.execution_id,
            _event("evt-under-lock"),
            lock=lock,
        )
        replacement_record = _replacement(original)
        stored_record = provider.compare_and_set_execution(
            original.execution_id,
            0,
            replacement_record,
            lock=lock,
        )
        assert provider.load_execution(original.execution_id, lock=lock) == stored_record
    finally:
        provider.release_execution_lock(lock)

    assert stored_event.previous_hash == "0" * 64


def test_append_event_is_canonical_and_hash_chained(tmp_path: Path) -> None:
    provider = AtomicFileStateStorage(tmp_path)
    provider.create_execution(_record())

    first = provider.append_event("exec-f2-2", _event("evt-1"))
    second = provider.append_event(
        "exec-f2-2",
        _event(
            "evt-2",
            event_type="NODE_COMPLETED",
            payload={"ok": True, "password": "controlled-journal-secret"},
        ),
    )
    raw = _journal_path(tmp_path, "exec-f2-2").read_bytes()
    lines = raw.splitlines()

    assert len(lines) == 2
    assert raw.endswith(b"\n") and b"\r" not in raw
    assert first.previous_hash == "0" * 64
    assert first.sequence_number == 1
    assert second.sequence_number == 2
    assert second.previous_hash == first.current_hash
    assert b"controlled-journal-secret" not in raw
    for line in lines:
        document = json.loads(line)
        assert {
            "event_id",
            "execution_id",
            "sequence_number",
            "event_type",
            "timestamp",
            "graph_name",
            "node_id",
            "attempt",
            "actor",
            "details",
            "previous_hash",
            "current_hash",
        } <= document.keys()
        assert "payload" not in document
        current_hash = document.pop("current_hash")
        canonical_without_hash = json.dumps(
            document,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        assert current_hash == hashlib.sha256(canonical_without_hash).hexdigest()
        assert line == json.dumps(
            json.loads(line),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")


def test_append_revalidates_mutated_details_before_hashing(tmp_path: Path) -> None:
    provider = AtomicFileStateStorage(tmp_path)
    provider.create_execution(_record())
    draft = _event("evt-mutated-details")
    draft.details["password"] = 1234

    persisted = provider.append_event("exec-f2-2", draft)
    loaded = provider.load_events("exec-f2-2")

    assert persisted.details["password"] == "[REDACTED_SECRET]"
    assert loaded == (persisted,)
    assert b'"password":1234' not in _journal_path(tmp_path, "exec-f2-2").read_bytes()


def test_append_rejects_mutated_non_json_details_before_write(tmp_path: Path) -> None:
    provider = AtomicFileStateStorage(tmp_path)
    provider.create_execution(_record())
    draft = _event("evt-mutated-non-json")
    draft.details["invalid"] = (1, 2)

    with pytest.raises(JournalIntegrityError, match="event envelope is invalid"):
        provider.append_event("exec-f2-2", draft)

    assert not _journal_path(tmp_path, "exec-f2-2").exists()


def test_load_events_returns_detached_canonical_tuple_under_lock(
    tmp_path: Path,
) -> None:
    provider = AtomicFileStateStorage(tmp_path)
    provider.create_execution(_record())
    lock = provider.acquire_execution_lock(
        "exec-f2-2",
        "journal-reader",
        timeout_seconds=0,
    )
    try:
        persisted = provider.append_event(
            "exec-f2-2",
            _event("evt-load-events", payload={"value": "canonical"}),
            lock=lock,
        )
        loaded = provider.load_events("exec-f2-2", lock=lock)
    finally:
        provider.release_execution_lock(lock)

    assert loaded == (persisted,)
    assert isinstance(loaded, tuple)
    loaded[0].payload["value"] = "caller-mutated"
    assert provider.load_events("exec-f2-2")[0].payload == {
        "value": "canonical"
    }

    with pytest.raises(ExecutionNotFoundError):
        provider.load_events("exec-missing")


def test_duplicate_event_and_caller_metadata_preserve_journal(tmp_path: Path) -> None:
    provider = AtomicFileStateStorage(tmp_path)
    provider.create_execution(_record())
    provider.append_event("exec-f2-2", _event("evt-duplicate"))
    path = _journal_path(tmp_path, "exec-f2-2")
    previous = path.read_bytes()

    with pytest.raises(DuplicateEventError):
        provider.append_event("exec-f2-2", _event("evt-duplicate"))
    with pytest.raises(JournalIntegrityError, match="caller-supplied"):
        provider.append_event(
            "exec-f2-2",
            _event("evt-hashed", previous_hash="0" * 64),
        )
    with pytest.raises(JournalIntegrityError, match="caller-supplied"):
        provider.append_event(
            "exec-f2-2",
            _event("evt-sequenced", sequence_number=2),
        )
    with pytest.raises(ExecutionIdentityMismatchError, match="graph_name"):
        provider.append_event(
            "exec-f2-2",
            _event("evt-other-graph", graph_name="other-workflow"),
        )
    assert path.read_bytes() == previous


@pytest.mark.parametrize("mutation", ["hash", "line", "utf8", "legacy"])
def test_journal_corruption_and_legacy_format_fail_closed(
    tmp_path: Path,
    mutation: str,
) -> None:
    provider = AtomicFileStateStorage(tmp_path)
    provider.create_execution(_record())
    provider.append_event("exec-f2-2", _event("evt-corrupt"))
    path = _journal_path(tmp_path, "exec-f2-2")
    if mutation == "hash":
        document = json.loads(path.read_text(encoding="utf-8"))
        document["current_hash"] = "f" * 64
        path.write_text(
            json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
    elif mutation == "line":
        path.write_bytes(path.read_bytes().removesuffix(b"\n"))
    elif mutation == "utf8":
        path.write_bytes(b"\xff\n")
    else:
        path.write_text('{"event":"legacy"}\n', encoding="utf-8")
    previous = path.read_bytes()

    with pytest.raises(JournalIntegrityError):
        provider.append_event("exec-f2-2", _event("evt-after-corruption"))
    assert path.read_bytes() == previous


def test_execution_event_envelope_is_strict_canonical_and_compatible() -> None:
    event = _event("evt-envelope", payload={"z": [1, True, None], "a": 1.5})
    assert event.event_schema_version == "2.0"
    assert event.canonical_json().endswith("\n")
    assert "\n" not in event.canonical_json()[:-1]
    assert ExecutionEvent.model_validate_json(event.canonical_json()) == event

    compatible = ExecutionEvent(
        event_id="evt-compatible",
        execution_id="exec-compatible",
        sequence_number=1,
        event_type="NODE_COMPLETED",
        timestamp=_UPDATED_AT,
        graph_name="new-feature",
        node_id="compatible",
        attempt=1,
        actor="state_storage_test",
        details={},
        previous_hash="hash-1",
        current_hash="hash-2",
    )
    assert compatible.event_schema_version == "2.0"


@pytest.mark.parametrize(
    "overrides",
    [
        {"event_schema_version": "1.0"},
        {"event_id": "../escape"},
        {"execution_id": "CON"},
        {"event_type": "UNKNOWN_EVENT"},
        {"timestamp": _UPDATED_AT.replace(tzinfo=None)},
        {"timestamp": _UPDATED_AT.astimezone(timezone(-timedelta(hours=3)))},
        {"payload": {"bad": float("nan")}},
        {"payload": {"bad": (1, 2)}},
        {"payload": {1: "bad"}},
        {"unexpected": True},
    ],
)
def test_execution_event_invalid_envelope_is_rejected(overrides: dict[str, object]) -> None:
    document = _event("evt-invalid").model_dump()
    document.update(overrides)
    with pytest.raises((ValidationError, TypeError)):
        ExecutionEvent.model_validate(document)


def test_lock_handle_forged_foreign_released_and_nonreentrant_fail(
    tmp_path: Path,
) -> None:
    provider = AtomicFileStateStorage(tmp_path)
    other_provider = AtomicFileStateStorage(tmp_path)
    lock = provider.acquire_execution_lock("exec-lock", "owner", timeout_seconds=0)
    forged = replace(lock)

    with pytest.raises(LockOwnershipError):
        provider.load_execution("exec-lock", lock=forged)
    with pytest.raises(LockOwnershipError):
        other_provider.release_execution_lock(lock)
    with pytest.raises(LockOwnershipError, match="not reentrant"):
        provider.acquire_execution_lock("exec-lock", "owner", timeout_seconds=0)

    provider.release_execution_lock(lock)
    with pytest.raises(LockOwnershipError):
        provider.release_execution_lock(lock)


def test_lock_timeout_and_fencing_are_cross_process(tmp_path: Path) -> None:
    context = multiprocessing.get_context("spawn")
    ready_queue = context.Queue()
    release_event = context.Event()
    process = context.Process(
        target=_lock_holder_worker,
        args=(str(tmp_path), "exec-timeout", ready_queue, release_event),
    )
    process.start()
    first_token = ready_queue.get(timeout=10)
    provider = AtomicFileStateStorage(tmp_path)
    try:
        with pytest.raises(LockAcquisitionTimeoutError):
            provider.acquire_execution_lock(
                "exec-timeout",
                "contender",
                timeout_seconds=0.05,
            )
    finally:
        release_event.set()
        process.join(10)

    assert process.exitcode == 0
    next_lock = provider.acquire_execution_lock(
        "exec-timeout",
        "next-owner",
        timeout_seconds=2,
    )
    try:
        assert next_lock.fencing_token > first_token
    finally:
        provider.release_execution_lock(next_lock)


def test_crash_releases_lock_and_fencing_token_never_repeats(tmp_path: Path) -> None:
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(
        target=_crash_lock_worker,
        args=(str(tmp_path), "exec-crash", sender),
    )
    process.start()
    crashed_token = receiver.recv()
    process.join(10)
    assert process.exitcode == 0

    provider = AtomicFileStateStorage(tmp_path)
    lock = provider.acquire_execution_lock(
        "exec-crash",
        "recovery-owner",
        timeout_seconds=2,
    )
    try:
        assert lock.fencing_token > crashed_token
    finally:
        provider.release_execution_lock(lock)
    fence = tmp_path / ".harness" / "state" / "locks" / "exec-crash.fence"
    assert fence.read_text(encoding="ascii") == f"{lock.fencing_token}\n"


def test_multiprocess_concurrent_cas_has_one_success_one_conflict(tmp_path: Path) -> None:
    provider = AtomicFileStateStorage(tmp_path)
    original = _record("exec-concurrent-cas")
    provider.create_execution(original)
    replacement_record = _replacement(original)
    context = multiprocessing.get_context("spawn")
    start_event = context.Event()
    result_queue = context.Queue()
    processes = [
        context.Process(
            target=_cas_worker,
            args=(str(tmp_path), replacement_record.canonical_json(), start_event, result_queue),
        )
        for _ in range(2)
    ]
    for process in processes:
        process.start()
    start_event.set()
    results = [result_queue.get(timeout=15) for _ in processes]
    for process in processes:
        process.join(15)

    assert sorted(result[0] for result in results) == ["conflict", "success"]
    assert all(process.exitcode == 0 for process in processes)
    assert provider.load_execution(original.execution_id).revision == 1


def test_multiprocess_concurrent_appends_preserve_both_events(tmp_path: Path) -> None:
    provider = AtomicFileStateStorage(tmp_path)
    execution_id = "exec-concurrent-append"
    provider.create_execution(_record(execution_id))
    context = multiprocessing.get_context("spawn")
    start_event = context.Event()
    result_queue = context.Queue()
    events = [_event(f"evt-{index}", execution_id) for index in range(2)]
    processes = [
        context.Process(
            target=_append_worker,
            args=(str(tmp_path), event.model_dump_json(), start_event, result_queue),
        )
        for event in events
    ]
    for process in processes:
        process.start()
    start_event.set()
    results = [result_queue.get(timeout=15) for _ in processes]
    for process in processes:
        process.join(15)

    assert [result[0] for result in results].count("success") == 2
    assert all(process.exitcode == 0 for process in processes)
    lines = _journal_path(tmp_path, execution_id).read_text(encoding="utf-8").splitlines()
    assert {json.loads(line)["event_id"] for line in lines} == {"evt-0", "evt-1"}
    assert json.loads(lines[1])["previous_hash"] == json.loads(lines[0])["current_hash"]


def test_recovery_promotes_single_valid_abandoned_record(tmp_path: Path) -> None:
    provider = AtomicFileStateStorage(tmp_path)
    record = _record("exec-recovery-single")
    temp = _record_temp(tmp_path, record.execution_id, "controlled")
    temp.parent.mkdir(parents=True)
    temp.write_bytes(record.canonical_json().encode("utf-8"))

    assert provider.load_execution(record.execution_id) == record
    assert execution_record_path(tmp_path, record.execution_id).exists()
    assert not temp.exists()


def test_list_recovery_promotes_managed_temp_and_rejects_corrupt_record(
    tmp_path: Path,
) -> None:
    provider = AtomicFileStateStorage(tmp_path)
    recoverable = _record("exec-list-recovery")
    temp = _record_temp(tmp_path, recoverable.execution_id, "list")
    temp.parent.mkdir(parents=True)
    temp.write_bytes(recoverable.canonical_json().encode("utf-8"))

    assert provider.list_executions() == (recoverable,)
    assert not temp.exists()

    corrupt = execution_record_path(tmp_path, "exec-list-corrupt")
    corrupt.parent.mkdir(parents=True)
    corrupt.write_bytes(b"corrupt")
    with pytest.raises(RecoveryConflictError):
        provider.list_executions()


def test_recovery_canonical_record_wins_and_cleans_abandoned_temp(tmp_path: Path) -> None:
    provider = AtomicFileStateStorage(tmp_path)
    record = _record("exec-recovery-canonical")
    provider.create_execution(record)
    temp = _record_temp(tmp_path, record.execution_id, "orphan")
    temp.write_bytes(b"invalid candidate retained only when canonical is absent")

    assert provider.load_execution(record.execution_id) == record
    assert not temp.exists()


@pytest.mark.parametrize("candidate_count", [1, 2])
def test_recovery_invalid_or_ambiguous_candidates_preserve_evidence(
    tmp_path: Path,
    candidate_count: int,
) -> None:
    provider = AtomicFileStateStorage(tmp_path)
    execution_id = "exec-recovery-conflict"
    candidates = [
        _record_temp(tmp_path, execution_id, f"candidate-{index}")
        for index in range(candidate_count)
    ]
    candidates[0].parent.mkdir(parents=True)
    for candidate in candidates:
        candidate.write_bytes(b"not canonical")
    previous = {candidate: candidate.read_bytes() for candidate in candidates}

    with pytest.raises(RecoveryConflictError):
        provider.load_execution(execution_id)
    assert {candidate: candidate.read_bytes() for candidate in candidates} == previous
    assert not execution_record_path(tmp_path, execution_id).exists()


def test_recovery_invalid_canonical_preserves_all_evidence(tmp_path: Path) -> None:
    provider = AtomicFileStateStorage(tmp_path)
    execution_id = "exec-recovery-invalid-canonical"
    destination = execution_record_path(tmp_path, execution_id)
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"corrupt canonical")
    candidate = _record_temp(tmp_path, execution_id, "valid")
    candidate.write_text(_record(execution_id).canonical_json(), encoding="utf-8")
    previous_destination = destination.read_bytes()
    previous_candidate = candidate.read_bytes()

    with pytest.raises(RecoveryConflictError):
        provider.load_execution(execution_id)
    assert destination.read_bytes() == previous_destination
    assert candidate.read_bytes() == previous_candidate


def test_recovery_promotes_single_abandoned_journal_before_append(tmp_path: Path) -> None:
    provider = AtomicFileStateStorage(tmp_path)
    provider.create_execution(_record())
    provider.append_event("exec-f2-2", _event("evt-before-crash"))
    canonical = _journal_path(tmp_path, "exec-f2-2")
    abandoned = canonical.with_name(f".{canonical.name}.controlled.tmp")
    abandoned.write_bytes(canonical.read_bytes())
    canonical.unlink()

    provider.append_event("exec-f2-2", _event("evt-after-crash"))
    lines = canonical.read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["event_id"] for line in lines] == [
        "evt-before-crash",
        "evt-after-crash",
    ]
    assert not abandoned.exists()


def test_load_events_recovers_single_abandoned_journal_candidate(
    tmp_path: Path,
) -> None:
    provider = AtomicFileStateStorage(tmp_path)
    provider.create_execution(_record())
    persisted = provider.append_event("exec-f2-2", _event("evt-load-recovery"))
    canonical = _journal_path(tmp_path, "exec-f2-2")
    abandoned = canonical.with_name(f".{canonical.name}.load-events.tmp")
    abandoned.write_bytes(canonical.read_bytes())
    canonical.unlink()

    assert provider.load_events("exec-f2-2") == (persisted,)
    assert canonical.is_file()
    assert not abandoned.exists()


def test_recovery_ambiguous_journal_candidates_preserve_evidence(tmp_path: Path) -> None:
    provider = AtomicFileStateStorage(tmp_path)
    provider.create_execution(_record())
    provider.append_event("exec-f2-2", _event("evt-before-ambiguity"))
    canonical = _journal_path(tmp_path, "exec-f2-2")
    candidates = [
        canonical.with_name(f".{canonical.name}.candidate-{index}.tmp")
        for index in range(2)
    ]
    for candidate in candidates:
        candidate.write_bytes(canonical.read_bytes())
    canonical.unlink()
    previous = {candidate: candidate.read_bytes() for candidate in candidates}

    with pytest.raises(RecoveryConflictError):
        provider.append_event("exec-f2-2", _event("evt-after-ambiguity"))
    assert {candidate: candidate.read_bytes() for candidate in candidates} == previous


class _FailingStream:
    def __init__(self, stream: Any, stage: str) -> None:
        self._stream = stream
        self._stage = stage

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> object:
        return self._stream.__exit__(*args)

    def write(self, content: bytes) -> int:
        if self._stage == "write":
            raise OSError("controlled write failure")
        return self._stream.write(content)

    def flush(self) -> None:
        if self._stage == "flush":
            raise OSError("controlled flush failure")
        self._stream.flush()

    def fileno(self) -> int:
        return self._stream.fileno()


@pytest.mark.parametrize("stage", ["create", "write", "flush", "fsync", "replace"])
def test_atomic_failure_during_cas_preserves_destination_and_removes_temp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
) -> None:
    provider = AtomicFileStateStorage(tmp_path)
    original = _record("exec-atomic-failure")
    provider.create_execution(original)
    destination = execution_record_path(tmp_path, original.execution_id)
    previous = destination.read_bytes()
    replacement_record = _replacement(original)

    if stage == "create":
        monkeypatch.setattr(
            ATOMIC_FILE_MODULE.tempfile,
            "mkstemp",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                OSError("controlled create failure")
            ),
        )
    elif stage in {"write", "flush"}:
        original_fdopen: Any = os.fdopen

        def failing_fdopen(*args: object, **kwargs: object) -> _FailingStream:
            return _FailingStream(original_fdopen(*args, **kwargs), stage)

        monkeypatch.setattr(ATOMIC_FILE_MODULE.os, "fdopen", failing_fdopen)
    elif stage == "fsync":
        monkeypatch.setattr(
            ATOMIC_FILE_MODULE.os,
            "fsync",
            lambda descriptor: (_ for _ in ()).throw(
                OSError("controlled fsync failure")
            ),
        )
    else:
        monkeypatch.setattr(
            ATOMIC_FILE_MODULE.os,
            "replace",
            lambda source, target: (_ for _ in ()).throw(
                OSError("controlled replace failure")
            ),
        )

    with pytest.raises(StateWriteError, match=f"controlled {stage} failure"):
        provider.compare_and_set_execution(
            original.execution_id,
            0,
            replacement_record,
        )

    assert destination.read_bytes() == previous
    assert not tuple(destination.parent.glob(".execution.json.*.tmp"))


@pytest.mark.parametrize("stage", ["create", "write", "flush", "fsync", "replace"])
def test_atomic_failure_during_append_preserves_journal_and_removes_temp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
) -> None:
    provider = AtomicFileStateStorage(tmp_path)
    provider.create_execution(_record())
    provider.append_event("exec-f2-2", _event("evt-before-atomic-failure"))
    destination = _journal_path(tmp_path, "exec-f2-2")
    previous = destination.read_bytes()

    if stage == "create":
        monkeypatch.setattr(
            ATOMIC_FILE_MODULE.tempfile,
            "mkstemp",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                OSError("controlled create failure")
            ),
        )
    elif stage in {"write", "flush"}:
        original_fdopen: Any = os.fdopen

        def failing_fdopen(*args: object, **kwargs: object) -> _FailingStream:
            return _FailingStream(original_fdopen(*args, **kwargs), stage)

        monkeypatch.setattr(ATOMIC_FILE_MODULE.os, "fdopen", failing_fdopen)
    elif stage == "fsync":
        monkeypatch.setattr(
            ATOMIC_FILE_MODULE.os,
            "fsync",
            lambda descriptor: (_ for _ in ()).throw(
                OSError("controlled fsync failure")
            ),
        )
    else:
        monkeypatch.setattr(
            ATOMIC_FILE_MODULE.os,
            "replace",
            lambda source, target: (_ for _ in ()).throw(
                OSError("controlled replace failure")
            ),
        )

    with pytest.raises(StateWriteError, match=f"controlled {stage} failure"):
        provider.append_event("exec-f2-2", _event("evt-after-atomic-failure"))

    assert destination.read_bytes() == previous
    assert not tuple(destination.parent.glob(".event-journal.jsonl.*.tmp"))


def test_lock_unavailable_and_corrupt_fencing_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = AtomicFileStateStorage(tmp_path)

    def unavailable(descriptor: int) -> None:
        raise OSError(errno.ENOSYS, "controlled unavailable lock")

    monkeypatch.setattr(LOCKS_MODULE, "_try_lock_descriptor", unavailable)
    with pytest.raises(LockUnavailableError, match="unavailable"):
        provider.acquire_execution_lock("exec-unavailable", "owner", timeout_seconds=0)

    monkeypatch.undo()
    lock = provider.acquire_execution_lock("exec-corrupt-fence", "owner", timeout_seconds=0)
    provider.release_execution_lock(lock)
    fence = (
        tmp_path
        / ".harness"
        / "state"
        / "locks"
        / "exec-corrupt-fence.fence"
    )
    fence.write_bytes(b"not-canonical")
    with pytest.raises(StateIntegrityError, match="fencing token"):
        provider.acquire_execution_lock(
            "exec-corrupt-fence",
            "next-owner",
            timeout_seconds=0,
        )
    assert fence.read_bytes() == b"not-canonical"


def test_invalid_execution_id_and_symlink_escape_fail_closed(tmp_path: Path) -> None:
    provider = AtomicFileStateStorage(tmp_path)
    with pytest.raises(StateIntegrityError):
        provider.load_execution("../escape")

    if not hasattr(os, "symlink"):
        return
    outside = tmp_path.parent / f"outside-{time.time_ns()}"
    outside.mkdir()
    state_root = tmp_path / ".harness" / "state"
    state_root.mkdir(parents=True)
    try:
        os.symlink(outside, state_root / "executions", target_is_directory=True)
    except OSError:
        outside.rmdir()
        return
    try:
        with pytest.raises(StateIntegrityError, match="escapes"):
            provider.load_execution("exec-symlink")
    finally:
        (state_root / "executions").unlink()
        outside.rmdir()


def _bundle_fixture(
    execution_id: str,
) -> tuple[ExecutionBundle, dict[str, object]]:
    graph = GraphSpec.model_validate(
        {
            "graph": {
                "name": "bundle-test",
                "graph_schema_version": "1.0",
                "definition_version": "1.0.0",
                "entrypoint": "execute",
                "status": "stable",
            },
            "nodes": [
                {
                    "id": "execute",
                    "type": "deterministic",
                    "executor": "deterministic_gate",
                    "gate_name": "bundle",
                    "on_success": "completed",
                    "on_failure": "failed",
                }
            ],
            "terminal_states": [
                {"id": "completed", "outcome": "success"},
                {"id": "failed", "outcome": "failure"},
            ],
            "policies": [],
            "contracts": [],
        }
    )
    artifact = CompiledGraphArtifact.build(
        graph=graph,
        resolved_contracts=(),
        resolved_policies=(),
        source_manifest=(
            SourceManifestEntry(
                source_kind="graph",
                source_id="project://bundle-test.yaml",
                content_digest=f"sha256:{'0' * 64}",
            ),
        ),
    )
    artifact_json = artifact.canonical_json()
    configuration_json = canonical_json_object({"profile": "bundle-test"})
    initial_input = {"intent": "persist exactly"}
    initial_json = canonical_json_object(initial_input)
    return (
        ExecutionBundle(
            bundle_schema_version="1.0",
            execution_id=execution_id,
            artifact_digest=canonical_json_digest(artifact_json),
            configuration_digest=canonical_json_digest(configuration_json),
            initial_input_digest=canonical_json_digest(initial_json),
            artifact_json=artifact_json,
            configuration_json=configuration_json,
        ),
        initial_input,
    )


def _create_bundle_and_record(
    root: Path,
    execution_id: str = "exec-bundle",
) -> tuple[AtomicFileStateStorage, ExecutionBundle, dict[str, object]]:
    provider = AtomicFileStateStorage(root)
    bundle, initial_input = _bundle_fixture(execution_id)
    provider.create_execution_bundle(bundle, initial_input=initial_input)
    provider.create_execution(
        _record(
            execution_id,
            artifact_digest=bundle.artifact_digest,
            configuration_digest=bundle.configuration_digest,
            current_node_id="execute",
        )
    )
    return provider, bundle, initial_input


def test_bundle_payload_create_load_public_immutable_and_canonical(
    tmp_path: Path,
) -> None:
    provider, bundle, initial_input = _create_bundle_and_record(tmp_path)

    assert provider.load_execution_bundle(bundle.execution_id) == bundle
    assert provider.load_payload(
        bundle.execution_id,
        bundle.initial_input_digest,
    ) == initial_input
    payload = {"nested": {"value": 1}, "items": [True, None]}
    digest = provider.store_payload(bundle.execution_id, payload)
    loaded = provider.load_payload(bundle.execution_id, digest)
    loaded["mutated"] = True
    assert provider.load_payload(bundle.execution_id, digest) == payload

    directory = (
        tmp_path / ".harness" / "artifacts" / "executions" / bundle.execution_id
    )
    assert (directory / "artifact.json").read_text(encoding="utf-8") == bundle.artifact_json
    assert (directory / "configuration.json").read_text(
        encoding="utf-8"
    ) == bundle.configuration_json
    assert (directory / "bundle.json").read_text(
        encoding="utf-8"
    ) == bundle.manifest_json()
    with pytest.raises(ExecutionBundleAlreadyExistsError):
        provider.create_execution_bundle(bundle, initial_input=initial_input)


def test_bundle_create_conflict_with_existing_record_preserves_state(
    tmp_path: Path,
) -> None:
    execution_id = "exec-bundle-record-conflict"
    provider = AtomicFileStateStorage(tmp_path)
    record = _record(execution_id)
    provider.create_execution(record)
    record_bytes = execution_record_path(tmp_path, execution_id).read_bytes()
    bundle, initial_input = _bundle_fixture(execution_id)

    with pytest.raises(ExecutionBundleAlreadyExistsError):
        provider.create_execution_bundle(bundle, initial_input=initial_input)

    assert execution_record_path(tmp_path, execution_id).read_bytes() == record_bytes
    assert not (
        tmp_path / ".harness" / "artifacts" / "executions" / execution_id
    ).exists()


@pytest.mark.parametrize(
    "component",
    ["artifact.json", "configuration.json", "bundle.json", "initial-payload"],
)
def test_bundle_or_payload_tamper_fails_closed_and_preserves_bytes(
    tmp_path: Path,
    component: str,
) -> None:
    provider, bundle, _ = _create_bundle_and_record(tmp_path)
    directory = (
        tmp_path / ".harness" / "artifacts" / "executions" / bundle.execution_id
    )
    target = (
        directory / "payloads" / f"{bundle.initial_input_digest.removeprefix('sha256:')}.json"
        if component == "initial-payload"
        else directory / component
    )
    target.write_bytes(b'{"tampered":true}\n')
    tampered = target.read_bytes()

    with pytest.raises(ExecutionBundleIntegrityError):
        provider.load_execution_bundle(bundle.execution_id)

    assert target.read_bytes() == tampered


def test_bundle_missing_component_fails_closed_without_reconstruction(
    tmp_path: Path,
) -> None:
    provider, bundle, _ = _create_bundle_and_record(tmp_path)
    target = (
        tmp_path
        / ".harness"
        / "artifacts"
        / "executions"
        / bundle.execution_id
        / "configuration.json"
    )
    target.unlink()

    with pytest.raises(ExecutionBundleIntegrityError, match="missing"):
        provider.load_execution_bundle(bundle.execution_id)

    assert not target.exists()


def test_bundle_recovery_of_one_abandoned_canonical_payload_temp(
    tmp_path: Path,
) -> None:
    provider, bundle, initial_input = _create_bundle_and_record(tmp_path)
    target = (
        tmp_path
        / ".harness"
        / "artifacts"
        / "executions"
        / bundle.execution_id
        / "payloads"
        / f"{bundle.initial_input_digest.removeprefix('sha256:')}.json"
    )
    temporary = target.with_name(f".{target.name}.recovery.tmp")
    target.replace(temporary)

    assert provider.load_payload(
        bundle.execution_id,
        bundle.initial_input_digest,
    ) == initial_input
    assert target.is_file()
    assert not temporary.exists()


def test_bundle_recovery_with_multiple_temporaries_fails_closed(
    tmp_path: Path,
) -> None:
    provider, bundle, _ = _create_bundle_and_record(tmp_path)
    target = (
        tmp_path
        / ".harness"
        / "artifacts"
        / "executions"
        / bundle.execution_id
        / "configuration.json"
    )
    canonical = target.read_bytes()
    target.unlink()
    first = target.with_name(f".{target.name}.one.tmp")
    second = target.with_name(f".{target.name}.two.tmp")
    first.write_bytes(canonical)
    second.write_bytes(canonical)

    with pytest.raises(RecoveryConflictError, match="multiple"):
        provider.load_execution_bundle(bundle.execution_id)

    assert not target.exists()
    assert first.read_bytes() == canonical
    assert second.read_bytes() == canonical


def test_payload_atomic_write_failure_removes_temp_and_publishes_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider, bundle, _ = _create_bundle_and_record(tmp_path)
    payload = {"new": "payload"}
    digest = canonical_json_digest(canonical_json_object(payload))
    target = (
        tmp_path
        / ".harness"
        / "artifacts"
        / "executions"
        / bundle.execution_id
        / "payloads"
        / f"{digest.removeprefix('sha256:')}.json"
    )
    original_atomic_replace = ATOMIC_FILE_MODULE._atomic_replace_bytes

    def fail_target_only(destination: Path, content: bytes) -> None:
        if destination == target:
            raise OSError("controlled bundle replace failure")
        original_atomic_replace(destination, content)

    monkeypatch.setattr(
        ATOMIC_FILE_MODULE,
        "_atomic_replace_bytes",
        fail_target_only,
    )

    with pytest.raises(ExecutionBundleWriteError, match="publish"):
        provider.store_payload(bundle.execution_id, payload)

    assert not target.exists()
    assert not tuple(target.parent.glob(f".{target.name}.*.tmp"))


def test_payload_noncanonical_missing_or_invalid_digest_fails_closed(
    tmp_path: Path,
) -> None:
    provider, bundle, _ = _create_bundle_and_record(tmp_path)

    with pytest.raises(ExecutionBundleIntegrityError):
        provider.store_payload(bundle.execution_id, {"bad": float("nan")})
    with pytest.raises(ExecutionBundleIntegrityError, match="invalid"):
        provider.load_payload(bundle.execution_id, "sha256:not-a-digest")
    with pytest.raises(ExecutionBundleIntegrityError, match="missing"):
        provider.load_payload(bundle.execution_id, f"sha256:{'f' * 64}")


def test_concurrent_payload_publication_is_idempotent(tmp_path: Path) -> None:
    _, bundle, _ = _create_bundle_and_record(tmp_path)
    context = multiprocessing.get_context("spawn")
    start_event = context.Event()
    result_queue = context.Queue()
    processes = [
        context.Process(
            target=_payload_worker,
            args=(str(tmp_path), bundle.execution_id, start_event, result_queue),
        )
        for _ in range(2)
    ]
    for process in processes:
        process.start()
    start_event.set()
    results = [result_queue.get(timeout=20) for _ in processes]
    for process in processes:
        process.join(timeout=20)
        assert process.exitcode == 0

    assert len(set(results)) == 1
    provider = AtomicFileStateStorage(tmp_path)
    assert provider.load_payload(bundle.execution_id, results[0]) == {"worker": "shared"}
