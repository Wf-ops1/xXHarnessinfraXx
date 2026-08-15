"""Atomic file persistence for resumable execution state."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Final

from pydantic import ValidationError

from ai_engineering_harness.contracts import CompiledGraphArtifact
from ai_engineering_harness.contracts.events import ExecutionEvent
from ai_engineering_harness.contracts.execution import (
    ExecutionRecord,
    validate_execution_id,
)

from .base import (
    DuplicateEventError,
    ExecutionAlreadyExistsError,
    ExecutionBundle,
    ExecutionBundleAlreadyExistsError,
    ExecutionBundleIntegrityError,
    ExecutionBundleWriteError,
    ExecutionIdentityMismatchError,
    ExecutionLock,
    ExecutionNotFoundError,
    JournalIntegrityError,
    RecoveryConflictError,
    ResumeStateStorageProvider,
    RevisionConflictError,
    StateIntegrityError,
    StateWriteError,
    canonical_json_digest,
    canonical_json_object,
)
from .locks import CrossProcessLockManager

_EXECUTION_RECORD_NAME: Final = "execution.json"
_EVENT_JOURNAL_NAME: Final = "event-journal.jsonl"
_BUNDLE_MANIFEST_NAME: Final = "bundle.json"
_BUNDLE_ARTIFACT_NAME: Final = "artifact.json"
_BUNDLE_CONFIGURATION_NAME: Final = "configuration.json"
_BUNDLE_PAYLOAD_DIRECTORY: Final = "payloads"
_DIGEST_WITH_PREFIX_PATTERN: Final = re.compile(r"^sha256:([0-9a-f]{64})$")
_DEFAULT_LOCK_TIMEOUT_SECONDS: Final = 10.0
_FIRST_EVENT_HASH: Final = "0" * 64
_HASH_PATTERN: Final = re.compile(r"^[0-9a-f]{64}$")
_IMMUTABLE_IDENTITY_FIELDS: Final = (
    "workflow_name",
    "artifact_digest",
    "base_commit_sha",
    "original_branch",
    "configuration_digest",
    "created_at",
)


class ExecutionRecordStorageError(Exception):
    """Base error retained for the F2.1 snapshot helpers."""


class ExecutionRecordIntegrityError(ExecutionRecordStorageError):
    """A stored F2.1 record is malformed, noncanonical, or misbound."""


class ExecutionRecordWriteError(ExecutionRecordStorageError):
    """An F2.1 execution record could not be published atomically."""


def execution_record_path(project_root: Path, execution_id: str) -> Path:
    """Return the only F2.1/F2.2 storage location for an execution record."""
    validated_id = validate_execution_id(execution_id)
    return (
        project_root
        / ".harness"
        / "state"
        / "executions"
        / validated_id
        / _EXECUTION_RECORD_NAME
    )


def save_execution_record(project_root: Path, record: ExecutionRecord) -> Path:
    """Publish one F2.1 record without changing its unconditional-save contract."""
    destination = execution_record_path(project_root, record.execution_id)
    content = record.canonical_json().encode("utf-8")
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        _atomic_replace_bytes(destination, content)
    except OSError as exc:
        raise ExecutionRecordWriteError(f"cannot write execution record: {exc}") from exc
    return destination


def load_execution_record(project_root: Path, execution_id: str) -> ExecutionRecord:
    """Load an F2.1 canonical record without provider recovery semantics."""
    source = execution_record_path(project_root, execution_id)
    try:
        raw_text = source.read_bytes().decode("utf-8")
    except FileNotFoundError:
        raise
    except (OSError, UnicodeError) as exc:
        raise ExecutionRecordIntegrityError(f"cannot read execution record: {exc}") from exc

    try:
        record = ExecutionRecord.model_validate_json(raw_text)
    except (ValidationError, ValueError) as exc:
        raise ExecutionRecordIntegrityError(f"execution record is invalid: {exc}") from exc

    if record.execution_id != execution_id:
        raise ExecutionRecordIntegrityError(
            "stored execution_id does not match the requested execution"
        )
    if raw_text != record.canonical_json():
        raise ExecutionRecordIntegrityError("execution record is not canonical JSON")
    return record


class AtomicFileStateStorage(ResumeStateStorageProvider):
    """OS-locked, compare-and-set state storage rooted in one project."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = Path(project_root).resolve()
        self._execution_root = (
            self.project_root / ".harness" / "state" / "executions"
        )
        self._bundle_root = (
            self.project_root / ".harness" / "artifacts" / "executions"
        )
        self._locks = CrossProcessLockManager(self.project_root)
        self._owner_id = f"atomic-file-provider-{uuid.uuid4().hex}"

    def create_execution(self, record: ExecutionRecord) -> ExecutionRecord:
        """Create revision zero exactly once under catalog then execution lock."""
        if not isinstance(record, ExecutionRecord):
            raise StateIntegrityError("record must be an ExecutionRecord")
        execution_id = self._validate_execution_id(record.execution_id)
        if record.revision != 0:
            raise RevisionConflictError(
                execution_id,
                expected_revision=0,
                actual_revision=record.revision,
            )

        catalog_lock = self._locks.acquire_catalog(
            self._owner_id,
            timeout_seconds=_DEFAULT_LOCK_TIMEOUT_SECONDS,
        )
        try:
            execution_lock = self.acquire_execution_lock(
                execution_id,
                self._owner_id,
                timeout_seconds=_DEFAULT_LOCK_TIMEOUT_SECONDS,
            )
            try:
                destination = self._record_path(execution_id)
                recovered = self._recover_record(execution_id)
                if recovered is not None or destination.exists():
                    raise ExecutionAlreadyExistsError(
                        f"execution {execution_id!r} already exists",
                        execution_id=execution_id,
                    )
                self._ensure_execution_directory(execution_id)
                self._publish_state_bytes(
                    destination,
                    record.canonical_json().encode("utf-8"),
                    execution_id=execution_id,
                )
                return record
            finally:
                self.release_execution_lock(execution_lock)
        finally:
            self._locks.release_catalog(catalog_lock)

    def load_execution(
        self,
        execution_id: str,
        *,
        lock: ExecutionLock | None = None,
    ) -> ExecutionRecord:
        """Recover and load one canonical record under its execution lock."""
        validated_id = self._validate_execution_id(execution_id)
        with self._execution_guard(validated_id, lock):
            record = self._recover_record(validated_id)
            if record is None:
                raise ExecutionNotFoundError(
                    f"execution {validated_id!r} does not exist",
                    execution_id=validated_id,
                )
            return record

    def compare_and_set_execution(
        self,
        execution_id: str,
        expected_revision: int,
        replacement: ExecutionRecord,
        *,
        lock: ExecutionLock | None = None,
    ) -> ExecutionRecord:
        """Publish only the exact next revision while preserving identity."""
        validated_id = self._validate_execution_id(execution_id)
        if (
            isinstance(expected_revision, bool)
            or not isinstance(expected_revision, int)
            or expected_revision < 0
        ):
            raise StateIntegrityError(
                "expected_revision must be a non-negative integer",
                execution_id=validated_id,
            )
        if not isinstance(replacement, ExecutionRecord):
            raise StateIntegrityError(
                "replacement must be an ExecutionRecord",
                execution_id=validated_id,
            )

        with self._execution_guard(validated_id, lock):
            current = self._recover_record(validated_id)
            if current is None:
                raise ExecutionNotFoundError(
                    f"execution {validated_id!r} does not exist",
                    execution_id=validated_id,
                )
            if current.revision != expected_revision:
                raise RevisionConflictError(
                    validated_id,
                    expected_revision=expected_revision,
                    actual_revision=current.revision,
                )
            required_revision = expected_revision + 1
            if replacement.revision != required_revision:
                raise RevisionConflictError(
                    validated_id,
                    expected_revision=required_revision,
                    actual_revision=replacement.revision,
                )
            self._validate_replacement_identity(validated_id, current, replacement)
            self._publish_state_bytes(
                self._record_path(validated_id),
                replacement.canonical_json().encode("utf-8"),
                execution_id=validated_id,
            )
            return replacement

    def append_event(
        self,
        execution_id: str,
        event: ExecutionEvent,
        *,
        lock: ExecutionLock | None = None,
    ) -> ExecutionEvent:
        """Republish the complete journal with one canonical hash-chained event."""
        validated_id = self._validate_execution_id(execution_id)
        if not isinstance(event, ExecutionEvent):
            raise JournalIntegrityError(
                "event must be an ExecutionEvent",
                execution_id=validated_id,
            )
        if event.execution_id != validated_id:
            raise ExecutionIdentityMismatchError(
                "event execution_id does not match the requested execution",
                execution_id=validated_id,
            )
        if (
            event.sequence_number != 0
            or event.previous_hash is not None
            or event.current_hash is not None
        ):
            raise JournalIntegrityError(
                "caller-supplied event sequence must be zero and hashes must both be null",
                execution_id=validated_id,
            )

        with self._execution_guard(validated_id, lock):
            record = self._recover_record(validated_id)
            if record is None:
                raise ExecutionNotFoundError(
                    f"execution {validated_id!r} does not exist",
                    execution_id=validated_id,
                )
            if event.graph_name != record.workflow_name:
                raise ExecutionIdentityMismatchError(
                    "event graph_name does not match the execution workflow",
                    execution_id=validated_id,
                )
            journal_bytes, events = self._recover_journal(validated_id)
            if any(existing.event_id == event.event_id for existing in events):
                raise DuplicateEventError(
                    f"event_id {event.event_id!r} already exists",
                    execution_id=validated_id,
                )
            previous_hash = events[-1].current_hash if events else _FIRST_EVENT_HASH
            assert previous_hash is not None
            with_previous = event.model_copy(
                update={
                    "sequence_number": len(events) + 1,
                    "previous_hash": previous_hash,
                }
            )
            current_hash = _event_hash(with_previous)
            persisted = ExecutionEvent.model_validate(
                with_previous.model_copy(update={"current_hash": current_hash}).model_dump()
            )
            self._publish_state_bytes(
                self._journal_path(validated_id),
                journal_bytes + _canonical_event_line(persisted),
                execution_id=validated_id,
            )
            return persisted

    def load_events(
        self,
        execution_id: str,
        *,
        lock: ExecutionLock | None = None,
    ) -> tuple[ExecutionEvent, ...]:
        """Recover and load the complete canonical journal under one lock."""
        validated_id = self._validate_execution_id(execution_id)
        with self._execution_guard(validated_id, lock):
            if self._recover_record(validated_id) is None:
                raise ExecutionNotFoundError(
                    f"execution {validated_id!r} does not exist",
                    execution_id=validated_id,
                )
            _, events = self._recover_journal(validated_id)
            return events

    def create_execution_bundle(
        self,
        bundle: ExecutionBundle,
        *,
        initial_input: dict[str, object],
    ) -> ExecutionBundle:
        """Create an immutable artifact/configuration/payload bundle."""
        if not isinstance(bundle, ExecutionBundle):
            raise ExecutionBundleIntegrityError(
                "bundle must be an ExecutionBundle"
            )
        execution_id = self._validate_execution_id(bundle.execution_id)
        artifact_json = self._validate_artifact_json(
            bundle.artifact_json,
            execution_id=execution_id,
        )
        configuration_json = self._validate_json_object_text(
            bundle.configuration_json,
            execution_id=execution_id,
            label="configuration",
        )
        try:
            initial_json = canonical_json_object(initial_input)
        except ValueError as exc:
            raise ExecutionBundleIntegrityError(
                "initial input must be a finite JSON object",
                execution_id=execution_id,
            ) from exc
        if canonical_json_digest(artifact_json) != bundle.artifact_digest:
            raise ExecutionBundleIntegrityError(
                "artifact digest does not match bundle content",
                execution_id=execution_id,
            )
        if canonical_json_digest(configuration_json) != bundle.configuration_digest:
            raise ExecutionBundleIntegrityError(
                "configuration digest does not match bundle content",
                execution_id=execution_id,
            )
        if canonical_json_digest(initial_json) != bundle.initial_input_digest:
            raise ExecutionBundleIntegrityError(
                "initial input digest does not match bundle content",
                execution_id=execution_id,
            )

        catalog_lock = self._locks.acquire_catalog(
            self._owner_id,
            timeout_seconds=_DEFAULT_LOCK_TIMEOUT_SECONDS,
        )
        try:
            execution_lock = self.acquire_execution_lock(
                execution_id,
                self._owner_id,
                timeout_seconds=_DEFAULT_LOCK_TIMEOUT_SECONDS,
            )
            try:
                directory = self._bundle_directory(execution_id)
                if self._recover_record(execution_id) is not None:
                    raise ExecutionBundleAlreadyExistsError(
                        f"execution state {execution_id!r} already exists",
                        execution_id=execution_id,
                    )
                if directory.exists() or directory.is_symlink():
                    raise ExecutionBundleAlreadyExistsError(
                        f"execution bundle {execution_id!r} already exists",
                        execution_id=execution_id,
                    )
                self._ensure_bundle_directory(execution_id)
                self._publish_bundle_bytes(
                    self._bundle_artifact_path(execution_id),
                    artifact_json.encode("utf-8"),
                    execution_id=execution_id,
                )
                self._publish_bundle_bytes(
                    self._bundle_configuration_path(execution_id),
                    configuration_json.encode("utf-8"),
                    execution_id=execution_id,
                )
                self._publish_bundle_bytes(
                    self._payload_path(execution_id, bundle.initial_input_digest),
                    initial_json.encode("utf-8"),
                    execution_id=execution_id,
                )
                self._publish_bundle_bytes(
                    self._bundle_manifest_path(execution_id),
                    bundle.manifest_json().encode("utf-8"),
                    execution_id=execution_id,
                )
                return bundle
            finally:
                self.release_execution_lock(execution_lock)
        finally:
            self._locks.release_catalog(catalog_lock)

    def load_execution_bundle(
        self,
        execution_id: str,
        *,
        lock: ExecutionLock | None = None,
    ) -> ExecutionBundle:
        """Recover and validate one immutable resume bundle."""
        validated_id = self._validate_execution_id(execution_id)
        with self._execution_guard(validated_id, lock):
            if self._recover_record(validated_id) is None:
                raise ExecutionNotFoundError(
                    f"execution {validated_id!r} does not exist",
                    execution_id=validated_id,
                )
            return self._load_bundle_locked(validated_id)

    def store_payload(
        self,
        execution_id: str,
        payload: dict[str, object],
        *,
        lock: ExecutionLock | None = None,
    ) -> str:
        """Publish a canonical content-addressed JSON payload idempotently."""
        validated_id = self._validate_execution_id(execution_id)
        try:
            payload_json = canonical_json_object(payload)
        except ValueError as exc:
            raise ExecutionBundleIntegrityError(
                "payload must be a finite JSON object",
                execution_id=validated_id,
            ) from exc
        digest = canonical_json_digest(payload_json)
        with self._execution_guard(validated_id, lock):
            if self._recover_record(validated_id) is None:
                raise ExecutionNotFoundError(
                    f"execution {validated_id!r} does not exist",
                    execution_id=validated_id,
                )
            self._load_bundle_locked(validated_id)
            path = self._payload_path(validated_id, digest)
            if path.exists() or self._known_temp_paths(path):
                observed = self._load_payload_locked(validated_id, digest)
                if canonical_json_object(observed) != payload_json:
                    raise ExecutionBundleIntegrityError(
                        "payload digest collision or divergent content",
                        execution_id=validated_id,
                    )
                return digest
            self._publish_bundle_bytes(
                path,
                payload_json.encode("utf-8"),
                execution_id=validated_id,
            )
            return digest

    def load_payload(
        self,
        execution_id: str,
        digest: str,
        *,
        lock: ExecutionLock | None = None,
    ) -> dict[str, object]:
        """Load a detached canonical payload after digest verification."""
        validated_id = self._validate_execution_id(execution_id)
        with self._execution_guard(validated_id, lock):
            if self._recover_record(validated_id) is None:
                raise ExecutionNotFoundError(
                    f"execution {validated_id!r} does not exist",
                    execution_id=validated_id,
                )
            self._load_bundle_locked(validated_id)
            return self._load_payload_locked(validated_id, digest)

    def list_executions(self) -> tuple[ExecutionRecord, ...]:
        """Return managed records sorted by ID under the catalog hierarchy."""
        catalog_lock = self._locks.acquire_catalog(
            self._owner_id,
            timeout_seconds=_DEFAULT_LOCK_TIMEOUT_SECONDS,
        )
        try:
            if not self._execution_root.exists():
                return ()
            self._require_confined(self._execution_root)
            if not self._execution_root.is_dir():
                raise StateIntegrityError("execution state root is not a directory")
            try:
                entries = sorted(self._execution_root.iterdir(), key=lambda path: path.name)
            except OSError as exc:
                raise StateIntegrityError(f"cannot enumerate execution state: {exc}") from exc

            records: list[ExecutionRecord] = []
            for entry in entries:
                if not entry.is_dir():
                    continue
                self._require_confined(entry)
                if not self._has_managed_record(entry):
                    continue
                execution_id = self._validate_execution_id(entry.name)
                execution_lock = self.acquire_execution_lock(
                    execution_id,
                    self._owner_id,
                    timeout_seconds=_DEFAULT_LOCK_TIMEOUT_SECONDS,
                )
                try:
                    record = self._recover_record(execution_id)
                    if record is None:
                        raise RecoveryConflictError(
                            "managed execution disappeared during listing",
                            execution_id=execution_id,
                        )
                    records.append(record)
                finally:
                    self.release_execution_lock(execution_lock)
            return tuple(records)
        finally:
            self._locks.release_catalog(catalog_lock)

    def acquire_execution_lock(
        self,
        execution_id: str,
        owner_id: str,
        *,
        timeout_seconds: float,
    ) -> ExecutionLock:
        """Acquire an OS lock and advance its durable fencing token."""
        return self._locks.acquire(
            execution_id,
            owner_id,
            timeout_seconds=timeout_seconds,
        )

    def release_execution_lock(self, lock: ExecutionLock) -> None:
        """Release an exact handle created by this provider instance."""
        self._locks.release(lock)

    @contextmanager
    def _execution_guard(
        self,
        execution_id: str,
        lock: ExecutionLock | None,
    ) -> Iterator[None]:
        if lock is not None:
            self._locks.validate(lock, execution_id)
            yield
            return
        internal = self.acquire_execution_lock(
            execution_id,
            self._owner_id,
            timeout_seconds=_DEFAULT_LOCK_TIMEOUT_SECONDS,
        )
        try:
            yield
        finally:
            self.release_execution_lock(internal)

    def _recover_record(self, execution_id: str) -> ExecutionRecord | None:
        destination = self._record_path(execution_id)
        candidates = self._known_temp_paths(destination)
        if destination.exists():
            try:
                record = self._load_record_path(destination, execution_id)
            except StateIntegrityError as exc:
                raise RecoveryConflictError(
                    "canonical execution record is invalid; recovery refused",
                    execution_id=execution_id,
                ) from exc
            self._remove_known_temps(candidates, execution_id=execution_id)
            return record
        if len(candidates) > 1:
            raise RecoveryConflictError(
                "multiple abandoned execution record candidates exist",
                execution_id=execution_id,
            )
        if not candidates:
            return None

        candidate = candidates[0]
        try:
            record = self._load_record_path(candidate, execution_id)
        except StateIntegrityError as exc:
            raise RecoveryConflictError(
                "abandoned execution record candidate is invalid",
                execution_id=execution_id,
            ) from exc
        try:
            os.replace(candidate, destination)
            _fsync_directory(destination.parent)
        except OSError as exc:
            raise StateWriteError(
                f"cannot recover execution record: {exc}",
                execution_id=execution_id,
            ) from exc
        return record

    def _recover_journal(
        self,
        execution_id: str,
    ) -> tuple[bytes, tuple[ExecutionEvent, ...]]:
        destination = self._journal_path(execution_id)
        candidates = self._known_temp_paths(destination)
        if destination.exists():
            raw, events = self._load_journal_path(destination, execution_id)
            self._remove_known_temps(candidates, execution_id=execution_id)
            return raw, events
        if len(candidates) > 1:
            raise RecoveryConflictError(
                "multiple abandoned event journal candidates exist",
                execution_id=execution_id,
            )
        if not candidates:
            return b"", ()

        candidate = candidates[0]
        try:
            raw, events = self._load_journal_path(candidate, execution_id)
        except JournalIntegrityError as exc:
            raise RecoveryConflictError(
                "abandoned event journal candidate is invalid",
                execution_id=execution_id,
            ) from exc
        try:
            os.replace(candidate, destination)
            _fsync_directory(destination.parent)
        except OSError as exc:
            raise StateWriteError(
                f"cannot recover event journal: {exc}",
                execution_id=execution_id,
            ) from exc
        return raw, events

    def _load_record_path(self, path: Path, execution_id: str) -> ExecutionRecord:
        self._require_confined(path, execution_id=execution_id)
        try:
            raw_text = path.read_bytes().decode("utf-8")
        except (OSError, UnicodeError) as exc:
            raise StateIntegrityError(
                f"cannot read execution record: {exc}",
                execution_id=execution_id,
            ) from exc
        try:
            record = ExecutionRecord.model_validate_json(raw_text)
        except (ValidationError, ValueError) as exc:
            raise StateIntegrityError(
                f"execution record is invalid: {exc}",
                execution_id=execution_id,
            ) from exc
        if record.execution_id != execution_id:
            raise StateIntegrityError(
                "stored execution_id does not match the requested execution",
                execution_id=execution_id,
            )
        if raw_text != record.canonical_json():
            raise StateIntegrityError(
                "execution record is not canonical JSON",
                execution_id=execution_id,
            )
        return record

    def _load_journal_path(
        self,
        path: Path,
        execution_id: str,
    ) -> tuple[bytes, tuple[ExecutionEvent, ...]]:
        self._require_confined(path, execution_id=execution_id)
        try:
            raw = path.read_bytes()
            text = raw.decode("utf-8")
        except (OSError, UnicodeError) as exc:
            raise JournalIntegrityError(
                f"cannot read event journal: {exc}",
                execution_id=execution_id,
            ) from exc
        if not raw:
            return raw, ()
        if not raw.endswith(b"\n") or b"\r" in raw:
            raise JournalIntegrityError(
                "event journal must contain complete LF-terminated lines",
                execution_id=execution_id,
            )

        events: list[ExecutionEvent] = []
        event_ids: set[str] = set()
        expected_previous = _FIRST_EVENT_HASH
        for line_number, line in enumerate(text.splitlines(keepends=True), start=1):
            if not line.endswith("\n") or line == "\n":
                raise JournalIntegrityError(
                    f"event journal line {line_number} is incomplete or empty",
                    execution_id=execution_id,
                )
            try:
                event = ExecutionEvent.model_validate_json(line[:-1])
            except (ValidationError, ValueError) as exc:
                raise JournalIntegrityError(
                    f"event journal line {line_number} is invalid: {exc}",
                    execution_id=execution_id,
                ) from exc
            if _canonical_event_line(event).decode("utf-8") != line:
                raise JournalIntegrityError(
                    f"event journal line {line_number} is not canonical JSON",
                    execution_id=execution_id,
                )
            if event.execution_id != execution_id:
                raise JournalIntegrityError(
                    f"event journal line {line_number} belongs to another execution",
                    execution_id=execution_id,
                )
            if event.event_id in event_ids:
                raise JournalIntegrityError(
                    f"event journal contains duplicate event_id {event.event_id!r}",
                    execution_id=execution_id,
                )
            if event.sequence_number != line_number:
                raise JournalIntegrityError(
                    f"event journal sequence is invalid at line {line_number}",
                    execution_id=execution_id,
                )
            if (
                event.previous_hash != expected_previous
                or event.current_hash is None
                or _HASH_PATTERN.fullmatch(event.current_hash) is None
                or event.current_hash != _event_hash(event)
            ):
                raise JournalIntegrityError(
                    f"event journal hash chain is invalid at line {line_number}",
                    execution_id=execution_id,
                )
            event_ids.add(event.event_id)
            expected_previous = event.current_hash
            events.append(event)
        return raw, tuple(events)

    def _validate_replacement_identity(
        self,
        execution_id: str,
        current: ExecutionRecord,
        replacement: ExecutionRecord,
    ) -> None:
        if replacement.execution_id != execution_id:
            raise ExecutionIdentityMismatchError(
                "replacement execution_id does not match",
                execution_id=execution_id,
            )
        changed = [
            field
            for field in _IMMUTABLE_IDENTITY_FIELDS
            if getattr(current, field) != getattr(replacement, field)
        ]
        if changed:
            raise ExecutionIdentityMismatchError(
                f"replacement changes immutable identity fields: {', '.join(changed)}",
                execution_id=execution_id,
            )
        if replacement.updated_at < current.updated_at:
            raise ExecutionIdentityMismatchError(
                "replacement updated_at cannot regress",
                execution_id=execution_id,
            )

    def _load_bundle_locked(self, execution_id: str) -> ExecutionBundle:
        manifest_raw = self._recover_bundle_component(
            self._bundle_manifest_path(execution_id),
            execution_id=execution_id,
            validator=lambda raw: self._validate_manifest_bytes(
                raw,
                execution_id=execution_id,
            ),
        )
        artifact_raw = self._recover_bundle_component(
            self._bundle_artifact_path(execution_id),
            execution_id=execution_id,
            validator=lambda raw: self._validate_artifact_json(
                self._decode_bundle_bytes(raw, execution_id=execution_id),
                execution_id=execution_id,
            ),
        )
        configuration_raw = self._recover_bundle_component(
            self._bundle_configuration_path(execution_id),
            execution_id=execution_id,
            validator=lambda raw: self._validate_json_object_text(
                self._decode_bundle_bytes(raw, execution_id=execution_id),
                execution_id=execution_id,
                label="configuration",
            ),
        )
        manifest = self._validate_manifest_bytes(
            manifest_raw,
            execution_id=execution_id,
        )
        artifact_json = self._validate_artifact_json(
            self._decode_bundle_bytes(artifact_raw, execution_id=execution_id),
            execution_id=execution_id,
        )
        configuration_json = self._validate_json_object_text(
            self._decode_bundle_bytes(configuration_raw, execution_id=execution_id),
            execution_id=execution_id,
            label="configuration",
        )
        bundle = ExecutionBundle(
            bundle_schema_version=manifest.bundle_schema_version,
            execution_id=manifest.execution_id,
            artifact_digest=manifest.artifact_digest,
            configuration_digest=manifest.configuration_digest,
            initial_input_digest=manifest.initial_input_digest,
            artifact_json=artifact_json,
            configuration_json=configuration_json,
        )
        if canonical_json_digest(artifact_json) != bundle.artifact_digest:
            raise ExecutionBundleIntegrityError(
                "stored artifact digest does not match bundle manifest",
                execution_id=execution_id,
            )
        if canonical_json_digest(configuration_json) != bundle.configuration_digest:
            raise ExecutionBundleIntegrityError(
                "stored configuration digest does not match bundle manifest",
                execution_id=execution_id,
            )
        self._load_payload_locked(execution_id, bundle.initial_input_digest)
        return bundle

    def _load_payload_locked(
        self,
        execution_id: str,
        digest: str,
    ) -> dict[str, object]:
        path = self._payload_path(execution_id, digest)
        raw = self._recover_bundle_component(
            path,
            execution_id=execution_id,
            validator=lambda content: self._validate_payload_bytes(
                content,
                execution_id=execution_id,
                digest=digest,
            ),
        )
        return self._validate_payload_bytes(
            raw,
            execution_id=execution_id,
            digest=digest,
        )

    def _recover_bundle_component(
        self,
        destination: Path,
        *,
        execution_id: str,
        validator: Callable[[bytes], object],
    ) -> bytes:
        candidates = self._known_temp_paths(destination)
        if destination.exists():
            try:
                raw = destination.read_bytes()
                validator(raw)
            except ExecutionBundleIntegrityError:
                raise
            except OSError as exc:
                raise ExecutionBundleIntegrityError(
                    "cannot read resume bundle component",
                    execution_id=execution_id,
                ) from exc
            self._remove_known_temps(candidates, execution_id=execution_id)
            return raw
        if len(candidates) > 1:
            raise RecoveryConflictError(
                "multiple abandoned resume bundle candidates exist",
                execution_id=execution_id,
            )
        if not candidates:
            raise ExecutionBundleIntegrityError(
                "resume bundle component is missing",
                execution_id=execution_id,
            )
        candidate = candidates[0]
        try:
            raw = candidate.read_bytes()
            validator(raw)
            os.replace(candidate, destination)
            _fsync_directory(destination.parent)
        except ExecutionBundleIntegrityError:
            raise
        except OSError as exc:
            raise ExecutionBundleWriteError(
                "cannot recover resume bundle component",
                execution_id=execution_id,
            ) from exc
        return raw

    def _validate_manifest_bytes(
        self,
        raw: bytes,
        *,
        execution_id: str,
    ) -> ExecutionBundle:
        text = self._decode_bundle_bytes(raw, execution_id=execution_id)
        try:
            document = json.loads(text)
        except (json.JSONDecodeError, ValueError) as exc:
            raise ExecutionBundleIntegrityError(
                "bundle manifest is invalid JSON",
                execution_id=execution_id,
            ) from exc
        expected_keys = {
            "artifact_digest",
            "bundle_schema_version",
            "configuration_digest",
            "execution_id",
            "initial_input_digest",
        }
        if type(document) is not dict or set(document) != expected_keys:
            raise ExecutionBundleIntegrityError(
                "bundle manifest has missing or extra fields",
                execution_id=execution_id,
            )
        if canonical_json_object(document) != text:
            raise ExecutionBundleIntegrityError(
                "bundle manifest is not canonical JSON",
                execution_id=execution_id,
            )
        if document.get("execution_id") != execution_id:
            raise ExecutionBundleIntegrityError(
                "bundle manifest belongs to another execution",
                execution_id=execution_id,
            )
        try:
            bundle = ExecutionBundle(
                **document,
                artifact_json="{}\n",
                configuration_json="{}\n",
            )
        except (TypeError, ValueError, ValidationError) as exc:
            raise ExecutionBundleIntegrityError(
                "bundle manifest violates its public contract",
                execution_id=execution_id,
            ) from exc
        return bundle

    def _validate_artifact_json(
        self,
        text: str,
        *,
        execution_id: str,
    ) -> str:
        try:
            artifact = CompiledGraphArtifact.model_validate_json(text)
        except (TypeError, ValueError, ValidationError) as exc:
            raise ExecutionBundleIntegrityError(
                "bundle artifact is invalid",
                execution_id=execution_id,
            ) from exc
        if artifact.canonical_json() != text:
            raise ExecutionBundleIntegrityError(
                "bundle artifact is not canonical JSON",
                execution_id=execution_id,
            )
        return text

    def _validate_json_object_text(
        self,
        text: str,
        *,
        execution_id: str,
        label: str,
    ) -> str:
        try:
            document = json.loads(text)
            canonical = canonical_json_object(document)
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise ExecutionBundleIntegrityError(
                f"bundle {label} is not a finite JSON object",
                execution_id=execution_id,
            ) from exc
        if canonical != text:
            raise ExecutionBundleIntegrityError(
                f"bundle {label} is not canonical JSON",
                execution_id=execution_id,
            )
        return text

    def _validate_payload_bytes(
        self,
        raw: bytes,
        *,
        execution_id: str,
        digest: str,
    ) -> dict[str, object]:
        text = self._validate_json_object_text(
            self._decode_bundle_bytes(raw, execution_id=execution_id),
            execution_id=execution_id,
            label="payload",
        )
        if canonical_json_digest(text) != digest:
            raise ExecutionBundleIntegrityError(
                "payload digest does not match its content",
                execution_id=execution_id,
            )
        loaded = json.loads(text)
        assert type(loaded) is dict
        return loaded

    @staticmethod
    def _decode_bundle_bytes(raw: bytes, *, execution_id: str) -> str:
        try:
            return raw.decode("utf-8")
        except UnicodeError as exc:
            raise ExecutionBundleIntegrityError(
                "resume bundle component is not UTF-8",
                execution_id=execution_id,
            ) from exc

    def _bundle_directory(self, execution_id: str) -> Path:
        path = self._bundle_root / execution_id
        self._require_confined(path, execution_id=execution_id)
        return path

    def _bundle_manifest_path(self, execution_id: str) -> Path:
        return self._bundle_directory(execution_id) / _BUNDLE_MANIFEST_NAME

    def _bundle_artifact_path(self, execution_id: str) -> Path:
        return self._bundle_directory(execution_id) / _BUNDLE_ARTIFACT_NAME

    def _bundle_configuration_path(self, execution_id: str) -> Path:
        return self._bundle_directory(execution_id) / _BUNDLE_CONFIGURATION_NAME

    def _payload_path(self, execution_id: str, digest: str) -> Path:
        match = _DIGEST_WITH_PREFIX_PATTERN.fullmatch(digest) if type(digest) is str else None
        if match is None:
            raise ExecutionBundleIntegrityError(
                "payload digest is invalid",
                execution_id=execution_id,
            )
        path = (
            self._bundle_directory(execution_id)
            / _BUNDLE_PAYLOAD_DIRECTORY
            / f"{match.group(1)}.json"
        )
        self._require_confined(path, execution_id=execution_id)
        return path

    def _ensure_bundle_directory(self, execution_id: str) -> None:
        directory = self._bundle_directory(execution_id)
        try:
            (directory / _BUNDLE_PAYLOAD_DIRECTORY).mkdir(
                parents=True,
                exist_ok=True,
            )
        except OSError as exc:
            raise ExecutionBundleWriteError(
                "cannot create resume bundle directory",
                execution_id=execution_id,
            ) from exc
        self._require_confined(directory, execution_id=execution_id)

    def _publish_bundle_bytes(
        self,
        destination: Path,
        content: bytes,
        *,
        execution_id: str,
    ) -> None:
        self._ensure_bundle_directory(execution_id)
        self._require_confined(destination, execution_id=execution_id)
        try:
            _atomic_replace_bytes(destination, content)
        except OSError as exc:
            raise ExecutionBundleWriteError(
                "cannot publish resume bundle component",
                execution_id=execution_id,
            ) from exc

    def _record_path(self, execution_id: str) -> Path:
        path = execution_record_path(self.project_root, execution_id)
        self._require_confined(path, execution_id=execution_id)
        return path

    def _journal_path(self, execution_id: str) -> Path:
        path = self._record_path(execution_id).with_name(_EVENT_JOURNAL_NAME)
        self._require_confined(path, execution_id=execution_id)
        return path

    def _ensure_execution_directory(self, execution_id: str) -> None:
        directory = self._record_path(execution_id).parent
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise StateWriteError(
                f"cannot create execution state directory: {exc}",
                execution_id=execution_id,
            ) from exc
        self._require_confined(directory, execution_id=execution_id)

    def _publish_state_bytes(
        self,
        destination: Path,
        content: bytes,
        *,
        execution_id: str,
    ) -> None:
        self._ensure_execution_directory(execution_id)
        self._require_confined(destination, execution_id=execution_id)
        try:
            _atomic_replace_bytes(destination, content)
        except OSError as exc:
            raise StateWriteError(
                f"cannot publish execution state: {exc}",
                execution_id=execution_id,
            ) from exc

    def _known_temp_paths(self, destination: Path) -> tuple[Path, ...]:
        if not destination.parent.exists():
            return ()
        self._require_confined(destination.parent)
        try:
            candidates = tuple(
                sorted(
                    destination.parent.glob(f".{destination.name}.*.tmp"),
                    key=lambda path: path.name,
                )
            )
        except OSError as exc:
            raise RecoveryConflictError(f"cannot inspect recovery candidates: {exc}") from exc
        for candidate in candidates:
            self._require_confined(candidate)
        return candidates

    def _remove_known_temps(
        self,
        candidates: tuple[Path, ...],
        *,
        execution_id: str,
    ) -> None:
        for candidate in candidates:
            try:
                candidate.unlink()
            except FileNotFoundError:
                continue
            except OSError as exc:
                raise RecoveryConflictError(
                    f"cannot remove abandoned recovery candidate: {exc}",
                    execution_id=execution_id,
                ) from exc

    @staticmethod
    def _has_managed_record(directory: Path) -> bool:
        if (directory / _EXECUTION_RECORD_NAME).exists():
            return True
        return any(directory.glob(f".{_EXECUTION_RECORD_NAME}.*.tmp"))

    def _require_confined(
        self,
        path: Path,
        *,
        execution_id: str | None = None,
    ) -> None:
        try:
            path.resolve(strict=False).relative_to(self.project_root)
        except (OSError, ValueError) as exc:
            raise StateIntegrityError(
                "managed state path escapes the project root",
                execution_id=execution_id,
            ) from exc

    @staticmethod
    def _validate_execution_id(execution_id: str) -> str:
        try:
            return validate_execution_id(execution_id)
        except (TypeError, ValueError) as exc:
            raise StateIntegrityError("execution_id is invalid") from exc


def _canonical_event_json(event: ExecutionEvent, *, include_current_hash: bool) -> bytes:
    exclude = set() if include_current_hash else {"current_hash"}
    try:
        document = event.model_dump(mode="json", exclude=exclude)
        return json.dumps(
            document,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise JournalIntegrityError(f"event cannot be serialized canonically: {exc}") from exc


def _canonical_event_line(event: ExecutionEvent) -> bytes:
    return _canonical_event_json(event, include_current_hash=True) + b"\n"


def _event_hash(event: ExecutionEvent) -> str:
    return hashlib.sha256(
        _canonical_event_json(event, include_current_hash=False)
    ).hexdigest()


def _atomic_replace_bytes(destination: Path, content: bytes) -> None:
    descriptor: int | None = None
    temp_path: Path | None = None
    try:
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
        _fsync_directory(destination.parent)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def _fsync_directory(directory: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


__all__ = [
    "AtomicFileStateStorage",
    "ExecutionRecordIntegrityError",
    "ExecutionRecordStorageError",
    "ExecutionRecordWriteError",
    "execution_record_path",
    "load_execution_record",
    "save_execution_record",
]
