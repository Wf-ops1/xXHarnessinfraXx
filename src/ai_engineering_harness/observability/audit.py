"""Canonical, locally tamper-evident execution journal auditing."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from ai_engineering_harness.contracts.events import ExecutionEvent
from ai_engineering_harness.contracts.execution import validate_execution_id
from ai_engineering_harness.persistence import (
    AtomicFileStateStorage,
    EventJournalStateStorageProvider,
    StateStorageError,
)
from ai_engineering_harness.security import Redactor

_CHECKPOINT_SCHEMA_VERSION = "1.0"
_HMAC_PREFIX = "sha256:"
_MINIMUM_HMAC_KEY_BYTES = 32


class AuditTrailError(Exception):
    """Base class for redaction-safe audit failures."""

    def __init__(self, message: str, *, execution_id: str | None = None) -> None:
        super().__init__(message)
        self.execution_id = execution_id


class AuditConfigurationError(AuditTrailError):
    """Audit configuration is invalid before journal access."""


class AuditIntegrityError(AuditTrailError):
    """The execution journal or a supplied checkpoint is invalid."""


class AuditWriteError(AuditTrailError):
    """A canonical event could not be appended durably."""


@dataclass(frozen=True, slots=True)
class AuditCheckpoint:
    """Detached integrity summary for one exact canonical journal state."""

    checkpoint_schema_version: Literal["1.0"]
    execution_id: str
    total_events: int
    last_sequence_number: int
    last_event_hash: str | None
    protection: Literal["tamper-evident-local", "hmac-sha256"]
    hmac_sha256: str | None

    def to_dict(self) -> dict[str, object]:
        """Return a detached JSON-native checkpoint object."""

        return asdict(self)

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> AuditCheckpoint:
        """Validate an untrusted checkpoint mapping without coercion."""

        expected_keys = {
            "checkpoint_schema_version",
            "execution_id",
            "total_events",
            "last_sequence_number",
            "last_event_hash",
            "protection",
            "hmac_sha256",
        }
        if type(value) is not dict or set(value) != expected_keys:
            raise ValueError("checkpoint fields are invalid")
        schema_version = value["checkpoint_schema_version"]
        execution_id = value["execution_id"]
        total_events = value["total_events"]
        last_sequence_number = value["last_sequence_number"]
        last_event_hash = value["last_event_hash"]
        protection = value["protection"]
        signature = value["hmac_sha256"]
        if schema_version != _CHECKPOINT_SCHEMA_VERSION:
            raise ValueError("checkpoint schema version is unsupported")
        try:
            validated_execution_id = validate_execution_id(execution_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("checkpoint execution_id is invalid") from exc
        if type(total_events) is not int or total_events < 0:
            raise ValueError("checkpoint total_events is invalid")
        if type(last_sequence_number) is not int or last_sequence_number < 0:
            raise ValueError("checkpoint last_sequence_number is invalid")
        if total_events != last_sequence_number:
            raise ValueError("checkpoint event count and sequence disagree")
        if last_event_hash is not None and (
            type(last_event_hash) is not str
            or not _is_sha256_hex(last_event_hash)
        ):
            raise ValueError("checkpoint last_event_hash is invalid")
        if total_events == 0 and last_event_hash is not None:
            raise ValueError("empty checkpoint cannot have a last event hash")
        if total_events > 0 and last_event_hash is None:
            raise ValueError("non-empty checkpoint requires a last event hash")
        if protection not in {"tamper-evident-local", "hmac-sha256"}:
            raise ValueError("checkpoint protection is invalid")
        if protection == "tamper-evident-local":
            if signature is not None:
                raise ValueError("unsigned checkpoint cannot contain an HMAC")
        elif type(signature) is not str or not signature.startswith(_HMAC_PREFIX):
            raise ValueError("signed checkpoint requires an HMAC-SHA256 digest")
        elif not _is_sha256_hex(signature.removeprefix(_HMAC_PREFIX)):
            raise ValueError("checkpoint HMAC-SHA256 digest is invalid")
        return cls(
            checkpoint_schema_version="1.0",
            execution_id=validated_execution_id,
            total_events=total_events,
            last_sequence_number=last_sequence_number,
            last_event_hash=last_event_hash,
            protection=protection,
            hmac_sha256=signature,
        )


class AuditTrailManager:
    """Audit the single canonical ``ExecutionEvent`` journal for one execution."""

    def __init__(
        self,
        project_root: Path,
        execution_id: str,
        *,
        hmac_key: bytes | None = None,
        storage: EventJournalStateStorageProvider | None = None,
    ) -> None:
        try:
            self.execution_id = validate_execution_id(execution_id)
        except (TypeError, ValueError) as exc:
            raise AuditConfigurationError("audit execution_id is invalid") from exc
        if hmac_key is not None and (
            type(hmac_key) is not bytes or len(hmac_key) < _MINIMUM_HMAC_KEY_BYTES
        ):
            raise AuditConfigurationError(
                "audit HMAC key must be at least 32 bytes when configured",
                execution_id=self.execution_id,
            )
        resolved_root = Path(project_root).resolve()
        self.exec_dir = (
            resolved_root
            / ".harness"
            / "state"
            / "executions"
            / self.execution_id
        )
        self.journal_file = self.exec_dir / "event-journal.jsonl"
        self._hmac_key = hmac_key
        self._storage = (
            storage if storage is not None else AtomicFileStateStorage(resolved_root)
        )
        if not isinstance(self._storage, EventJournalStateStorageProvider):
            raise AuditConfigurationError(
                "audit storage must implement EventJournalStateStorageProvider",
                execution_id=self.execution_id,
            )

    def append_event(self, event: ExecutionEvent) -> ExecutionEvent:
        """Append one canonical draft through the F6.1 storage authority."""

        if not isinstance(event, ExecutionEvent):
            raise AuditWriteError(
                "audit append requires a canonical ExecutionEvent draft",
                execution_id=self.execution_id,
            )
        try:
            return self._storage.append_event(self.execution_id, event)
        except StateStorageError as exc:
            raise AuditWriteError(
                "cannot append audit event for execution "
                f"{self.execution_id!r}: {_safe_storage_error(exc)}",
                execution_id=self.execution_id,
            ) from exc

    def log_event(self, event: ExecutionEvent) -> ExecutionEvent:
        """Compatibility name for canonical appends; legacy envelopes are rejected."""

        return self.append_event(event)

    def load_events(self) -> tuple[ExecutionEvent, ...]:
        """Load and validate the complete canonical journal."""

        try:
            return self._storage.load_events(self.execution_id)
        except StateStorageError as exc:
            raise AuditIntegrityError(
                "audit journal for execution "
                f"{self.execution_id!r} is invalid: {_safe_storage_error(exc)}",
                execution_id=self.execution_id,
            ) from exc

    def verify_integrity(self) -> tuple[Literal[True], str]:
        """Validate the journal or raise a typed, execution-bound error."""

        events = self.load_events()
        protection = (
            "HMAC-SHA256 checkpoint"
            if self._hmac_key is not None
            else "tamper-evident local"
        )
        return (
            True,
            f"Journal canônico verificado: {len(events)} evento(s); proteção {protection}.",
        )

    def create_checkpoint(self) -> AuditCheckpoint:
        """Create an unsigned local or HMAC-authenticated journal checkpoint."""

        return self._checkpoint_for(self.load_events())

    def verify_checkpoint(
        self,
        checkpoint: AuditCheckpoint | Mapping[str, object],
    ) -> None:
        """Verify a detached checkpoint against the current canonical journal."""

        try:
            supplied = AuditCheckpoint.from_mapping(
                checkpoint.to_dict()
                if isinstance(checkpoint, AuditCheckpoint)
                else checkpoint
            )
        except (TypeError, ValueError) as exc:
            raise AuditIntegrityError(
                f"checkpoint for execution {self.execution_id!r} is invalid: {exc}",
                execution_id=self.execution_id,
            ) from exc
        expected = self._checkpoint_for(self.load_events())
        supplied_data = supplied.to_dict()
        expected_data = expected.to_dict()
        supplied_signature = supplied.hmac_sha256
        expected_signature = expected.hmac_sha256
        supplied_data.pop("hmac_sha256")
        expected_data.pop("hmac_sha256")
        if supplied_data != expected_data:
            raise AuditIntegrityError(
                f"checkpoint does not match execution {self.execution_id!r}",
                execution_id=self.execution_id,
            )
        if expected_signature is None:
            if supplied_signature is not None:
                raise AuditIntegrityError(
                    f"checkpoint protection does not match execution {self.execution_id!r}",
                    execution_id=self.execution_id,
                )
            return
        if type(supplied_signature) is not str or not hmac.compare_digest(
            supplied_signature,
            expected_signature,
        ):
            raise AuditIntegrityError(
                f"checkpoint HMAC verification failed for execution {self.execution_id!r}",
                execution_id=self.execution_id,
            )

    def export_json(self) -> str:
        """Export only a fully verified canonical journal as structured JSON."""

        events = self.load_events()
        checkpoint = self._checkpoint_for(events)
        document = {
            "audit_schema_version": "1.0",
            "execution_id": self.execution_id,
            "total_events": len(events),
            "integrity": {
                "status": "verified",
                "checkpoint": checkpoint.to_dict(),
            },
            "events": [event.model_dump(mode="json") for event in events],
        }
        return json.dumps(
            document,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )

    def export_sarif(self) -> str:
        """Export only a fully verified canonical journal as SARIF v2.1.0."""

        events = self.load_events()
        checkpoint = self._checkpoint_for(events)
        journal_uri = (
            f".harness/state/executions/{self.execution_id}/event-journal.jsonl"
        )
        results = [
            {
                "ruleId": f"AUDIT-EVENT-{event.event_type.value}",
                "level": "note",
                "message": {
                    "text": (
                        f"Evento {event.event_type.value} #{event.sequence_number} "
                        f"registrado em {event.timestamp.isoformat()}"
                    )
                },
                "locations": [
                    {
                        "physicalLocation": {
                            "artifactLocation": {"uri": journal_uri},
                            "region": {"startLine": event.sequence_number},
                        }
                    }
                ],
                "properties": {
                    "event_id": event.event_id,
                    "execution_id": self.execution_id,
                },
            }
            for event in events
        ]
        document = {
            "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
            "version": "2.1.0",
            "runs": [
                {
                    "tool": {
                        "driver": {
                            "name": "AI-Engineering-Harness Audit Trail",
                            "version": "0.1.0",
                        }
                    },
                    "automationDetails": {"id": self.execution_id},
                    "properties": {
                        "execution_id": self.execution_id,
                        "total_events": len(events),
                        "integrity_status": "verified",
                        "checkpoint": checkpoint.to_dict(),
                    },
                    "results": results,
                }
            ],
        }
        return json.dumps(
            document,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )

    def _checkpoint_for(
        self,
        events: tuple[ExecutionEvent, ...],
    ) -> AuditCheckpoint:
        last_event = events[-1] if events else None
        unsigned: dict[str, object] = {
            "checkpoint_schema_version": _CHECKPOINT_SCHEMA_VERSION,
            "execution_id": self.execution_id,
            "total_events": len(events),
            "last_sequence_number": last_event.sequence_number if last_event else 0,
            "last_event_hash": last_event.current_hash if last_event else None,
            "protection": (
                "hmac-sha256"
                if self._hmac_key is not None
                else "tamper-evident-local"
            ),
        }
        signature = None
        if self._hmac_key is not None:
            payload = json.dumps(
                unsigned,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            signature = _HMAC_PREFIX + hmac.new(
                self._hmac_key,
                payload,
                hashlib.sha256,
            ).hexdigest()
        return AuditCheckpoint(
            checkpoint_schema_version="1.0",
            execution_id=self.execution_id,
            total_events=len(events),
            last_sequence_number=last_event.sequence_number if last_event else 0,
            last_event_hash=last_event.current_hash if last_event else None,
            protection=(
                "hmac-sha256"
                if self._hmac_key is not None
                else "tamper-evident-local"
            ),
            hmac_sha256=signature,
        )


def _is_sha256_hex(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _safe_storage_error(error: StateStorageError) -> str:
    """Keep actionable identity/line context without echoing invalid raw input."""

    message = str(error)
    message = re.sub(
        r"(event journal line \d+ is invalid):.*",
        r"\1: schema or JSON validation failed",
        message,
        flags=re.DOTALL,
    )
    message = re.sub(
        r"(execution record is invalid):.*",
        r"\1: schema or JSON validation failed",
        message,
        flags=re.DOTALL,
    )
    return Redactor.redact_text(message)


__all__ = [
    "AuditCheckpoint",
    "AuditConfigurationError",
    "AuditIntegrityError",
    "AuditTrailError",
    "AuditTrailManager",
    "AuditWriteError",
]
