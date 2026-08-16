"""F6.7 crash, integrity, concurrency, and retention proofs."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from ai_engineering_harness.knowledge import (
    KnowledgeTransactionConfigurationError,
    KnowledgeTransactionConflictError,
    KnowledgeTransactionIntegrityError,
    KnowledgeTransactionManager,
    TransactionState,
)
from ai_engineering_harness.persistence import (
    LockAcquisitionTimeoutError,
    canonical_json_digest,
    canonical_json_object,
)


def _git(repository: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments],
        cwd=repository,
        check=True,
        shell=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
    )


def _repository(tmp_path: Path) -> tuple[Path, str]:
    repository = tmp_path / "project"
    repository.mkdir()
    (repository / "tracked.txt").write_text("base\n", encoding="utf-8")
    _git(repository, "init", "--quiet")
    _git(repository, "config", "user.name", "Knowledge Test")
    _git(repository, "config", "user.email", "knowledge@example.invalid")
    _git(repository, "add", "--", "tracked.txt")
    _git(repository, "commit", "--quiet", "-m", "baseline")
    return repository, _git(repository, "rev-parse", "HEAD").stdout.strip().lower()


def _journal(manager: KnowledgeTransactionManager) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in manager.journal_file.read_text(encoding="utf-8").splitlines()
    ]


def _current(manager: KnowledgeTransactionManager) -> dict[str, object]:
    return json.loads(manager.current_json.read_text(encoding="utf-8"))


def _snapshot(manager: KnowledgeTransactionManager, tx_id: str) -> dict[str, object]:
    path = manager.snapshots_dir / f"{tx_id}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_transaction_publishes_verified_snapshot_pointer_and_journal(
    tmp_path: Path,
) -> None:
    repository, commit_sha = _repository(tmp_path)
    manager = KnowledgeTransactionManager(repository)

    result = manager.execute_transaction(
        "tx-one",
        {"id": "ki-auth", "content": "ADR Auth"},
        commit_sha=commit_sha,
    )

    assert result == TransactionState.COMMITTED.value
    pointer = _current(manager)
    snapshot = _snapshot(manager, "tx-one")
    records = _journal(manager)
    assert pointer["current_tx_id"] == "tx-one"
    assert pointer["previous_tx_id"] is None
    assert pointer["commit_sha"] == commit_sha
    assert pointer["index_digest"] == records[0]["index_digest"]
    assert pointer["fencing_token"] == 1
    assert snapshot == {
        "schema_version": "1.0",
        "commit_sha": commit_sha,
        "items": {"ki-auth": {"id": "ki-auth", "content": "ADR Auth"}},
    }
    assert [record["state"] for record in records] == ["PREPARED", "COMMITTED"]
    assert [record["fencing_token"] for record in records] == [1, 1]
    assert manager.resolve_repository_head() == commit_sha
    assert not (manager.staging_dir / "tx-one.json").exists()


def test_transactions_preserve_prior_kis_and_replace_only_matching_id(
    tmp_path: Path,
) -> None:
    repository, commit_sha = _repository(tmp_path)
    manager = KnowledgeTransactionManager(repository)
    manager.execute_transaction(
        "tx-one", {"id": "ki-one", "value": 1}, commit_sha=commit_sha
    )
    manager.execute_transaction(
        "tx-two", {"id": "ki-two", "value": 2}, commit_sha=commit_sha
    )
    manager.execute_transaction(
        "tx-three", {"id": "ki-one", "value": 3}, commit_sha=commit_sha
    )

    snapshot = _snapshot(manager, "tx-three")
    assert snapshot["items"] == {
        "ki-one": {"id": "ki-one", "value": 3},
        "ki-two": {"id": "ki-two", "value": 2},
    }
    assert _current(manager)["previous_tx_id"] == "tx-two"
    assert _current(manager)["fencing_token"] == 3
    prepared_tokens = [
        record["fencing_token"]
        for record in _journal(manager)
        if record["state"] == "PREPARED"
    ]
    assert prepared_tokens == [1, 2, 3]


def test_matching_committed_retry_is_idempotent_and_mismatch_is_rejected(
    tmp_path: Path,
) -> None:
    repository, commit_sha = _repository(tmp_path)
    manager = KnowledgeTransactionManager(repository)
    item = {"id": "ki-retry", "value": "same"}
    manager.execute_transaction("tx-retry", item, commit_sha=commit_sha)
    journal_before = manager.journal_file.read_bytes()
    pointer_before = manager.current_json.read_bytes()

    assert (
        manager.execute_transaction("tx-retry", item, commit_sha=commit_sha)
        == TransactionState.COMMITTED.value
    )
    assert manager.journal_file.read_bytes() == journal_before
    assert manager.current_json.read_bytes() == pointer_before

    with pytest.raises(KnowledgeTransactionConflictError, match="different KI"):
        manager.execute_transaction(
            "tx-retry",
            {"id": "ki-retry", "value": "changed"},
            commit_sha=commit_sha,
        )
    assert manager.journal_file.read_bytes() == journal_before
    assert manager.current_json.read_bytes() == pointer_before


def test_retry_reuses_matching_staging_before_prepared(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, commit_sha = _repository(tmp_path)
    manager = KnowledgeTransactionManager(repository)
    real_append = manager._append_prepared

    def interrupt_prepared(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise KeyboardInterrupt

    monkeypatch.setattr(manager, "_append_prepared", interrupt_prepared)
    with pytest.raises(KeyboardInterrupt):
        manager.execute_transaction(
            "tx-before-prepared",
            {"id": "ki-before", "value": 1},
            commit_sha=commit_sha,
        )
    assert (manager.staging_dir / "tx-before-prepared.json").is_file()
    assert not manager.journal_file.exists()

    monkeypatch.setattr(manager, "_append_prepared", real_append)
    assert (
        manager.execute_transaction(
            "tx-before-prepared",
            {"id": "ki-before", "value": 1},
            commit_sha=commit_sha,
        )
        == TransactionState.COMMITTED.value
    )
    assert [record["state"] for record in _journal(manager)] == [
        "PREPARED",
        "COMMITTED",
    ]


def test_recovery_after_prepared_completes_without_second_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, commit_sha = _repository(tmp_path)
    manager = KnowledgeTransactionManager(repository)
    real_publish = manager._publish_snapshot

    def interrupt_snapshot(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise KeyboardInterrupt

    monkeypatch.setattr(manager, "_publish_snapshot", interrupt_snapshot)
    with pytest.raises(KeyboardInterrupt):
        manager.execute_transaction(
            "tx-after-prepared",
            {"id": "ki-prepared", "value": 1},
            commit_sha=commit_sha,
        )
    staged_before = (manager.staging_dir / "tx-after-prepared.json").read_bytes()
    assert [record["state"] for record in _journal(manager)] == ["PREPARED"]

    monkeypatch.setattr(manager, "_publish_snapshot", real_publish)
    assert manager.recover_if_needed() == "RECOVERED_tx-after-prepared"
    assert not (manager.staging_dir / "tx-after-prepared.json").exists()
    assert (manager.snapshots_dir / "tx-after-prepared.json").read_bytes() == staged_before
    assert _current(manager)["fencing_token"] == 2
    assert [record["state"] for record in _journal(manager)] == [
        "PREPARED",
        "COMMITTED",
    ]


def test_recovery_after_snapshot_publish_completes_pointer_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, commit_sha = _repository(tmp_path)
    manager = KnowledgeTransactionManager(repository)
    real_publish = manager._publish_current

    def interrupt_pointer(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise KeyboardInterrupt

    monkeypatch.setattr(manager, "_publish_current", interrupt_pointer)
    with pytest.raises(KeyboardInterrupt):
        manager.execute_transaction(
            "tx-after-snapshot",
            {"id": "ki-snapshot", "value": 1},
            commit_sha=commit_sha,
        )
    assert (manager.snapshots_dir / "tx-after-snapshot.json").is_file()
    assert not manager.current_json.exists()

    monkeypatch.setattr(manager, "_publish_current", real_publish)
    assert manager.recover_if_needed() == "RECOVERED_tx-after-snapshot"
    assert _current(manager)["current_tx_id"] == "tx-after-snapshot"
    assert _current(manager)["fencing_token"] == 2


def test_recovery_after_pointer_swap_does_not_rewrite_pointer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, commit_sha = _repository(tmp_path)
    manager = KnowledgeTransactionManager(repository)
    real_publish = manager._publish_current

    def interrupt_after_pointer(*args: object, **kwargs: object) -> None:
        real_publish(*args, **kwargs)  # type: ignore[arg-type]
        raise KeyboardInterrupt

    monkeypatch.setattr(manager, "_publish_current", interrupt_after_pointer)
    with pytest.raises(KeyboardInterrupt):
        manager.execute_transaction(
            "tx-after-pointer",
            {"id": "ki-pointer", "value": 1},
            commit_sha=commit_sha,
        )
    pointer_before = manager.current_json.read_bytes()

    monkeypatch.setattr(manager, "_publish_current", real_publish)
    assert manager.recover_if_needed() == "RECOVERED_tx-after-pointer"
    assert manager.current_json.read_bytes() == pointer_before
    records = _journal(manager)
    assert [record["state"] for record in records] == ["PREPARED", "COMMITTED"]
    assert [record["fencing_token"] for record in records] == [1, 2]


def test_crash_after_committed_append_is_already_terminal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, commit_sha = _repository(tmp_path)
    manager = KnowledgeTransactionManager(repository)
    real_append = manager._append_terminal

    def interrupt_after_terminal(*args: object, **kwargs: object) -> None:
        real_append(*args, **kwargs)  # type: ignore[arg-type]
        raise KeyboardInterrupt

    monkeypatch.setattr(manager, "_append_terminal", interrupt_after_terminal)
    with pytest.raises(KeyboardInterrupt):
        manager.execute_transaction(
            "tx-after-terminal",
            {"id": "ki-terminal", "value": 1},
            commit_sha=commit_sha,
        )
    monkeypatch.setattr(manager, "_append_terminal", real_append)

    assert manager.recover_if_needed() == "CLEAN"
    assert [record["state"] for record in _journal(manager)] == [
        "PREPARED",
        "COMMITTED",
    ]


@pytest.mark.parametrize("mutation", ["missing", "corrupt"])
def test_invalid_prepared_staging_is_aborted_without_pointer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    repository, commit_sha = _repository(tmp_path)
    manager = KnowledgeTransactionManager(repository)

    def interrupt_snapshot(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise KeyboardInterrupt

    monkeypatch.setattr(manager, "_publish_snapshot", interrupt_snapshot)
    with pytest.raises(KeyboardInterrupt):
        manager.execute_transaction(
            "tx-invalid-stage",
            {"id": "ki-invalid", "value": 1},
            commit_sha=commit_sha,
        )
    staged = manager.staging_dir / "tx-invalid-stage.json"
    if mutation == "missing":
        staged.unlink()
    else:
        staged.write_bytes(b'{"corrupt":true}\n')

    assert manager.recover_if_needed() == "ABORTED_tx-invalid-stage"
    assert not manager.current_json.exists()
    records = _journal(manager)
    assert [record["state"] for record in records] == ["PREPARED", "ABORTED"]
    assert isinstance(records[-1]["reason"], str)


def test_corrupt_visible_snapshot_fails_closed_without_mutation(tmp_path: Path) -> None:
    repository, commit_sha = _repository(tmp_path)
    manager = KnowledgeTransactionManager(repository)
    manager.execute_transaction(
        "tx-visible", {"id": "ki-visible", "value": 1}, commit_sha=commit_sha
    )
    snapshot = manager.snapshots_dir / "tx-visible.json"
    snapshot.write_bytes(b'{"corrupt":true}\n')
    pointer_before = manager.current_json.read_bytes()
    journal_before = manager.journal_file.read_bytes()

    with pytest.raises(KnowledgeTransactionIntegrityError):
        manager.recover_if_needed()

    assert manager.current_json.read_bytes() == pointer_before
    assert manager.journal_file.read_bytes() == journal_before
    assert snapshot.read_bytes() == b'{"corrupt":true}\n'


def test_recovery_never_overwrites_a_valid_pointer_that_advanced(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, commit_sha = _repository(tmp_path)
    manager = KnowledgeTransactionManager(repository)
    manager.execute_transaction(
        "tx-base", {"id": "ki-base", "value": 1}, commit_sha=commit_sha
    )

    def interrupt_pointer(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise KeyboardInterrupt

    monkeypatch.setattr(manager, "_publish_current", interrupt_pointer)
    with pytest.raises(KeyboardInterrupt):
        manager.execute_transaction(
            "tx-interrupted",
            {"id": "ki-interrupted", "value": 2},
            commit_sha=commit_sha,
        )

    foreign_index = {
        "schema_version": "1.0",
        "commit_sha": commit_sha,
        "items": {
            "ki-base": {"id": "ki-base", "value": 1},
            "ki-foreign": {"id": "ki-foreign", "value": 3},
        },
    }
    canonical_index = canonical_json_object(foreign_index)
    foreign_digest = canonical_json_digest(canonical_index)
    (manager.snapshots_dir / "tx-foreign.json").write_bytes(
        canonical_index.encode("utf-8")
    )
    foreign_pointer = {
        "schema_version": "2.0",
        "current_tx_id": "tx-foreign",
        "previous_tx_id": "tx-base",
        "commit_sha": commit_sha,
        "index_digest": foreign_digest,
        "fencing_token": 2,
        "active_ki": "ki-foreign",
        "updated_at": manager._now(),
    }
    manager.current_json.write_bytes(
        canonical_json_object(foreign_pointer).encode("utf-8")
    )
    pointer_before = manager.current_json.read_bytes()

    assert manager.recover_if_needed() == "ABORTED_tx-interrupted"
    assert manager.current_json.read_bytes() == pointer_before
    assert _current(manager)["current_tx_id"] == "tx-foreign"
    interrupted = [
        record for record in _journal(manager) if record["tx_id"] == "tx-interrupted"
    ]
    assert [record["state"] for record in interrupted] == ["PREPARED", "ABORTED"]


def test_invalid_or_missing_commit_is_rejected_before_durable_state(
    tmp_path: Path,
) -> None:
    repository, _ = _repository(tmp_path)
    manager = KnowledgeTransactionManager(repository)

    with pytest.raises(KnowledgeTransactionConfigurationError, match="full"):
        manager.execute_transaction(
            "tx-short-sha", {"id": "ki-short"}, commit_sha="abc"
        )
    with pytest.raises(KnowledgeTransactionIntegrityError, match="does not exist"):
        manager.execute_transaction(
            "tx-missing-sha", {"id": "ki-missing"}, commit_sha="f" * 40
        )

    assert not manager.current_json.exists()
    assert not manager.journal_file.exists()


def test_legacy_current_is_migrated_without_losing_its_ki(tmp_path: Path) -> None:
    repository, commit_sha = _repository(tmp_path)
    manager = KnowledgeTransactionManager(repository)
    legacy_dir = manager.staging_dir / "tx-legacy"
    legacy_dir.mkdir()
    (legacy_dir / "data.json").write_text(
        json.dumps({"id": "ki-legacy", "value": "old"}), encoding="utf-8"
    )
    manager.current_json.write_text(
        json.dumps({"current_tx_id": "tx-legacy", "active_ki": "ki-legacy"}),
        encoding="utf-8",
    )

    manager.execute_transaction(
        "tx-migrated", {"id": "ki-new", "value": "new"}, commit_sha=commit_sha
    )

    assert _current(manager)["previous_tx_id"] == "tx-legacy"
    assert _snapshot(manager, "tx-migrated")["items"] == {
        "ki-legacy": {"id": "ki-legacy", "value": "old"},
        "ki-new": {"id": "ki-new", "value": "new"},
    }


def test_lock_contention_blocks_second_writer_before_effect(tmp_path: Path) -> None:
    repository, commit_sha = _repository(tmp_path)
    first = KnowledgeTransactionManager(repository, lock_timeout_seconds=0)
    second = KnowledgeTransactionManager(repository, lock_timeout_seconds=0)
    held = first._acquire_lock("held-by-test")
    try:
        with pytest.raises(LockAcquisitionTimeoutError):
            second.execute_transaction(
                "tx-contended",
                {"id": "ki-contended", "value": 1},
                commit_sha=commit_sha,
            )
    finally:
        first._locks.release(held)

    assert not first.current_json.exists()
    assert not first.journal_file.exists()


def test_stale_fencing_token_is_rejected_before_publication(tmp_path: Path) -> None:
    repository, _ = _repository(tmp_path)
    manager = KnowledgeTransactionManager(repository)
    lock = manager._acquire_lock("stale-test")
    fence_path = (
        repository
        / ".harness"
        / "state"
        / "locks"
        / "knowledge-transaction.fence"
    )
    fence_path.write_text(f"{lock.fencing_token + 1}\n", encoding="ascii")
    try:
        with pytest.raises(KnowledgeTransactionConflictError, match="stale"):
            manager._require_current_fence(lock)
    finally:
        manager._locks.release(lock)


def test_retention_removes_only_old_committed_snapshots(tmp_path: Path) -> None:
    repository, commit_sha = _repository(tmp_path)
    manager = KnowledgeTransactionManager(repository, retention_limit=2)
    for number in range(1, 4):
        manager.execute_transaction(
            f"tx-{number}",
            {"id": f"ki-{number}", "value": number},
            commit_sha=commit_sha,
        )

    assert manager.cleanup_retained_snapshots() == ("tx-1",)
    assert not (manager.snapshots_dir / "tx-1.json").exists()
    assert (manager.snapshots_dir / "tx-2.json").is_file()
    assert (manager.snapshots_dir / "tx-3.json").is_file()
    assert set(_snapshot(manager, "tx-3")["items"]) == {"ki-1", "ki-2", "ki-3"}


def test_corrupt_journal_is_rejected_without_repair(tmp_path: Path) -> None:
    repository, _ = _repository(tmp_path)
    manager = KnowledgeTransactionManager(repository)
    manager.journal_file.write_bytes(b'{"tx_id":"broken"}')
    before = manager.journal_file.read_bytes()

    with pytest.raises(KnowledgeTransactionIntegrityError, match="newline"):
        manager.recover_if_needed()

    assert manager.journal_file.read_bytes() == before
