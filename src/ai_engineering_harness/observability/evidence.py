"""Generation and fail-closed verification of canonical execution evidence."""

from __future__ import annotations

import hashlib
import os
import re
import stat
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from pathlib import Path

from ai_engineering_harness.contracts.events import ExecutionEvent
from ai_engineering_harness.contracts.evidence import (
    ApprovalEvidence,
    BudgetEvidence,
    EvidenceApplicability,
    EvidenceDigest,
    EvidenceFile,
    EvidenceManifest,
    EvidenceNotApplicableReason,
    GateEvidence,
    KnowledgeEvidence,
    ModelEvidence,
    PromotionEvidence,
)
from ai_engineering_harness.contracts.execution import (
    ApprovalStatus,
    ExecutionRecord,
    ExecutionState,
)
from ai_engineering_harness.persistence import ExecutionLock, ResumeStateStorageProvider
from ai_engineering_harness.security import Redactor

_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_PAYLOAD_NAME = re.compile(r"^[0-9a-f]{64}\.json$")
_STATE_TRANSITIONED = "STATE_TRANSITIONED"


class EvidenceError(Exception):
    """Base class for redaction-safe evidence failures."""

    def __init__(self, message: str, *, execution_id: str | None = None) -> None:
        super().__init__(message)
        self.execution_id = execution_id


class EvidenceIntegrityError(EvidenceError):
    """Persisted inputs or manifest content cannot prove terminal success."""


