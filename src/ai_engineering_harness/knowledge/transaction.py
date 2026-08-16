"""Crash-safe knowledge transactions with durable fencing and verified recovery."""

from __future__ import annotations

import json
import math
import os
import re
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any, ClassVar

from ai_engineering_harness.persistence import (
    ExecutionLock,
    canonical_json_digest,
    canonical_json_object,
)
from ai_engineering_harness.persistence.locks import CrossProcessLockManager


class KnowledgeTransactionError(RuntimeError):
    """Base error for durable knowledge transaction failures."""


class KnowledgeTransactionConfigurationError(KnowledgeTransactionError):
    """Raised when a transaction input or manager option is invalid."""


class KnowledgeTransactionIntegrityError(KnowledgeTransactionError):
    """Raised when persisted knowledge bytes cannot be trusted."""


class KnowledgeTransactionConflictError(KnowledgeTransactionError):
    """Raised when durable state belongs to a different operation."""


class KnowledgeTransactionRecoveryError(KnowledgeTransactionError):
    """Raised when an interrupted effect cannot be reconciled safely."""


class KnowledgeTransactionWriteError(KnowledgeTransactionError):
    """Raised when knowledge state cannot be published atomically."""


class TransactionState(str, Enum):
    """Durable states accepted by the knowledge transaction journal."""

    STAGING = "STAGING"
    VALIDATED = "VALIDATED"
    PREPARED = "PREPARED"
    COMMITTED = "COMMITTED"
    ABORTED = "ABORTED"


@dataclass(frozen=True, slots=True)
class _PreparedTransaction:
    tx_id: str
    commit_sha: str
    index_digest: str
    previous_tx_id: str | None
    active_ki: str
    fencing_token: int


@dataclass(frozen=True, slots=True)
class _CurrentKnowledge:
    tx_id: str
    previous_tx_id: str | None
    commit_sha: str | None
    index_digest: str | None
    fencing_token: int
    active_ki: str
    items: dict[str, dict[str, Any]]
    legacy: bool


