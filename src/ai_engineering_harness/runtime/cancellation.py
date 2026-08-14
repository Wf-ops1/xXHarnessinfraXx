"""Durable, execution-bound cancellation signalling for operational commands."""

from __future__ import annotations

import hashlib
import json
import math
import os
import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final

from ai_engineering_harness.contracts.execution import validate_execution_id

_SCHEMA_VERSION: Final = "1.0"
_POLICY_FILE: Final = "cancellation-policy.json"
_REQUEST_FILE: Final = "cancellation-request.json"
_ACTIVE_COMMAND_FILE: Final = "active-command.json"
_COMMAND_OUTCOME_FILE: Final = "command-cancellation.json"
_COMMAND_OUTCOMES: Final = frozenset(
    {
        "cancelled",
        "cancelled_before_spawn",
        "completed",
        "spawn_failed",
        "timed_out",
    }
)


class CancellationControllerError(RuntimeError):
    """Base error for durable cancellation state."""


class CancellationStateIntegrityError(CancellationControllerError):
    """Cancellation state is malformed, divergent, or outside its execution root."""


class CancellationRequestedError(CancellationControllerError):
    """A command cannot start because its execution is already cancelled."""


class ConcurrentCommandError(CancellationControllerError):
    """A second command attempted to reuse one execution cancellation slot."""


@dataclass(frozen=True, slots=True)
class CancellationRequestResult:
    """Observed request identity and command active after publication."""

    decision_id: str
    requested_at: datetime
    active_command_id: str | None


@dataclass(frozen=True, slots=True)
class CancellationPolicyDecision:
    """Durable control decision that must precede the cancellation request."""

    decision_id: str
    requested_at: datetime


@dataclass(frozen=True, slots=True)
class CancellationObservation:
    """Observed quiescence after a cancellation request."""

    command_id: str | None
    outcome: str
    exit_code: int | None
    quiescent: bool
    termination_observed: bool


