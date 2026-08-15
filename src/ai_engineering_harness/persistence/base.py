"""Public contracts for durable execution state storage."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from ai_engineering_harness.contracts.events import ExecutionEvent
from ai_engineering_harness.contracts.evidence import EvidenceManifest
from ai_engineering_harness.contracts.execution import ExecutionId, ExecutionRecord

_DIGEST_PATTERN = r"^sha256:[0-9a-f]{64}$"


class StateStorageError(Exception):
    """Base class for fail-closed state storage failures."""

    def __init__(self, message: str, *, execution_id: str | None = None) -> None:
        super().__init__(message)
        self.execution_id = execution_id


class ExecutionAlreadyExistsError(StateStorageError):
    """Creation was refused because managed state already exists."""


class ExecutionNotFoundError(StateStorageError):
    """No managed execution record exists for the requested identity."""


class RevisionConflictError(StateStorageError):
    """Optimistic concurrency rejected a stale or invalid revision."""

    def __init__(
        self,
        execution_id: str,
        *,
        expected_revision: int,
        actual_revision: int,
    ) -> None:
        super().__init__(
            (
                f"revision conflict for {execution_id!r}: expected "
                f"{expected_revision}, found {actual_revision}"
            ),
            execution_id=execution_id,
        )
        self.expected_revision = expected_revision
        self.actual_revision = actual_revision


class ExecutionIdentityMismatchError(StateStorageError):
    """A replacement attempted to change immutable execution identity."""


class StateIntegrityError(StateStorageError):
    """Persisted execution state is malformed or noncanonical."""


class JournalIntegrityError(StateIntegrityError):
    """The canonical event journal or its hash chain is invalid."""


class DuplicateEventError(JournalIntegrityError):
    """An event identifier already exists in the canonical journal."""


class LockAcquisitionTimeoutError(StateStorageError):
    """The cross-process lock was not acquired before its deadline."""


class LockOwnershipError(StateStorageError):
    """A lock handle is forged, foreign, inactive, or used incorrectly."""


class LockUnavailableError(StateStorageError):
    """The operating system cannot provide the required file lock."""


class RecoveryConflictError(StateIntegrityError):
    """Crash recovery is ambiguous or would discard integrity evidence."""


class StateWriteError(StateStorageError):
    """Durable state could not be published atomically."""


class ExecutionBundleError(StateStorageError):
    """Base class for immutable resume-bundle failures."""


class ExecutionBundleAlreadyExistsError(ExecutionBundleError):
    """A resume bundle already occupies the requested execution identity."""


class ExecutionBundleIntegrityError(ExecutionBundleError):
    """A resume bundle or content-addressed payload is invalid."""


class ExecutionBundleWriteError(ExecutionBundleError):
    """A resume bundle could not be published durably."""


class EvidenceManifestStorageError(StateStorageError):
    """Base class for canonical evidence manifest persistence failures."""


class EvidenceManifestNotFoundError(EvidenceManifestStorageError):
    """No canonical evidence manifest exists for the execution."""


class EvidenceManifestIntegrityError(EvidenceManifestStorageError):
    """Evidence bytes are malformed, noncanonical, divergent, or misbound."""


class EvidenceManifestWriteError(EvidenceManifestStorageError):
    """Canonical evidence could not be published atomically."""


class ExecutionBundle(BaseModel):
    """Immutable in-memory view of one exact resumable execution bundle."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    bundle_schema_version: Literal["1.0"]
    execution_id: ExecutionId
    artifact_digest: str = Field(pattern=_DIGEST_PATTERN)
    configuration_digest: str = Field(pattern=_DIGEST_PATTERN)
    initial_input_digest: str = Field(pattern=_DIGEST_PATTERN)
    artifact_json: Annotated[str, StringConstraints(min_length=1)]
    configuration_json: Annotated[str, StringConstraints(min_length=1)]

    def manifest_json(self) -> str:
        """Serialize only the redaction-safe bundle manifest canonically."""
        return canonical_json_object(
            {
                "artifact_digest": self.artifact_digest,
                "bundle_schema_version": self.bundle_schema_version,
                "configuration_digest": self.configuration_digest,
                "execution_id": self.execution_id,
                "initial_input_digest": self.initial_input_digest,
            }
        )


def canonical_json_object(value: object) -> str:
    """Return a detached finite JSON object with deterministic formatting."""
    if type(value) is not dict:
        raise ValueError("value must be an exact JSON object")
    try:
        serialized = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
        detached = json.loads(serialized)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"value is not a finite JSON object: {exc}") from exc
    if type(detached) is not dict:
        raise ValueError("value must be a JSON object")
    return serialized + "\n"