class KnowledgeTransactionManager:
    """Publish immutable knowledge snapshots behind one atomic current pointer."""

    JOURNAL_SCHEMA_VERSION: ClassVar[str] = "2.0"
    POINTER_SCHEMA_VERSION: ClassVar[str] = "2.0"
    INDEX_SCHEMA_VERSION: ClassVar[str] = "1.0"
    _GLOBAL_LOCK_ID: ClassVar[str] = "knowledge-transaction"
    _TX_ID: ClassVar[re.Pattern[str]] = re.compile(
        r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$"
    )
    _FULL_SHA: ClassVar[re.Pattern[str]] = re.compile(r"^[0-9a-f]{40}$")
    _DIGEST: ClassVar[re.Pattern[str]] = re.compile(r"^sha256:[0-9a-f]{64}$")
    _POINTER_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema_version",
            "current_tx_id",
            "previous_tx_id",
            "commit_sha",
            "index_digest",
            "fencing_token",
            "active_ki",
            "updated_at",
        }
    )
    _JOURNAL_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema_version",
            "tx_id",
            "state",
            "commit_sha",
            "index_digest",
            "previous_tx_id",
            "active_ki",
            "fencing_token",
            "timestamp",
            "reason",
        }
    )

    def __init__(
        self,
        project_root: Path,
        *,
        git_executable: str = "git",
        lock_timeout_seconds: float = 5.0,
        retention_limit: int = 5,
    ) -> None:
        try:
            root = Path(project_root).resolve(strict=True)
        except (OSError, RuntimeError, ValueError, TypeError) as exc:
            raise KnowledgeTransactionConfigurationError(
                "project_root must resolve to an existing directory"
            ) from exc
        if not root.is_dir():
            raise KnowledgeTransactionConfigurationError(
                "project_root must resolve to an existing directory"
            )
        if type(git_executable) is not str or not git_executable.strip():
            raise KnowledgeTransactionConfigurationError(
                "git_executable must be a non-empty string"
            )
        if "\x00" in git_executable:
            raise KnowledgeTransactionConfigurationError(
                "git_executable contains a null byte"
            )
        if (
            isinstance(lock_timeout_seconds, bool)
            or not isinstance(lock_timeout_seconds, (int, float))
            or not math.isfinite(lock_timeout_seconds)
            or lock_timeout_seconds < 0
        ):
            raise KnowledgeTransactionConfigurationError(
                "lock_timeout_seconds must be finite and non-negative"
            )
        if type(retention_limit) is not int or retention_limit < 1:
            raise KnowledgeTransactionConfigurationError(
                "retention_limit must be a positive integer"
            )

        self.project_root = root
        self.git_executable = git_executable
        self.lock_timeout_seconds = float(lock_timeout_seconds)
        self.retention_limit = retention_limit
        self.knw_dir = root / ".harness" / "knowledge"
        self.staging_dir = self.knw_dir / "staging"
        self.snapshots_dir = self.knw_dir / "snapshots"
        self.current_json = self.knw_dir / "current.json"
        self.journal_file = self.knw_dir / "transaction_journal.jsonl"
        for managed_path in (
            self.knw_dir,
            self.staging_dir,
            self.snapshots_dir,
            self.current_json,
            self.journal_file,
        ):
            self._require_confined(managed_path)
        try:
            self.staging_dir.mkdir(parents=True, exist_ok=True)
            self.snapshots_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise KnowledgeTransactionConfigurationError(
                "knowledge storage directories cannot be created"
            ) from exc
        self._locks = CrossProcessLockManager(root)

    def resolve_repository_head(self) -> str:
        """Return the repository HEAD as a verified full commit SHA."""

        result = self._run_git(("rev-parse", "--verify", "HEAD^{commit}"))
        commit_sha = result.stdout.strip().lower()
        self._require_commit_exists(commit_sha)
        return commit_sha

    def execute_transaction(
        self,
        tx_id: str,
        new_ki: dict[str, Any],
        *,
        commit_sha: str,
    ) -> str:
        """Merge one KI into a verified snapshot and atomically publish its pointer."""

        validated_tx_id = self._validate_identifier(tx_id, label="tx_id")
        validated_ki = self._validate_ki(new_ki)
        validated_sha = self._validate_commit_sha(commit_sha)
        self._require_commit_exists(validated_sha)

        lock = self._acquire_lock("execute")
        try:
            self._recover_locked(lock)
            return self._execute_locked(
                validated_tx_id,
                validated_ki,
                commit_sha=validated_sha,
                lock=lock,
            )
        finally:
            self._locks.release(lock)

    def recover_if_needed(self) -> str:
        """Complete or abort one proven interrupted transaction under a fresh fence."""

        lock = self._acquire_lock("recover")
        try:
            return self._recover_locked(lock)
        finally:
            self._locks.release(lock)

    def cleanup_retained_snapshots(self) -> tuple[str, ...]:
        """Remove only old committed snapshots beyond the configured retention limit."""

        lock = self._acquire_lock("retention")
        try:
            self._recover_locked(lock)
            current = self._load_current()
            records = self._read_journal()
            committed_order = [
                record["tx_id"]
                for record in records
                if record.get("state") == TransactionState.COMMITTED.value
                and type(record.get("tx_id")) is str
            ]
            keep = set(committed_order[-self.retention_limit :])
            if current is not None:
                keep.add(current.tx_id)
            committed = set(committed_order)
            removed: list[str] = []
            for path in sorted(
                self.snapshots_dir.glob("*.json"), key=lambda item: item.name
            ):
                tx_id = path.stem
                if self._TX_ID.fullmatch(tx_id) is None:
                    continue
                if tx_id not in committed or tx_id in keep:
                    continue
                self._require_confined(path)
                try:
                    path.unlink()
                    self._fsync_directory(path.parent)
                except OSError as exc:
                    raise KnowledgeTransactionWriteError(
                        "retained snapshot could not be removed safely"
                    ) from exc
                removed.append(tx_id)
            return tuple(removed)
        finally:
            self._locks.release(lock)

    def _execute_locked(
        self,
        tx_id: str,
        new_ki: dict[str, Any],
        *,
        commit_sha: str,
        lock: ExecutionLock,
    ) -> str:
        self._require_current_fence(lock)
        records = self._read_journal()
        tx_records = [record for record in records if record.get("tx_id") == tx_id]
        if tx_records:
            final_state = tx_records[-1].get("state")
            if final_state == TransactionState.COMMITTED.value:
                self._validate_committed_retry(
                    tx_id,
                    new_ki,
                    commit_sha=commit_sha,
                    record=tx_records[-1],
                )
                return TransactionState.COMMITTED.value
            raise KnowledgeTransactionConflictError(
                "transaction identifier already has durable non-committed history"
            )

        current = self._load_current()
        items = {} if current is None else dict(current.items)
        active_ki = new_ki["id"]
        items[active_ki] = new_ki
        index = {
            "schema_version": self.INDEX_SCHEMA_VERSION,
            "commit_sha": commit_sha,
            "items": items,
        }
        canonical_index = canonical_json_object(index)
        index_digest = canonical_json_digest(canonical_index)
        staged_path = self._staged_path(tx_id)
        snapshot_path = self._snapshot_path(tx_id)
        if snapshot_path.exists():
            raise KnowledgeTransactionConflictError(
                "transaction path already exists without matching durable history"
            )
        if not staged_path.exists():
            self._publish_staging(staged_path, canonical_index.encode("utf-8"))
        self._load_index(
            staged_path,
            expected_digest=index_digest,
            expected_commit_sha=commit_sha,
        )
        prepared = _PreparedTransaction(
            tx_id=tx_id,
            commit_sha=commit_sha,
            index_digest=index_digest,
            previous_tx_id=None if current is None else current.tx_id,
            active_ki=active_ki,
            fencing_token=lock.fencing_token,
        )
        self._append_prepared(prepared)
        self._require_current_fence(lock)
        self._publish_snapshot(staged_path, snapshot_path)
        self._load_index(
            snapshot_path,
            expected_digest=index_digest,
            expected_commit_sha=commit_sha,
        )
        self._require_current_fence(lock)
        self._publish_current(prepared, fencing_token=lock.fencing_token)
        self._require_current_fence(lock)
        self._append_terminal(
            prepared,
            state=TransactionState.COMMITTED,
            fencing_token=lock.fencing_token,
            reason=None,
        )
        return TransactionState.COMMITTED.value

    def _recover_locked(self, lock: ExecutionLock) -> str:
        self._require_current_fence(lock)
        records = self._read_journal()
        unresolved = self._unresolved_prepared(records)
        if not unresolved:
            self._load_current()
            return "CLEAN"
        if len(unresolved) != 1:
            raise KnowledgeTransactionRecoveryError(
                "multiple unresolved PREPARED transactions require intervention"
            )

        record = unresolved[0]
        tx_id = self._validate_persisted_identifier(
            record.get("tx_id"), label="journal tx_id"
        )
        if record.get("schema_version") != self.JOURNAL_SCHEMA_VERSION:
            prepared = _PreparedTransaction(
                tx_id=tx_id,
                commit_sha="0" * 40,
                index_digest="sha256:" + "0" * 64,
                previous_tx_id=None,
                active_ki="legacy-unknown",
                fencing_token=lock.fencing_token,
            )
            self._append_terminal(
                prepared,
                state=TransactionState.ABORTED,
                fencing_token=lock.fencing_token,
                reason="legacy_prepared_missing_verified_metadata",
            )
            return f"ABORTED_{tx_id}"

        prepared = self._prepared_from_record(record)
        current = self._load_current()
        pointer_is_transaction = current is not None and current.tx_id == prepared.tx_id
        try:
            self._require_commit_exists(prepared.commit_sha)
        except KnowledgeTransactionIntegrityError:
            if pointer_is_transaction:
                raise
            return self._abort_recovery(
                prepared,
                lock=lock,
                reason="prepared_commit_is_missing_or_invalid",
            )

        staged_path = self._staged_path(prepared.tx_id)
        snapshot_path = self._snapshot_path(prepared.tx_id)
        staged_exists = staged_path.is_file()
        snapshot_exists = snapshot_path.is_file()
        if staged_exists and snapshot_exists:
            raise KnowledgeTransactionRecoveryError(
                "both staging and snapshot exist for one PREPARED transaction"
            )
        if not staged_exists and not snapshot_exists:
            if pointer_is_transaction:
                raise KnowledgeTransactionIntegrityError(
                    "current pointer references a missing prepared snapshot"
                )
            return self._abort_recovery(
                prepared,
                lock=lock,
                reason="prepared_snapshot_and_staging_are_missing",
            )

        source = snapshot_path if snapshot_exists else staged_path
        try:
            index = self._load_index(
                source,
                expected_digest=prepared.index_digest,
                expected_commit_sha=prepared.commit_sha,
            )
        except KnowledgeTransactionIntegrityError:
            if pointer_is_transaction:
                raise
            return self._abort_recovery(
                prepared,
                lock=lock,
                reason="prepared_index_failed_validation",
            )
        if prepared.active_ki not in index["items"]:
            if pointer_is_transaction:
                raise KnowledgeTransactionIntegrityError(
                    "current prepared snapshot is missing its active KI"
                )
            return self._abort_recovery(
                prepared,
                lock=lock,
                reason="prepared_index_missing_active_ki",
            )

        if pointer_is_transaction:
            assert current is not None
            self._validate_current_matches_prepared(current, prepared)
        else:
            observed_previous = None if current is None else current.tx_id
            if observed_previous != prepared.previous_tx_id:
                return self._abort_recovery(
                    prepared,
                    lock=lock,
                    reason="current_pointer_advanced_past_prepared_predecessor",
                )
            self._require_current_fence(lock)
            if staged_exists:
                self._publish_snapshot(staged_path, snapshot_path)
            self._load_index(
                snapshot_path,
                expected_digest=prepared.index_digest,
                expected_commit_sha=prepared.commit_sha,
            )
            self._require_current_fence(lock)
            self._publish_current(prepared, fencing_token=lock.fencing_token)

        self._require_current_fence(lock)
        self._append_terminal(
            prepared,
            state=TransactionState.COMMITTED,
            fencing_token=lock.fencing_token,
            reason=None,
        )
        return f"RECOVERED_{prepared.tx_id}"

    def _abort_recovery(
        self,
        prepared: _PreparedTransaction,
        *,
        lock: ExecutionLock,
        reason: str,
    ) -> str:
        current = self._load_current()
        if current is not None and current.tx_id == prepared.tx_id:
            raise KnowledgeTransactionRecoveryError(
                "cannot abort a transaction already visible through current.json"
            )
        self._require_current_fence(lock)
        self._append_terminal(
            prepared,
            state=TransactionState.ABORTED,
            fencing_token=lock.fencing_token,
            reason=reason,
        )
        return f"ABORTED_{prepared.tx_id}"

    def _validate_committed_retry(
        self,
        tx_id: str,
        new_ki: dict[str, Any],
        *,
        commit_sha: str,
        record: dict[str, Any],
    ) -> None:
        if record.get("schema_version") != self.JOURNAL_SCHEMA_VERSION:
            raise KnowledgeTransactionConflictError(
                "legacy committed transaction cannot be retried idempotently"
            )
        prepared = self._prepared_from_record(record)
        if prepared.commit_sha != commit_sha:
            raise KnowledgeTransactionConflictError(
                "committed transaction retry uses a different commit SHA"
            )
        snapshot = self._load_index(
            self._snapshot_path(tx_id),
            expected_digest=prepared.index_digest,
            expected_commit_sha=commit_sha,
        )
        if snapshot["items"].get(new_ki["id"]) != new_ki:
            raise KnowledgeTransactionConflictError(
                "committed transaction retry uses different KI content"
            )

    def _publish_staging(self, destination: Path, content: bytes) -> None:
        self._atomic_write(destination, content)

    def _append_prepared(self, prepared: _PreparedTransaction) -> None:
        self._append_journal_record(
            self._journal_record(
                prepared,
                state=TransactionState.PREPARED,
                fencing_token=prepared.fencing_token,
                reason=None,
            )
        )

    def _publish_snapshot(self, staged_path: Path, snapshot_path: Path) -> None:
        self._require_confined(staged_path)
        self._require_confined(snapshot_path)
        if snapshot_path.exists():
            raise KnowledgeTransactionConflictError(
                "immutable knowledge snapshot already exists"
            )
        try:
            os.replace(staged_path, snapshot_path)
            self._fsync_directory(staged_path.parent)
            self._fsync_directory(snapshot_path.parent)
        except OSError as exc:
            raise KnowledgeTransactionWriteError(
                "staged knowledge snapshot could not be published"
            ) from exc

    def _publish_current(
        self,
        prepared: _PreparedTransaction,
        *,
        fencing_token: int,
    ) -> None:
        current = self._load_current()
        observed_previous = None if current is None else current.tx_id
        if observed_previous != prepared.previous_tx_id:
            raise KnowledgeTransactionConflictError(
                "current pointer no longer matches the prepared predecessor"
            )
        pointer = {
            "schema_version": self.POINTER_SCHEMA_VERSION,
            "current_tx_id": prepared.tx_id,
            "previous_tx_id": prepared.previous_tx_id,
            "commit_sha": prepared.commit_sha,
            "index_digest": prepared.index_digest,
            "fencing_token": fencing_token,
            "active_ki": prepared.active_ki,
            "updated_at": self._now(),
        }
        self._atomic_write(
            self.current_json,
            canonical_json_object(pointer).encode("utf-8"),
        )

    def _append_terminal(
        self,
        prepared: _PreparedTransaction,
        *,
        state: TransactionState,
        fencing_token: int,
        reason: str | None,
    ) -> None:
        if state not in {TransactionState.COMMITTED, TransactionState.ABORTED}:
            raise KnowledgeTransactionConfigurationError(
                "terminal journal state is invalid"
            )
        self._append_journal_record(
            self._journal_record(
                prepared,
                state=state,
                fencing_token=fencing_token,
                reason=reason,
            )
        )

    def _append_journal_record(self, record: dict[str, Any]) -> None:
        records = self._read_journal()
        self._validate_new_journal_record(record)
        line = (
            json.dumps(
                record,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
        existing = b""
        if records:
            try:
                existing = self.journal_file.read_bytes()
            except OSError as exc:
                raise KnowledgeTransactionIntegrityError(
                    "knowledge journal cannot be reread before append"
                ) from exc
        self._atomic_write(self.journal_file, existing + line)

    def _read_journal(self) -> list[dict[str, Any]]:
        try:
            raw = self.journal_file.read_bytes()
        except FileNotFoundError:
            return []
        except OSError as exc:
            raise KnowledgeTransactionIntegrityError(
                "knowledge journal cannot be read"
            ) from exc
        if not raw or not raw.endswith(b"\n"):
            raise KnowledgeTransactionIntegrityError(
                "knowledge journal is empty or not newline terminated"
            )
        try:
            text = raw.decode("utf-8", errors="strict")
        except UnicodeError as exc:
            raise KnowledgeTransactionIntegrityError(
                "knowledge journal is not valid UTF-8"
            ) from exc
        records: list[dict[str, Any]] = []
        for line_number, line in enumerate(text.splitlines(), start=1):
            try:
                payload = json.loads(
                    line,
                    object_pairs_hook=self._reject_duplicate_keys,
                    parse_constant=self._reject_constant,
                )
            except (json.JSONDecodeError, KnowledgeTransactionIntegrityError) as exc:
                raise KnowledgeTransactionIntegrityError(
                    f"knowledge journal line {line_number} is invalid"
                ) from exc
            if type(payload) is not dict:
                raise KnowledgeTransactionIntegrityError(
                    f"knowledge journal line {line_number} is not an object"
                )
            if set(payload) == {"tx_id", "state"}:
                self._validate_legacy_journal_record(payload)
            else:
                self._validate_new_journal_record(payload)
                canonical_line = json.dumps(
                    payload,
                    ensure_ascii=False,
                    allow_nan=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                if line != canonical_line:
                    raise KnowledgeTransactionIntegrityError(
                        f"knowledge journal line {line_number} is not canonical"
                    )
            records.append(payload)
        self._validate_journal_history(records)
        return records

    def _validate_journal_history(self, records: list[dict[str, Any]]) -> None:
        states: dict[str, TransactionState] = {}
        for record in records:
            tx_id = self._validate_persisted_identifier(
                record.get("tx_id"), label="journal tx_id"
            )
            state = TransactionState(record["state"])
            previous = states.get(tx_id)
            if state is TransactionState.PREPARED:
                if previous is not None:
                    raise KnowledgeTransactionIntegrityError(
                        "knowledge transaction has duplicate PREPARED history"
                    )
            elif state in {TransactionState.COMMITTED, TransactionState.ABORTED}:
                if previous is not TransactionState.PREPARED:
                    raise KnowledgeTransactionIntegrityError(
                        "knowledge terminal state is not preceded by PREPARED"
                    )
            else:
                raise KnowledgeTransactionIntegrityError(
                    "knowledge journal contains a non-durable intermediate state"
                )
            states[tx_id] = state

    def _unresolved_prepared(
        self,
        records: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        latest: dict[str, dict[str, Any]] = {}
        order: list[str] = []
        for record in records:
            tx_id = record["tx_id"]
            if tx_id not in latest:
                order.append(tx_id)
            latest[tx_id] = record
        return [
            latest[tx_id]
            for tx_id in order
            if latest[tx_id]["state"] == TransactionState.PREPARED.value
        ]

    def _load_current(self) -> _CurrentKnowledge | None:
        try:
            raw = self.current_json.read_bytes()
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise KnowledgeTransactionIntegrityError(
                "current knowledge pointer cannot be read"
            ) from exc
        payload = self._parse_json_object(raw, label="current knowledge pointer")
        if set(payload) == {"current_tx_id", "active_ki"}:
            return self._load_legacy_current(payload)
        if set(payload) != self._POINTER_FIELDS:
            raise KnowledgeTransactionIntegrityError(
                "current knowledge pointer fields do not match schema 2.0"
            )
        if payload.get("schema_version") != self.POINTER_SCHEMA_VERSION:
            raise KnowledgeTransactionIntegrityError(
                "current knowledge pointer schema is unsupported"
            )
        canonical = canonical_json_object(payload).encode("utf-8")
        if raw != canonical:
            raise KnowledgeTransactionIntegrityError(
                "current knowledge pointer is not canonical"
            )
        tx_id = self._validate_persisted_identifier(
            payload.get("current_tx_id"), label="current tx_id"
        )
        previous = payload.get("previous_tx_id")
        if previous is not None:
            previous = self._validate_persisted_identifier(
                previous, label="previous tx_id"
            )
            if previous == tx_id:
                raise KnowledgeTransactionIntegrityError(
                    "current knowledge pointer cannot reference itself as predecessor"
                )
        commit_sha = self._validate_persisted_commit(payload.get("commit_sha"))
        self._require_commit_exists(commit_sha)
        index_digest = self._validate_digest(payload.get("index_digest"))
        fencing_token = payload.get("fencing_token")
        if type(fencing_token) is not int or fencing_token < 1:
            raise KnowledgeTransactionIntegrityError(
                "current knowledge fencing token is invalid"
            )
        active_ki = self._validate_persisted_identifier(
            payload.get("active_ki"), label="active_ki"
        )
        self._validate_timestamp(payload.get("updated_at"))
        index = self._load_index(
            self._snapshot_path(tx_id),
            expected_digest=index_digest,
            expected_commit_sha=commit_sha,
        )
        if active_ki not in index["items"]:
            raise KnowledgeTransactionIntegrityError(
                "current knowledge snapshot is missing its active KI"
            )
        return _CurrentKnowledge(
            tx_id=tx_id,
            previous_tx_id=previous,
            commit_sha=commit_sha,
            index_digest=index_digest,
            fencing_token=fencing_token,
            active_ki=active_ki,
            items=index["items"],
            legacy=False,
        )

    def _load_legacy_current(self, payload: dict[str, Any]) -> _CurrentKnowledge:
        tx_id = self._validate_persisted_identifier(
            payload.get("current_tx_id"), label="legacy tx_id"
        )
        active_ki = self._validate_persisted_identifier(
            payload.get("active_ki"), label="legacy active_ki"
        )
        legacy_data = self.staging_dir / tx_id / "data.json"
        self._require_confined(legacy_data)
        try:
            raw = legacy_data.read_bytes()
        except OSError as exc:
            raise KnowledgeTransactionIntegrityError(
                "legacy current pointer has no verifiable staging data"
            ) from exc
        item = self._parse_json_object(raw, label="legacy knowledge item")
        try:
            validated = self._validate_ki(item)
        except KnowledgeTransactionConfigurationError as exc:
            raise KnowledgeTransactionIntegrityError(
                "legacy knowledge item is invalid"
            ) from exc
        if validated["id"] != active_ki:
            raise KnowledgeTransactionIntegrityError(
                "legacy current pointer active KI does not match staging"
            )
        return _CurrentKnowledge(
            tx_id=tx_id,
            previous_tx_id=None,
            commit_sha=None,
            index_digest=None,
            fencing_token=0,
            active_ki=active_ki,
            items={active_ki: validated},
            legacy=True,
        )

    def _load_index(
        self,
        path: Path,
        *,
        expected_digest: str,
        expected_commit_sha: str,
    ) -> dict[str, Any]:
        self._require_confined(path)
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise KnowledgeTransactionIntegrityError(
                "knowledge index cannot be read"
            ) from exc
        payload = self._parse_json_object(raw, label="knowledge index")
        if set(payload) != {"schema_version", "commit_sha", "items"}:
            raise KnowledgeTransactionIntegrityError(
                "knowledge index fields do not match schema 1.0"
            )
        if payload.get("schema_version") != self.INDEX_SCHEMA_VERSION:
            raise KnowledgeTransactionIntegrityError(
                "knowledge index schema is unsupported"
            )
        commit_sha = self._validate_persisted_commit(payload.get("commit_sha"))
        if commit_sha != expected_commit_sha:
            raise KnowledgeTransactionIntegrityError(
                "knowledge index commit SHA does not match durable metadata"
            )
        items = payload.get("items")
        if type(items) is not dict or not items:
            raise KnowledgeTransactionIntegrityError(
                "knowledge index must contain at least one KI"
            )
        validated_items: dict[str, dict[str, Any]] = {}
        for key, value in items.items():
            try:
                item_id = self._validate_identifier(key, label="knowledge item key")
                validated = self._validate_ki(value)
            except KnowledgeTransactionConfigurationError as exc:
                raise KnowledgeTransactionIntegrityError(
                    "persisted knowledge item is invalid"
                ) from exc
            if validated["id"] != item_id:
                raise KnowledgeTransactionIntegrityError(
                    "knowledge item key does not match its id"
                )
            validated_items[item_id] = validated
        detached = {
            "schema_version": self.INDEX_SCHEMA_VERSION,
            "commit_sha": commit_sha,
            "items": validated_items,
        }
        canonical = canonical_json_object(detached)
        if raw != canonical.encode("utf-8"):
            raise KnowledgeTransactionIntegrityError(
                "knowledge index is not canonical"
            )
        observed_digest = canonical_json_digest(canonical)
        if observed_digest != expected_digest:
            raise KnowledgeTransactionIntegrityError(
                "knowledge index digest does not match durable metadata"
            )
        return detached

    def _validate_current_matches_prepared(
        self,
        current: _CurrentKnowledge,
        prepared: _PreparedTransaction,
    ) -> None:
        if (
            current.legacy
            or current.previous_tx_id != prepared.previous_tx_id
            or current.commit_sha != prepared.commit_sha
            or current.index_digest != prepared.index_digest
            or current.active_ki != prepared.active_ki
        ):
            raise KnowledgeTransactionRecoveryError(
                "current pointer diverges from its PREPARED transaction"
            )

    def _prepared_from_record(self, record: dict[str, Any]) -> _PreparedTransaction:
        return _PreparedTransaction(
            tx_id=self._validate_persisted_identifier(
                record.get("tx_id"), label="prepared tx_id"
            ),
            commit_sha=self._validate_persisted_commit(record.get("commit_sha")),
            index_digest=self._validate_digest(record.get("index_digest")),
            previous_tx_id=self._validate_persisted_optional_identifier(
                record.get("previous_tx_id"), label="prepared previous tx_id"
            ),
            active_ki=self._validate_persisted_identifier(
                record.get("active_ki"), label="prepared active_ki"
            ),
            fencing_token=self._validate_fencing_token(record.get("fencing_token")),
        )

    def _journal_record(
        self,
        prepared: _PreparedTransaction,
        *,
        state: TransactionState,
        fencing_token: int,
        reason: str | None,
    ) -> dict[str, Any]:
        return {
            "schema_version": self.JOURNAL_SCHEMA_VERSION,
            "tx_id": prepared.tx_id,
            "state": state.value,
            "commit_sha": prepared.commit_sha,
            "index_digest": prepared.index_digest,
            "previous_tx_id": prepared.previous_tx_id,
            "active_ki": prepared.active_ki,
            "fencing_token": fencing_token,
            "timestamp": self._now(),
            "reason": reason,
        }

    def _validate_new_journal_record(self, record: dict[str, Any]) -> None:
        if set(record) != self._JOURNAL_FIELDS:
            raise KnowledgeTransactionIntegrityError(
                "knowledge journal fields do not match schema 2.0"
            )
        if record.get("schema_version") != self.JOURNAL_SCHEMA_VERSION:
            raise KnowledgeTransactionIntegrityError(
                "knowledge journal schema is unsupported"
            )
        self._validate_persisted_identifier(
            record.get("tx_id"), label="journal tx_id"
        )
        try:
            state = TransactionState(record.get("state"))
        except (TypeError, ValueError) as exc:
            raise KnowledgeTransactionIntegrityError(
                "knowledge journal state is invalid"
            ) from exc
        if state not in {
            TransactionState.PREPARED,
            TransactionState.COMMITTED,
            TransactionState.ABORTED,
        }:
            raise KnowledgeTransactionIntegrityError(
                "knowledge journal state is not durable"
            )
        self._validate_persisted_commit(record.get("commit_sha"))
        self._validate_digest(record.get("index_digest"))
        self._validate_persisted_optional_identifier(
            record.get("previous_tx_id"), label="journal previous tx_id"
        )
        self._validate_persisted_identifier(
            record.get("active_ki"), label="journal active_ki"
        )
        self._validate_fencing_token(record.get("fencing_token"))
        self._validate_timestamp(record.get("timestamp"))
        reason = record.get("reason")
        if state is TransactionState.ABORTED:
            if type(reason) is not str or not reason or len(reason) > 256:
                raise KnowledgeTransactionIntegrityError(
                    "ABORTED knowledge journal record requires a reason"
                )
        elif reason is not None:
            raise KnowledgeTransactionIntegrityError(
                "non-aborted knowledge journal record cannot contain a reason"
            )

    def _validate_legacy_journal_record(self, record: dict[str, Any]) -> None:
        self._validate_persisted_identifier(
            record.get("tx_id"), label="legacy journal tx_id"
        )
        if record.get("state") not in {
            TransactionState.PREPARED.value,
            TransactionState.COMMITTED.value,
        }:
            raise KnowledgeTransactionIntegrityError(
                "legacy knowledge journal state is invalid"
            )

    def _acquire_lock(self, operation: str) -> ExecutionLock:
        return self._locks.acquire(
            self._GLOBAL_LOCK_ID,
            f"knowledge:{operation}:{uuid.uuid4().hex}",
            timeout_seconds=self.lock_timeout_seconds,
        )

    def _require_current_fence(self, lock: ExecutionLock) -> None:
        self._locks.validate(lock, self._GLOBAL_LOCK_ID)
        fence_path = (
            self.project_root
            / ".harness"
            / "state"
            / "locks"
            / f"{self._GLOBAL_LOCK_ID}.fence"
        )
        self._require_confined(fence_path)
        try:
            raw = fence_path.read_bytes()
        except OSError as exc:
            raise KnowledgeTransactionIntegrityError(
                "knowledge fencing token cannot be read"
            ) from exc
        if raw != f"{lock.fencing_token}\n".encode("ascii"):
            raise KnowledgeTransactionConflictError(
                "knowledge writer holds a stale fencing token"
            )

    def _run_git(self, arguments: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        try:
            result = subprocess.run(
                [self.git_executable, *arguments],
                cwd=self.project_root,
                check=False,
                shell=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30.0,
                env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
            raise KnowledgeTransactionConfigurationError(
                "Git cannot verify the knowledge commit"
            ) from exc
        if result.returncode != 0:
            raise KnowledgeTransactionIntegrityError(
                "knowledge commit does not exist in the project repository"
            )
        return result

    def _require_commit_exists(self, commit_sha: str) -> None:
        validated = self._validate_commit_sha(commit_sha)
        root_result = self._run_git(("rev-parse", "--show-toplevel"))
        try:
            repository_root = Path(root_result.stdout.strip()).resolve(strict=True)
        except (OSError, RuntimeError, ValueError) as exc:
            raise KnowledgeTransactionIntegrityError(
                "project Git root cannot be resolved"
            ) from exc
        if repository_root != self.project_root:
            raise KnowledgeTransactionConfigurationError(
                "project_root must be the exact Git repository root"
            )
        self._run_git(("cat-file", "-e", f"{validated}^{{commit}}"))

    def _atomic_write(self, destination: Path, content: bytes) -> None:
        self._require_confined(destination)
        descriptor: int | None = None
        temp_path: Path | None = None
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            descriptor, raw_temp_path = tempfile.mkstemp(
                prefix=f".{destination.name}.",
                suffix=".tmp",
                dir=destination.parent,
            )
            temp_path = Path(raw_temp_path)
            with os.fdopen(descriptor, "wb") as stream:
                descriptor = None
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_path, destination)
            temp_path = None
            self._fsync_directory(destination.parent)
        except OSError as exc:
            raise KnowledgeTransactionWriteError(
                "knowledge state could not be published atomically"
            ) from exc
        finally:
            if descriptor is not None:
                os.close(descriptor)
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass

    def _parse_json_object(self, raw: bytes, *, label: str) -> dict[str, Any]:
        try:
            text = raw.decode("utf-8", errors="strict")
            payload = json.loads(
                text,
                object_pairs_hook=self._reject_duplicate_keys,
                parse_constant=self._reject_constant,
            )
        except (UnicodeError, json.JSONDecodeError, KnowledgeTransactionIntegrityError) as exc:
            raise KnowledgeTransactionIntegrityError(f"{label} is invalid JSON") from exc
        if type(payload) is not dict:
            raise KnowledgeTransactionIntegrityError(f"{label} must be an object")
        return payload

    def _validate_ki(self, value: object) -> dict[str, Any]:
        try:
            canonical = canonical_json_object(value)
            detached = json.loads(canonical)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise KnowledgeTransactionConfigurationError(
                "knowledge item must be a finite JSON object"
            ) from exc
        if type(detached) is not dict:
            raise KnowledgeTransactionConfigurationError(
                "knowledge item must be an exact JSON object"
            )
        self._validate_identifier(detached.get("id"), label="knowledge item id")
        return detached

    @classmethod
    def _validate_identifier(cls, value: object, *, label: str) -> str:
        if type(value) is not str or cls._TX_ID.fullmatch(value) is None:
            raise KnowledgeTransactionConfigurationError(
                f"{label} contains unsafe characters or length"
            )
        if ".." in value or value.endswith(".") or value.casefold().endswith(".lock"):
            raise KnowledgeTransactionConfigurationError(f"{label} is unsafe")
        return value

    @classmethod
    def _validate_persisted_identifier(cls, value: object, *, label: str) -> str:
        try:
            return cls._validate_identifier(value, label=label)
        except KnowledgeTransactionConfigurationError as exc:
            raise KnowledgeTransactionIntegrityError(
                f"persisted {label} is invalid"
            ) from exc

    @classmethod
    def _validate_persisted_optional_identifier(
        cls,
        value: object,
        *,
        label: str,
    ) -> str | None:
        if value is None:
            return None
        return cls._validate_persisted_identifier(value, label=label)

    @classmethod
    def _validate_commit_sha(cls, value: object) -> str:
        if type(value) is not str or cls._FULL_SHA.fullmatch(value.lower()) is None:
            raise KnowledgeTransactionConfigurationError(
                "commit_sha must be a full hexadecimal SHA"
            )
        return value.lower()

    @classmethod
    def _validate_persisted_commit(cls, value: object) -> str:
        try:
            return cls._validate_commit_sha(value)
        except KnowledgeTransactionConfigurationError as exc:
            raise KnowledgeTransactionIntegrityError(
                "persisted knowledge commit SHA is invalid"
            ) from exc

    @classmethod
    def _validate_digest(cls, value: object) -> str:
        if type(value) is not str or cls._DIGEST.fullmatch(value) is None:
            raise KnowledgeTransactionIntegrityError(
                "persisted knowledge index digest is invalid"
            )
        return value

    @staticmethod
    def _validate_fencing_token(value: object) -> int:
        if type(value) is not int or value < 1:
            raise KnowledgeTransactionIntegrityError(
                "persisted knowledge fencing token is invalid"
            )
        return value

    @staticmethod
    def _validate_timestamp(value: object) -> None:
        if type(value) is not str:
            raise KnowledgeTransactionIntegrityError(
                "persisted knowledge timestamp is invalid"
            )
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as exc:
            raise KnowledgeTransactionIntegrityError(
                "persisted knowledge timestamp is invalid"
            ) from exc
        if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
            raise KnowledgeTransactionIntegrityError(
                "persisted knowledge timestamp must be UTC"
            )

    def _staged_path(self, tx_id: str) -> Path:
        return self.staging_dir / f"{tx_id}.json"

    def _snapshot_path(self, tx_id: str) -> Path:
        return self.snapshots_dir / f"{tx_id}.json"

    def _require_confined(self, path: Path) -> None:
        try:
            path.resolve(strict=False).relative_to(self.project_root)
        except (OSError, RuntimeError, ValueError) as exc:
            raise KnowledgeTransactionConfigurationError(
                "knowledge path escapes the project root"
            ) from exc

    @staticmethod
    def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise KnowledgeTransactionIntegrityError(
                    "knowledge JSON contains duplicate keys"
                )
            result[key] = value
        return result

    @staticmethod
    def _reject_constant(value: str) -> None:
        raise KnowledgeTransactionIntegrityError(
            f"knowledge JSON contains invalid constant {value!r}"
        )

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _fsync_directory(directory: Path) -> None:
        if os.name == "nt":
            return
        try:
            descriptor = os.open(directory, os.O_RDONLY)
        except OSError as exc:
            raise KnowledgeTransactionWriteError(
                "knowledge directory cannot be opened for fsync"
            ) from exc
        try:
            os.fsync(descriptor)
        except OSError as exc:
            raise KnowledgeTransactionWriteError(
                "knowledge directory cannot be fsynced"
            ) from exc
        finally:
            os.close(descriptor)


__all__ = [
    "KnowledgeTransactionConfigurationError",
    "KnowledgeTransactionConflictError",
    "KnowledgeTransactionError",
    "KnowledgeTransactionIntegrityError",
    "KnowledgeTransactionManager",
    "KnowledgeTransactionRecoveryError",
    "KnowledgeTransactionWriteError",
    "TransactionState",
]