class EvidenceManifestManager:
    """Build and verify one deterministic manifest from canonical persisted evidence."""

    def __init__(self, project_root: Path, storage: ResumeStateStorageProvider) -> None:
        self.project_root = Path(project_root).resolve()
        if not self.project_root.is_dir():
            raise EvidenceIntegrityError("project root must be an existing directory")
        if not isinstance(storage, ResumeStateStorageProvider):
            raise TypeError("storage must implement ResumeStateStorageProvider")
        self._storage = storage

    def ensure_terminal_manifest(
        self,
        final_record: ExecutionRecord,
        terminal_event: ExecutionEvent,
        lock: ExecutionLock,
    ) -> EvidenceManifest:
        """Publish or recover exact evidence before the terminal snapshot CAS."""

        execution_id = final_record.execution_id
        manifest = self._expected_terminal_manifest(final_record, terminal_event, lock)
        persisted = self._storage.publish_evidence_manifest(manifest, lock=lock)
        loaded = self._storage.load_evidence_manifest(execution_id, lock=lock)
        if persisted != manifest or loaded != manifest:
            raise EvidenceIntegrityError(
                "published evidence did not round-trip exactly",
                execution_id=execution_id,
            )
        self._validate_referenced_payloads(loaded)
        return loaded

    def verify_terminal_manifest(
        self,
        final_record: ExecutionRecord,
        terminal_event: ExecutionEvent,
        lock: ExecutionLock,
    ) -> EvidenceManifest:
        """Verify an already-published manifest before recovering the terminal CAS."""

        execution_id = final_record.execution_id
        state_root = (
            self.project_root / ".harness" / "state" / "executions" / execution_id
        )
        evidence_path = state_root / "evidence.json"
        if not evidence_path.exists() or evidence_path.is_symlink():
            raise EvidenceIntegrityError(
                "canonical evidence manifest is missing during terminal recovery",
                execution_id=execution_id,
            )
        self._require_regular_file(evidence_path, state_root, execution_id)
        expected = self._expected_terminal_manifest(final_record, terminal_event, lock)
        loaded = self._storage.load_evidence_manifest(execution_id, lock=lock)
        if loaded != expected:
            raise EvidenceIntegrityError(
                "published evidence diverges during terminal recovery",
                execution_id=execution_id,
            )
        self._validate_referenced_payloads(loaded)
        return loaded

    def load_and_verify(
        self,
        execution_id: str,
        *,
        lock: ExecutionLock | None = None,
    ) -> EvidenceManifest:
        """Load a manifest and recompute it from its terminal journal anchor."""

        manifest = self._storage.load_evidence_manifest(execution_id, lock=lock)
        record = self._storage.load_execution(execution_id, lock=lock)
        events = self._storage.load_events(execution_id, lock=lock)
        index = manifest.journal_final_sequence - 1
        if index < 0 or index >= len(events):
            raise EvidenceIntegrityError(
                "manifest journal sequence is outside the canonical chain",
                execution_id=execution_id,
            )
        terminal_event = events[index]
        if terminal_event.current_hash != manifest.journal_final_hash:
            raise EvidenceIntegrityError(
                "manifest journal hash does not match its canonical sequence",
                execution_id=execution_id,
            )
        bundle = self._storage.load_execution_bundle(execution_id, lock=lock)
        rebuilt = self._build_manifest(
            record=record,
            events=events[: index + 1],
            terminal_event=terminal_event,
            bundle_artifact_digest=bundle.artifact_digest,
            bundle_configuration_digest=bundle.configuration_digest,
        )
        if rebuilt != manifest:
            raise EvidenceIntegrityError(
                "evidence manifest diverges from canonical persisted inputs",
                execution_id=execution_id,
            )
        self._validate_referenced_payloads(manifest)
        return manifest

    def _expected_terminal_manifest(
        self,
        final_record: ExecutionRecord,
        terminal_event: ExecutionEvent,
        lock: ExecutionLock,
    ) -> EvidenceManifest:
        execution_id = final_record.execution_id
        events = self._storage.load_events(execution_id, lock=lock)
        if not events or events[-1] != terminal_event:
            raise EvidenceIntegrityError(
                "terminal transition must be the final canonical event",
                execution_id=execution_id,
            )
        bundle = self._storage.load_execution_bundle(execution_id, lock=lock)
        return self._build_manifest(
            record=final_record,
            events=events,
            terminal_event=terminal_event,
            bundle_artifact_digest=bundle.artifact_digest,
            bundle_configuration_digest=bundle.configuration_digest,
        )

    def _build_manifest(
        self,
        *,
        record: ExecutionRecord,
        events: Sequence[ExecutionEvent],
        terminal_event: ExecutionEvent,
        bundle_artifact_digest: str,
        bundle_configuration_digest: str,
    ) -> EvidenceManifest:
        execution_id = record.execution_id
        self._require_terminal_event(terminal_event, execution_id)
        if (
            terminal_event.sequence_number != len(events)
            or terminal_event.current_hash is None
            or record.current_state is not ExecutionState.COMPLETED
            or terminal_event.payload.get("record_revision") != record.revision
        ):
            raise EvidenceIntegrityError(
                "terminal event is not the exact completed snapshot anchor",
                execution_id=execution_id,
            )
        if (
            record.artifact_digest != bundle_artifact_digest
            or record.configuration_digest != bundle_configuration_digest
        ):
            raise EvidenceIntegrityError(
                "execution and immutable bundle digests diverge",
                execution_id=execution_id,
            )

        promoted = record.promotion_commit_sha is not None
        promotion = (
            PromotionEvidence(
                status=EvidenceApplicability.RECORDED,
                commit_sha=record.promotion_commit_sha,
            )
            if promoted
            else PromotionEvidence(
                status=EvidenceApplicability.NOT_APPLICABLE,
                reason="promotion_manager_not_used",
            )
        )
        plan = self._digest_evidence(events, "PLAN_GENERATED", "plan_digest", "plan_not_generated")
        context = self._context_evidence(events)
        diff = self._diff_evidence(events, promoted=promoted, execution_id=execution_id)
        gates = self._gate_evidence(events, execution_id)
        approval = self._approval_evidence(events, record.approval_status, execution_id)
        models = self._model_evidence(events)
        budget = self._budget_evidence(events, execution_id)
        knowledge = self._knowledge_evidence(events, execution_id)
        files = self._evidence_files(execution_id)

        manifest = EvidenceManifest(
            execution_id=execution_id,
            final_result="PROMOTED" if promoted else "VERIFIED",
            base_commit_sha=record.base_commit_sha,
            promotion=promotion,
            artifact_digest=record.artifact_digest,
            configuration_digest=record.configuration_digest,
            plan=plan,
            context=context,
            diff=diff,
            gates=gates,
            approval=approval,
            models=models,
            budget=budget,
            knowledge=knowledge,
            journal_final_hash=terminal_event.current_hash,
            journal_final_sequence=terminal_event.sequence_number,
            files=files,
        )
        self._require_digest_payload(plan, manifest)
        self._require_digest_payload(context, manifest)
        return manifest

    @staticmethod
    def _require_terminal_event(event: ExecutionEvent, execution_id: str) -> None:
        if (
            event.execution_id != execution_id
            or event.event_type != _STATE_TRANSITIONED
            or event.payload.get("to_state") != "COMPLETED"
            or event.payload.get("from_state") != "GENERATING_EVIDENCE"
        ):
            raise EvidenceIntegrityError(
                "manifest anchor must be GENERATING_EVIDENCE to COMPLETED",
                execution_id=execution_id,
            )

    @staticmethod
    def _digest_evidence(
        events: Sequence[ExecutionEvent],
        event_type: str,
        key: str,
        reason: EvidenceNotApplicableReason,
    ) -> EvidenceDigest:
        for event in reversed(events):
            if event.event_type != event_type:
                continue
            value = event.payload.get(key)
            if type(value) is str and _DIGEST.fullmatch(value) is not None:
                return EvidenceDigest(status=EvidenceApplicability.RECORDED, digest=value)
            raise EvidenceIntegrityError(
                f"{event_type} contains an invalid {key}",
                execution_id=event.execution_id,
            )
        return EvidenceDigest(status=EvidenceApplicability.NOT_APPLICABLE, reason=reason)

    @staticmethod
    def _context_evidence(events: Sequence[ExecutionEvent]) -> EvidenceDigest:
        for event in reversed(events):
            if event.event_type != "CONTEXT_EVALUATED":
                continue
            payload = event.payload
            if payload.get("outcome") != "sufficient":
                raise EvidenceIntegrityError(
                    "completed execution has no sufficient context outcome",
                    execution_id=event.execution_id,
                )
            value = payload.get("payload_digest")
            if type(value) is not str or _DIGEST.fullmatch(value) is None:
                raise EvidenceIntegrityError(
                    "context evidence digest is invalid",
                    execution_id=event.execution_id,
                )
            return EvidenceDigest(status=EvidenceApplicability.RECORDED, digest=value)
        return EvidenceDigest(
            status=EvidenceApplicability.NOT_APPLICABLE,
            reason="context_policy_not_used",
        )

    @staticmethod
    def _diff_evidence(
        events: Sequence[ExecutionEvent],
        *,
        promoted: bool,
        execution_id: str,
    ) -> EvidenceDigest:
        for event in reversed(events):
            if event.event_type != "PROMOTION_APPROVAL_REQUESTED":
                continue
            request = event.payload.get("request")
            value = request.get("diff_digest") if isinstance(request, Mapping) else None
            if type(value) is not str or _DIGEST.fullmatch(value) is None:
                raise EvidenceIntegrityError(
                    "promotion approval contains an invalid diff digest",
                    execution_id=execution_id,
                )
            return EvidenceDigest(status=EvidenceApplicability.RECORDED, digest=value)
        if promoted:
            raise EvidenceIntegrityError(
                "promoted execution has no content-bound diff digest",
                execution_id=execution_id,
            )
        return EvidenceDigest(
            status=EvidenceApplicability.NOT_APPLICABLE,
            reason="promotion_not_performed",
        )

    @staticmethod
    def _gate_evidence(
        events: Sequence[ExecutionEvent],
        execution_id: str,
    ) -> tuple[GateEvidence, ...]:
        suite = next(
            (event for event in reversed(events) if event.event_type == "VERIFICATION_SUITE_RECORDED"),
            None,
        )
        if suite is None or suite.payload.get("all_passed") is not True:
            raise EvidenceIntegrityError(
                "completed execution has no passing verification suite",
                execution_id=execution_id,
            )
        raw_digests = suite.payload.get("gate_result_digests")
        if not isinstance(raw_digests, list) or not raw_digests:
            raise EvidenceIntegrityError(
                "passing verification suite has no gate digests",
                execution_id=execution_id,
            )
        if len(set(raw_digests)) != len(raw_digests):
            raise EvidenceIntegrityError(
                "passing verification suite contains duplicate gate digests",
                execution_id=execution_id,
            )
        recorded: dict[str, GateEvidence] = {}
        for event in events:
            if event.event_type != "VERIFICATION_GATE_RECORDED":
                continue
            payload = event.payload
            digest = payload.get("result_digest")
            if (
                type(digest) is not str
                or _DIGEST.fullmatch(digest) is None
                or not isinstance(payload.get("gate_id"), str)
                or type(payload.get("required")) is not bool
                or not isinstance(payload.get("status"), str)
            ):
                raise EvidenceIntegrityError(
                    "verification gate evidence is invalid",
                    execution_id=execution_id,
                )
            if digest in recorded:
                raise EvidenceIntegrityError(
                    "verification gate result digest is duplicated",
                    execution_id=execution_id,
                )
            recorded[digest] = GateEvidence(
                gate_id=Redactor.redact_text(payload["gate_id"]),
                required=payload["required"],
                status=payload["status"],
                result_digest=digest,
            )
        try:
            return tuple(recorded[digest] for digest in raw_digests)
        except (KeyError, TypeError) as exc:
            raise EvidenceIntegrityError(
                "verification suite references missing gate evidence",
                execution_id=execution_id,
            ) from exc

    @staticmethod
    def _approval_evidence(
        events: Sequence[ExecutionEvent],
        status: ApprovalStatus,
        execution_id: str,
    ) -> ApprovalEvidence:
        if status is ApprovalStatus.NOT_REQUIRED:
            return ApprovalEvidence(status=status, reason="approval_not_required")
        if status is not ApprovalStatus.APPROVED:
            raise EvidenceIntegrityError(
                "completed execution has a nonterminal approval status",
                execution_id=execution_id,
            )
        for event in reversed(events):
            if event.event_type != "PROMOTION_APPROVED":
                continue
            payload = event.payload
            candidates: list[object] = [payload.get("subject_digest")]
            for key in ("approval", "request"):
                nested = payload.get(key)
                if isinstance(nested, Mapping):
                    candidates.append(nested.get("subject_digest"))
            for candidate in candidates:
                if type(candidate) is str and _DIGEST.fullmatch(candidate) is not None:
                    return ApprovalEvidence(status=status, subject_digest=candidate)
        raise EvidenceIntegrityError(
            "approval status has no canonical subject digest",
            execution_id=execution_id,
        )

    @staticmethod
    def _model_evidence(events: Sequence[ExecutionEvent]) -> tuple[ModelEvidence, ...]:
        identities: set[tuple[str, str]] = set()
        for event in events:
            payload = event.payload
            if event.event_type == "PLAN_GENERATED":
                EvidenceManifestManager._add_model_identity(
                    identities,
                    payload.get("provider"),
                    payload.get("model_name"),
                )
            raw_calls = payload.get("model_calls")
            if isinstance(raw_calls, list):
                for call in raw_calls:
                    if isinstance(call, Mapping):
                        EvidenceManifestManager._add_model_identity(
                            identities,
                            call.get("provider_id"),
                            call.get("model_name"),
                        )
            EvidenceManifestManager._add_model_identity(
                identities,
                payload.get("model_provider"),
                payload.get("model_name"),
            )
        return tuple(ModelEvidence(provider=provider, model=model) for provider, model in sorted(identities))

    @staticmethod
    def _add_model_identity(
        identities: set[tuple[str, str]],
        provider: object,
        model: object,
    ) -> None:
        if not isinstance(provider, str) or not isinstance(model, str):
            return
        safe_provider = Redactor.redact_text(provider).strip()
        safe_model = Redactor.redact_text(model).strip()
        if safe_provider and safe_model:
            identities.add((safe_provider, safe_model))

    @staticmethod
    def _budget_evidence(
        events: Sequence[ExecutionEvent],
        execution_id: str,
    ) -> BudgetEvidence:
        totals = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "tool_calls": 0,
            "duration_ms": 0,
            "attempts": 0,
            "unpriced_operations": 0,
        }
        cost = Decimal(0)
        cost_known = True
        count = 0
        for event in events:
            if event.event_type != "BUDGET_COMMITTED":
                continue
            actual = event.payload.get("actual")
            if not isinstance(actual, Mapping):
                raise EvidenceIntegrityError(
                    "budget commit has no actual usage",
                    execution_id=execution_id,
                )
            for key in totals:
                value = actual.get(key, 0)
                if type(value) is not int or value < 0:
                    raise EvidenceIntegrityError(
                        "budget commit contains invalid usage",
                        execution_id=execution_id,
                    )
                totals[key] += value
            raw_cost = actual.get("estimated_cost_usd")
            if raw_cost is None:
                cost_known = False
            else:
                try:
                    parsed = Decimal(str(raw_cost))
                except (InvalidOperation, ValueError) as exc:
                    raise EvidenceIntegrityError(
                        "budget commit contains invalid cost",
                        execution_id=execution_id,
                    ) from exc
                if not parsed.is_finite() or parsed < 0:
                    raise EvidenceIntegrityError(
                        "budget commit contains invalid cost",
                        execution_id=execution_id,
                    )
                cost += parsed
            count += 1
        if not count:
            return BudgetEvidence(
                status=EvidenceApplicability.NOT_APPLICABLE,
                reason="budget_boundary_not_used",
            )
        return BudgetEvidence(
            status=EvidenceApplicability.RECORDED,
            prompt_tokens=totals["prompt_tokens"],
            completion_tokens=totals["completion_tokens"],
            total_tokens=totals["total_tokens"],
            tool_calls=totals["tool_calls"],
            duration_ms=totals["duration_ms"],
            attempts=totals["attempts"],
            estimated_cost_usd=_decimal_text(cost) if cost_known else None,
            unpriced_operations=totals["unpriced_operations"],
        )

    @staticmethod
    def _knowledge_evidence(
        events: Sequence[ExecutionEvent],
        execution_id: str,
    ) -> KnowledgeEvidence:
        for event in reversed(events):
            if event.event_type != "KNOWLEDGE_SYNC":
                continue
            transaction_id = event.payload.get("tx_id", event.payload.get("transaction_id"))
            status = event.payload.get("status")
            if not isinstance(transaction_id, str) or not isinstance(status, str):
                raise EvidenceIntegrityError(
                    "knowledge transaction evidence is invalid",
                    execution_id=execution_id,
                )
            return KnowledgeEvidence(
                status=EvidenceApplicability.RECORDED,
                transaction_id=Redactor.redact_text(transaction_id),
                transaction_status=Redactor.redact_text(status),
            )
        return KnowledgeEvidence(
            status=EvidenceApplicability.NOT_APPLICABLE,
            reason="knowledge_sync_not_run",
        )

    def _evidence_files(self, execution_id: str) -> tuple[EvidenceFile, ...]:
        bundle_root = self.project_root / ".harness" / "artifacts" / "executions" / execution_id
        state_root = self.project_root / ".harness" / "state" / "executions" / execution_id
        candidates = [
            bundle_root / "artifact.json",
            bundle_root / "bundle.json",
            bundle_root / "configuration.json",
        ]
        payload_root = bundle_root / "payloads"
        self._require_directory(payload_root, bundle_root, execution_id)
        try:
            payload_entries = sorted(payload_root.iterdir(), key=lambda path: path.name)
        except OSError as exc:
            raise EvidenceIntegrityError(
                "cannot enumerate immutable payload evidence",
                execution_id=execution_id,
            ) from exc
        for entry in payload_entries:
            if _PAYLOAD_NAME.fullmatch(entry.name) is None:
                raise EvidenceIntegrityError(
                    "immutable payload directory contains an unexpected entry",
                    execution_id=execution_id,
                )
            candidates.append(entry)
        approval = state_root / "approval-request.json"
        if approval.exists() or approval.is_symlink():
            candidates.append(approval)

        files = tuple(
            sorted(
                (self._file_evidence(path, execution_id) for path in candidates),
                key=lambda item: item.path,
            )
        )
        if not payload_entries:
            raise EvidenceIntegrityError(
                "immutable execution bundle has no payload evidence",
                execution_id=execution_id,
            )
        return files

    def _file_evidence(self, path: Path, execution_id: str) -> EvidenceFile:
        allowed_roots = (
            self.project_root / ".harness" / "artifacts" / "executions" / execution_id,
            self.project_root / ".harness" / "state" / "executions" / execution_id,
        )
        root = next((item for item in allowed_roots if _is_relative_to(path, item)), None)
        if root is None:
            raise EvidenceIntegrityError(
                "evidence path escaped managed execution roots",
                execution_id=execution_id,
            )
        self._require_regular_file(path, root, execution_id)
        try:
            before = path.stat(follow_symlinks=False)
            content = path.read_bytes()
            after = path.stat(follow_symlinks=False)
        except OSError as exc:
            raise EvidenceIntegrityError(
                "cannot read referenced evidence file",
                execution_id=execution_id,
            ) from exc
        identity_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        identity_after = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        if identity_before != identity_after or len(content) != after.st_size:
            raise EvidenceIntegrityError(
                "referenced evidence file changed while being hashed",
                execution_id=execution_id,
            )
        relative = path.relative_to(self.project_root).as_posix()
        return EvidenceFile(
            path=relative,
            digest="sha256:" + hashlib.sha256(content).hexdigest(),
            size_bytes=len(content),
        )

    def _validate_referenced_payloads(self, manifest: EvidenceManifest) -> None:
        paths = {item.path for item in manifest.files}
        for evidence in (manifest.plan, manifest.context):
            self._require_digest_payload(evidence, manifest, paths=paths)

    @staticmethod
    def _require_digest_payload(
        evidence: EvidenceDigest,
        manifest: EvidenceManifest,
        *,
        paths: set[str] | None = None,
    ) -> None:
        if evidence.status is EvidenceApplicability.NOT_APPLICABLE:
            return
        assert evidence.digest is not None
        expected_suffix = f"/payloads/{evidence.digest.removeprefix('sha256:')}.json"
        observed = paths if paths is not None else {item.path for item in manifest.files}
        if not any(path.endswith(expected_suffix) for path in observed):
            raise EvidenceIntegrityError(
                "digest evidence has no referenced immutable payload",
                execution_id=manifest.execution_id,
            )

    def _require_directory(self, path: Path, root: Path, execution_id: str) -> None:
        self._require_no_reparse(path, root, execution_id)
        if not path.is_dir():
            raise EvidenceIntegrityError(
                "managed evidence directory is missing",
                execution_id=execution_id,
            )

    def _require_regular_file(self, path: Path, root: Path, execution_id: str) -> None:
        self._require_no_reparse(path, root, execution_id)
        try:
            mode = path.stat(follow_symlinks=False).st_mode
        except OSError as exc:
            raise EvidenceIntegrityError(
                "referenced evidence file is missing",
                execution_id=execution_id,
            ) from exc
        if not stat.S_ISREG(mode):
            raise EvidenceIntegrityError(
                "referenced evidence path is not a regular file",
                execution_id=execution_id,
            )

    def _require_no_reparse(self, path: Path, root: Path, execution_id: str) -> None:
        try:
            relative = path.relative_to(root)
        except ValueError as exc:
            raise EvidenceIntegrityError(
                "evidence path escaped its managed root",
                execution_id=execution_id,
            ) from exc
        components = [root]
        current = root
        for part in relative.parts:
            current = current / part
            components.append(current)
        for current in components:
            try:
                metadata = os.lstat(current)
            except OSError as exc:
                raise EvidenceIntegrityError(
                    "managed evidence path is missing",
                    execution_id=execution_id,
                ) from exc
            attributes = getattr(metadata, "st_file_attributes", 0)
            reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
            if stat.S_ISLNK(metadata.st_mode) or attributes & reparse_flag:
                raise EvidenceIntegrityError(
                    "managed evidence path cannot contain symlink or reparse components",
                    execution_id=execution_id,
                )


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


__all__ = [
    "EvidenceError",
    "EvidenceIntegrityError",
    "EvidenceManifestManager",
]