def canonical_json_digest(canonical_json: str) -> str:
    """Return the public sha256-prefixed digest for canonical UTF-8 JSON."""
    if type(canonical_json) is not str or not canonical_json.endswith("\n"):
        raise ValueError("canonical JSON must be a newline-terminated string")
    return "sha256:" + hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ExecutionLock:
    """Immutable public handle for one active cross-process lock."""

    lock_id: str
    execution_id: str
    owner_id: str
    fencing_token: int
    acquired_at: datetime


@runtime_checkable
class StateStorageProvider(Protocol):
    """Stable provider boundary for resumable execution state."""

    def create_execution(self, record: ExecutionRecord) -> ExecutionRecord:
        """Create revision zero without overwriting managed state."""

    def load_execution(
        self,
        execution_id: str,
        *,
        lock: ExecutionLock | None = None,
    ) -> ExecutionRecord:
        """Load one canonical execution record."""

    def compare_and_set_execution(
        self,
        execution_id: str,
        expected_revision: int,
        replacement: ExecutionRecord,
        *,
        lock: ExecutionLock | None = None,
    ) -> ExecutionRecord:
        """Publish exactly the next revision when the expected revision matches."""

    def append_event(
        self,
        execution_id: str,
        event: ExecutionEvent,
        *,
        lock: ExecutionLock | None = None,
    ) -> ExecutionEvent:
        """Atomically append one canonical, hash-chained event."""

    def list_executions(self) -> tuple[ExecutionRecord, ...]:
        """Return managed records ordered by execution identifier."""

    def acquire_execution_lock(
        self,
        execution_id: str,
        owner_id: str,
        *,
        timeout_seconds: float,
    ) -> ExecutionLock:
        """Acquire an OS-backed lock and advance its durable fencing token."""

    def release_execution_lock(self, lock: ExecutionLock) -> None:
        """Release an active handle owned by this provider instance."""


@runtime_checkable
class EventJournalStateStorageProvider(StateStorageProvider, Protocol):
    """Add canonical journal reads without expanding the F2.2 provider."""

    def load_events(
        self,
        execution_id: str,
        *,
        lock: ExecutionLock | None = None,
    ) -> tuple[ExecutionEvent, ...]:
        """Load the complete canonical journal after fail-closed recovery."""


@runtime_checkable
class ResumeStateStorageProvider(EventJournalStateStorageProvider, Protocol):
    """Add immutable bundles and content-addressed payloads for F2.5."""

    def create_execution_bundle(
        self,
        bundle: ExecutionBundle,
        *,
        initial_input: dict[str, object],
    ) -> ExecutionBundle:
        """Create one immutable bundle without overwriting an existing identity."""

    def load_execution_bundle(
        self,
        execution_id: str,
        *,
        lock: ExecutionLock | None = None,
    ) -> ExecutionBundle:
        """Load and verify the exact artifact/configuration bundle."""

    def store_payload(
        self,
        execution_id: str,
        payload: dict[str, object],
        *,
        lock: ExecutionLock | None = None,
    ) -> str:
        """Publish a canonical payload blob and return its digest."""

    def load_payload(
        self,
        execution_id: str,
        digest: str,
        *,
        lock: ExecutionLock | None = None,
    ) -> dict[str, object]:
        """Load a canonical payload blob after verifying its digest."""

    def publish_evidence_manifest(
        self,
        manifest: EvidenceManifest,
        *,
        lock: ExecutionLock | None = None,
    ) -> EvidenceManifest:
        """Publish one immutable canonical evidence manifest idempotently."""

    def load_evidence_manifest(
        self,
        execution_id: str,
        *,
        lock: ExecutionLock | None = None,
    ) -> EvidenceManifest:
        """Load and validate the canonical evidence manifest."""


__all__ = [
    "DuplicateEventError",
    "EventJournalStateStorageProvider",
    "EvidenceManifestIntegrityError",
    "EvidenceManifestNotFoundError",
    "EvidenceManifestStorageError",
    "EvidenceManifestWriteError",
    "ExecutionAlreadyExistsError",
    "ExecutionBundle",
    "ExecutionBundleAlreadyExistsError",
    "ExecutionBundleError",
    "ExecutionBundleIntegrityError",
    "ExecutionBundleWriteError",
    "ExecutionIdentityMismatchError",
    "ExecutionLock",
    "ExecutionNotFoundError",
    "JournalIntegrityError",
    "LockAcquisitionTimeoutError",
    "LockOwnershipError",
    "LockUnavailableError",
    "RecoveryConflictError",
    "ResumeStateStorageProvider",
    "RevisionConflictError",
    "StateIntegrityError",
    "StateStorageError",
    "StateStorageProvider",
    "StateWriteError",
    "canonical_json_digest",
    "canonical_json_object",
]