class CancellationController:
    """Coordinate cancellation through confined atomic files shared across processes."""

    def __init__(
        self,
        project_root: Path,
        execution_id: str,
        *,
        clock: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] | None = None,
        sleeper: Callable[[float], None] | None = None,
        poll_interval_seconds: float = 0.05,
    ) -> None:
        try:
            root = Path(project_root).resolve(strict=True)
        except (OSError, RuntimeError, ValueError) as exc:
            raise CancellationStateIntegrityError(
                "project_root must resolve to an existing directory"
            ) from exc
        if not root.is_dir():
            raise CancellationStateIntegrityError("project_root must be a directory")
        safe_execution_id = validate_execution_id(execution_id)
        execution_root = root / ".harness" / "state" / "executions" / safe_execution_id
        try:
            resolved_execution_root = execution_root.resolve(strict=True)
        except (OSError, RuntimeError, ValueError) as exc:
            raise CancellationStateIntegrityError(
                "execution state directory must already exist"
            ) from exc
        state_root = (root / ".harness" / "state" / "executions").resolve(strict=True)
        if resolved_execution_root.parent != state_root or not resolved_execution_root.is_dir():
            raise CancellationStateIntegrityError(
                "execution cancellation state is outside the canonical state root"
            )
        if (
            isinstance(poll_interval_seconds, bool)
            or not isinstance(poll_interval_seconds, (int, float))
            or not math.isfinite(poll_interval_seconds)
            or poll_interval_seconds <= 0
        ):
            raise ValueError("poll_interval_seconds must be a positive finite number")
        self.project_root = root
        self.execution_id = safe_execution_id
        self.execution_root = resolved_execution_root
        self._clock = clock or (lambda: datetime.now(UTC))
        self._monotonic = monotonic or time.monotonic
        self._sleeper = sleeper or time.sleep
        self._poll_interval_seconds = float(poll_interval_seconds)

    @property
    def is_cancelled(self) -> bool:
        """Fail closed when a request exists, including malformed request state."""

        request_path = self._path(_REQUEST_FILE)
        if not request_path.exists():
            return False
        try:
            self._load_request()
        except CancellationControllerError:
            return True
        return True

    @property
    def policy_decision(self) -> CancellationPolicyDecision | None:
        """Load the control decision used to recover an interrupted request publish."""

        if not self._path(_POLICY_FILE).exists():
            return None
        payload = self._load_policy()
        return CancellationPolicyDecision(
            decision_id=str(payload["decision_id"]),
            requested_at=self._parse_timestamp(
                payload["requested_at"],
                label="requested_at",
            ),
        )

    def request(
        self,
        *,
        decision_id: str,
        requested_at: datetime,
    ) -> CancellationRequestResult:
        """Publish one idempotent request after its policy decision is journaled."""

        safe_decision_id = self._non_empty_text(decision_id, label="decision_id")
        timestamp = self._utc_timestamp(requested_at, label="requested_at")
        policy = self._publish_policy_decision(
            decision_id=safe_decision_id,
            requested_at=timestamp,
        )
        safe_decision_id = policy.decision_id
        timestamp = policy.requested_at
        payload: dict[str, object] = {
            "schema_version": _SCHEMA_VERSION,
            "execution_id": self.execution_id,
            "decision_id": safe_decision_id,
            "requested_at": timestamp.isoformat().replace("+00:00", "Z"),
        }
        request_path = self._path(_REQUEST_FILE)
        if request_path.exists():
            existing = self._load_request()
            if (
                existing["decision_id"] != safe_decision_id
                or self._parse_timestamp(
                    existing["requested_at"],
                    label="requested_at",
                )
                != timestamp
            ):
                raise CancellationStateIntegrityError(
                    "cancellation was already requested by another policy decision"
                )
            timestamp = self._parse_timestamp(existing["requested_at"], label="requested_at")
        else:
            self._write_json_exclusive(request_path, payload)
        active = self._load_active(optional=True)
        return CancellationRequestResult(
            decision_id=safe_decision_id,
            requested_at=timestamp,
            active_command_id=None if active is None else str(active["command_id"]),
        )

    def _publish_policy_decision(
        self,
        *,
        decision_id: str,
        requested_at: datetime,
    ) -> CancellationPolicyDecision:
        payload: dict[str, object] = {
            "schema_version": _SCHEMA_VERSION,
            "execution_id": self.execution_id,
            "decision_id": decision_id,
            "requested_at": requested_at.isoformat().replace("+00:00", "Z"),
        }
        path = self._path(_POLICY_FILE)
        if path.exists():
            existing = self._load_policy()
            existing_timestamp = self._parse_timestamp(
                existing["requested_at"],
                label="requested_at",
            )
            if (
                existing["decision_id"] != decision_id
                or existing_timestamp != requested_at
            ):
                raise CancellationStateIntegrityError(
                    "cancellation policy decision is already bound to another request"
                )
            return CancellationPolicyDecision(
                decision_id=decision_id,
                requested_at=existing_timestamp,
            )
        self._write_json_exclusive(path, payload)
        return CancellationPolicyDecision(
            decision_id=decision_id,
            requested_at=requested_at,
        )

    def command_started(self, argv: Sequence[str]) -> str:
        """Reserve the single command slot before spawning any subprocess."""

        if self.is_cancelled:
            raise CancellationRequestedError("execution cancellation was already requested")
        normalized_argv = tuple(argv)
        if not normalized_argv or any(not isinstance(item, str) or not item for item in normalized_argv):
            raise CancellationStateIntegrityError("command argv must contain non-empty text")
        command_id = f"command-{uuid.uuid4().hex}"
        canonical_argv = json.dumps(
            normalized_argv,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )
        payload: dict[str, object] = {
            "schema_version": _SCHEMA_VERSION,
            "execution_id": self.execution_id,
            "command_id": command_id,
            "argv_digest": "sha256:"
            + hashlib.sha256(canonical_argv.encode("utf-8")).hexdigest(),
            "status": "PREPARING",
            "pid": None,
            "started_at": self._now().isoformat().replace("+00:00", "Z"),
        }
        try:
            self._write_json_exclusive(self._path(_ACTIVE_COMMAND_FILE), payload)
        except FileExistsError as exc:
            raise ConcurrentCommandError(
                "an execution can have only one active operational command"
            ) from exc
        if self.is_cancelled:
            self.command_finished(
                command_id,
                outcome="cancelled_before_spawn",
                exit_code=None,
            )
            raise CancellationRequestedError("execution was cancelled before command spawn")
        return command_id

    def command_spawned(self, command_id: str, *, pid: int) -> None:
        """Bind the reserved command to the exact spawned process leader."""

        if type(pid) is not int or pid <= 0:
            raise CancellationStateIntegrityError("spawned pid must be a positive integer")
        active = self._require_active_command(command_id)
        active.update({"status": "RUNNING", "pid": pid})
        self._write_json_atomic(self._path(_ACTIVE_COMMAND_FILE), active)

    def command_finished(
        self,
        command_id: str,
        *,
        outcome: str,
        exit_code: int | None,
    ) -> None:
        """Publish the observed terminal outcome before clearing the active slot."""

        if outcome not in _COMMAND_OUTCOMES:
            raise CancellationStateIntegrityError("unsupported command cancellation outcome")
        if exit_code is not None and type(exit_code) is not int:
            raise CancellationStateIntegrityError("command exit_code must be an integer or null")
        active = self._require_active_command(command_id)
        payload = {
            "schema_version": _SCHEMA_VERSION,
            "execution_id": self.execution_id,
            "command_id": str(active["command_id"]),
            "argv_digest": str(active["argv_digest"]),
            "pid": active["pid"],
            "outcome": outcome,
            "exit_code": exit_code,
            "finished_at": self._now().isoformat().replace("+00:00", "Z"),
        }
        self._write_json_atomic(self._path(_COMMAND_OUTCOME_FILE), payload)
        try:
            self._path(_ACTIVE_COMMAND_FILE).unlink()
        except FileNotFoundError:
            return
        except OSError as exc:
            raise CancellationStateIntegrityError(
                "active command state could not be cleared"
            ) from exc

    def wait_for_quiescence(
        self,
        active_command_id: str | None,
        *,
        timeout_seconds: float,
    ) -> CancellationObservation:
        """Wait only for the command observed when the request was published."""

        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(timeout_seconds)
            or timeout_seconds < 0
        ):
            raise ValueError("timeout_seconds must be a non-negative finite number")
        if active_command_id is None:
            return CancellationObservation(
                command_id=None,
                outcome="no_active_command",
                exit_code=None,
                quiescent=True,
                termination_observed=False,
            )
        safe_command_id = self._non_empty_text(active_command_id, label="active_command_id")
        deadline = self._monotonic() + float(timeout_seconds)
        while True:
            outcome = self._load_outcome(optional=True)
            active = self._load_active(optional=True)
            if outcome is not None and outcome["command_id"] == safe_command_id:
                same_active = active is not None and active["command_id"] == safe_command_id
                if not same_active:
                    observed = str(outcome["outcome"])
                    raw_exit_code = outcome["exit_code"]
                    if raw_exit_code is not None and type(raw_exit_code) is not int:
                        raise CancellationStateIntegrityError(
                            "command outcome exit_code is invalid"
                        )
                    return CancellationObservation(
                        command_id=safe_command_id,
                        outcome=observed,
                        exit_code=raw_exit_code,
                        quiescent=True,
                        termination_observed=observed
                        in {"cancelled", "cancelled_before_spawn"},
                    )
            if active is None:
                return CancellationObservation(
                    command_id=safe_command_id,
                    outcome="active_command_disappeared_without_outcome",
                    exit_code=None,
                    quiescent=False,
                    termination_observed=False,
                )
            now = self._monotonic()
            if now >= deadline:
                return CancellationObservation(
                    command_id=safe_command_id,
                    outcome="termination_not_observed",
                    exit_code=None,
                    quiescent=False,
                    termination_observed=False,
                )
            self._sleeper(min(self._poll_interval_seconds, deadline - now))

    def _require_active_command(self, command_id: str) -> dict[str, object]:
        safe_command_id = self._non_empty_text(command_id, label="command_id")
        active = self._load_active(optional=False)
        assert active is not None
        if active["command_id"] != safe_command_id:
            raise CancellationStateIntegrityError("active command identity diverged")
        return active

    def _load_request(self) -> dict[str, object]:
        payload = self._load_json(self._path(_REQUEST_FILE))
        self._require_exact_keys(
            payload,
            {"schema_version", "execution_id", "decision_id", "requested_at"},
            label="cancellation request",
        )
        self._require_identity(payload)
        self._non_empty_text(payload["decision_id"], label="decision_id")
        self._parse_timestamp(payload["requested_at"], label="requested_at")
        return payload

    def _load_policy(self) -> dict[str, object]:
        payload = self._load_json(self._path(_POLICY_FILE))
        self._require_exact_keys(
            payload,
            {"schema_version", "execution_id", "decision_id", "requested_at"},
            label="cancellation policy decision",
        )
        self._require_identity(payload)
        self._non_empty_text(payload["decision_id"], label="decision_id")
        self._parse_timestamp(payload["requested_at"], label="requested_at")
        return payload

    def _load_active(self, *, optional: bool) -> dict[str, object] | None:
        path = self._path(_ACTIVE_COMMAND_FILE)
        if optional and not path.exists():
            return None
        payload = self._load_json(path)
        self._require_exact_keys(
            payload,
            {
                "schema_version",
                "execution_id",
                "command_id",
                "argv_digest",
                "status",
                "pid",
                "started_at",
            },
            label="active command",
        )
        self._require_identity(payload)
        self._non_empty_text(payload["command_id"], label="command_id")
        digest = self._non_empty_text(payload["argv_digest"], label="argv_digest")
        if len(digest) != 71 or not digest.startswith("sha256:"):
            raise CancellationStateIntegrityError("active command argv_digest is invalid")
        if payload["status"] not in {"PREPARING", "RUNNING"}:
            raise CancellationStateIntegrityError("active command status is invalid")
        pid = payload["pid"]
        if pid is not None and (type(pid) is not int or pid <= 0):
            raise CancellationStateIntegrityError("active command pid is invalid")
        self._parse_timestamp(payload["started_at"], label="started_at")
        return payload

    def _load_outcome(self, *, optional: bool) -> dict[str, object] | None:
        path = self._path(_COMMAND_OUTCOME_FILE)
        if optional and not path.exists():
            return None
        payload = self._load_json(path)
        self._require_exact_keys(
            payload,
            {
                "schema_version",
                "execution_id",
                "command_id",
                "argv_digest",
                "pid",
                "outcome",
                "exit_code",
                "finished_at",
            },
            label="command outcome",
        )
        self._require_identity(payload)
        self._non_empty_text(payload["command_id"], label="command_id")
        if payload["outcome"] not in _COMMAND_OUTCOMES:
            raise CancellationStateIntegrityError("command outcome status is invalid")
        exit_code = payload["exit_code"]
        if exit_code is not None and type(exit_code) is not int:
            raise CancellationStateIntegrityError("command outcome exit_code is invalid")
        self._parse_timestamp(payload["finished_at"], label="finished_at")
        return payload

    def _require_identity(self, payload: dict[str, object]) -> None:
        if payload["schema_version"] != _SCHEMA_VERSION:
            raise CancellationStateIntegrityError("cancellation schema version is unsupported")
        if payload["execution_id"] != self.execution_id:
            raise CancellationStateIntegrityError("cancellation execution identity diverged")

    def _path(self, name: str) -> Path:
        path = self.execution_root / name
        if path.parent != self.execution_root:
            raise CancellationStateIntegrityError("cancellation path escaped execution root")
        return path

    @staticmethod
    def _load_json(path: Path) -> dict[str, object]:
        try:
            raw = path.read_text(encoding="utf-8")
            payload = json.loads(raw)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise CancellationStateIntegrityError(
                "cancellation state could not be read as strict UTF-8 JSON"
            ) from exc
        if type(payload) is not dict:
            raise CancellationStateIntegrityError("cancellation state must be a JSON object")
        return payload

    @staticmethod
    def _write_json_exclusive(path: Path, payload: dict[str, object]) -> None:
        data = CancellationController._json_bytes(payload)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
        except Exception:
            try:
                path.unlink()
            except OSError:
                pass
            raise

    @staticmethod
    def _write_json_atomic(path: Path, payload: dict[str, object]) -> None:
        data = CancellationController._json_bytes(payload)
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("xb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        except OSError as exc:
            try:
                temporary.unlink()
            except OSError:
                pass
            raise CancellationStateIntegrityError(
                "cancellation state could not be published atomically"
            ) from exc

    @staticmethod
    def _json_bytes(payload: dict[str, object]) -> bytes:
        try:
            serialized = json.dumps(
                payload,
                ensure_ascii=False,
                allow_nan=False,
                indent=2,
                sort_keys=True,
            )
        except (TypeError, ValueError) as exc:
            raise CancellationStateIntegrityError(
                "cancellation state is not finite JSON"
            ) from exc
        return (serialized + "\n").encode("utf-8")

    @staticmethod
    def _require_exact_keys(
        payload: dict[str, object],
        expected: set[str],
        *,
        label: str,
    ) -> None:
        if set(payload) != expected:
            raise CancellationStateIntegrityError(f"{label} fields are invalid")

    @staticmethod
    def _non_empty_text(value: object, *, label: str) -> str:
        if not isinstance(value, str) or not value.strip() or value != value.strip():
            raise CancellationStateIntegrityError(f"{label} must be canonical non-empty text")
        return value

    @staticmethod
    def _utc_timestamp(value: datetime, *, label: str) -> datetime:
        if (
            not isinstance(value, datetime)
            or value.tzinfo is None
            or value.utcoffset() is None
            or value.utcoffset() != timedelta(0)
        ):
            raise CancellationStateIntegrityError(f"{label} must be a UTC timestamp")
        return value.astimezone(UTC)

    @classmethod
    def _parse_timestamp(cls, value: object, *, label: str) -> datetime:
        if not isinstance(value, str):
            raise CancellationStateIntegrityError(f"{label} must be timestamp text")
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as exc:
            raise CancellationStateIntegrityError(f"{label} is invalid") from exc
        return cls._utc_timestamp(parsed, label=label)

    def _now(self) -> datetime:
        return self._utc_timestamp(self._clock(), label="clock")


__all__ = [
    "CancellationController",
    "CancellationControllerError",
    "CancellationObservation",
    "CancellationPolicyDecision",
    "CancellationRequestResult",
    "CancellationRequestedError",
    "CancellationStateIntegrityError",
    "ConcurrentCommandError",
]
