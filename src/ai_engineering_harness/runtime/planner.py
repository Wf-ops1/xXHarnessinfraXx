"""Evidence-bound structured planning before compiled graph execution."""

from __future__ import annotations

import hashlib
import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from ai_engineering_harness.contracts.execution import validate_execution_id
from ai_engineering_harness.contracts.nodes import ContextSufficiencyReport, RetrievalRequest
from ai_engineering_harness.contracts.planning import PlanContent, PlanDocument
from ai_engineering_harness.contracts.policies import ResolvedPolicySpec, VerificationPolicySpec
from ai_engineering_harness.governance.budget import BudgetExceededError
from ai_engineering_harness.indexer.snapshot_manager import (
    SnapshotIntegrityError,
    SnapshotManager,
    SnapshotNotFoundError,
)
from ai_engineering_harness.models.provider import LLMResponse, ProviderError
from ai_engineering_harness.models.router import (
    ModelEgressDeniedError,
    ModelResponseBudgetExceededError,
    ModelRouter,
    ModelRoutingConfigurationError,
    ModelRoutingIntegrityError,
)
from ai_engineering_harness.persistence import (
    ExecutionLock,
    ResumeStateStorageProvider,
    StateStorageError,
    canonical_json_digest,
    canonical_json_object,
)

_VERIFICATION_POLICY_REFERENCE = "policies/verification_policy.yaml"
_TOOL_POLICY_REFERENCE = "policies/tool_policy.yaml"


class PlanPrerequisiteError(RuntimeError):
    """Planning failed closed before graph traversal could begin."""


class InvalidPlanError(PlanPrerequisiteError, ValueError):
    """Provider plan content is invalid, generic, or outside compiled boundaries."""


@dataclass(frozen=True, slots=True)
class PlanGenerationResult:
    document: PlanDocument
    plan_digest: str
    response: LLMResponse


class Planner:
    """Generate, validate, persist, and recover one canonical execution plan."""

    def __init__(
        self,
        project_root: Path,
        storage: ResumeStateStorageProvider,
        model_router: ModelRouter,
        *,
        snapshot_manager: SnapshotManager | None = None,
    ) -> None:
        try:
            self.project_root = Path(project_root).resolve(strict=True)
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            raise PlanPrerequisiteError("project root is not an existing canonical directory") from exc
        if not self.project_root.is_dir():
            raise PlanPrerequisiteError("project root is not an existing canonical directory")
        if not isinstance(storage, ResumeStateStorageProvider):
            raise TypeError("storage must implement ResumeStateStorageProvider")
        if not isinstance(model_router, ModelRouter):
            raise TypeError("model_router must be a ModelRouter")
        self._storage = storage
        self._model_router = model_router
        self._snapshot_manager = snapshot_manager or SnapshotManager(self.project_root)

    @staticmethod
    def response_schema() -> dict[str, object]:
        """Return the provider schema derived directly from the typed content contract."""
        return PlanContent.model_json_schema()

    @classmethod
    def schema_digest(cls) -> str:
        return canonical_json_digest(canonical_json_object(cls.response_schema()))

    def validate_route(self) -> tuple[str, ...]:
        """Validate egress and every configured candidate before reading evidence."""
        return self._model_router.validate_route()

    @staticmethod
    def validate_plan(plan: PlanDocument) -> bool:
        """Compatibility validation over the now-strict public contract."""
        try:
            PlanDocument.model_validate(plan.model_dump(mode="json"))
        except (TypeError, ValueError, ValidationError):
            return False
        return True

    def create_plan(
        self,
        *,
        execution_id: str,
        context_report: ContextSufficiencyReport,
        context_digest: str,
        context_request: RetrievalRequest,
        graph_input: dict[str, object],
        workflow_name: str,
        base_commit_sha: str,
        verification_policy: ResolvedPolicySpec,
        tool_policy: ResolvedPolicySpec,
        active_node_ids: tuple[str, ...],
        lock: ExecutionLock | None = None,
    ) -> PlanGenerationResult:
        """Call the configured provider once and durably publish a validated plan."""
        try:
            validate_execution_id(execution_id)
            self.validate_route()
            graph_input_digest = canonical_json_digest(canonical_json_object(graph_input))
            self._validate_context(
                context_report,
                context_digest=context_digest,
                request=context_request,
                workflow_name=workflow_name,
                base_commit_sha=base_commit_sha,
            )
            artifacts = self._read_artifacts(context_report)
            evidence_refs, symbol_refs = self._validated_structural_evidence(context_report)
            evidence_refs.update(
                f"artifact:{item.artifact_id}@{item.digest}" for item in context_report.artifact_evidence
            )
            applicable_gates = self._applicable_gates(verification_policy, workflow_name)
            allowed_tools = self._allowed_tools(tool_policy, active_node_ids)
            prompt = self._prompt(
                request=context_request,
                workflow_name=workflow_name,
                base_commit_sha=base_commit_sha,
                artifacts=artifacts,
                symbol_refs=tuple(sorted(symbol_refs)),
                evidence_refs=tuple(sorted(evidence_refs)),
                applicable_gates=applicable_gates,
                allowed_tools=allowed_tools,
            )
            response = self._model_router.structured_output_with_fallback(
                prompt,
                self.response_schema(),
            )
            if type(response.structured_output) is not dict:
                raise InvalidPlanError("provider response does not contain a structured plan object")
            content = PlanContent.model_validate(response.structured_output)
            self._validate_specificity(
                content,
                evidence_refs=evidence_refs,
                symbol_refs=symbol_refs,
                applicable_gates=applicable_gates,
                allowed_tools=allowed_tools,
            )
            document = PlanDocument.model_validate(
                {
                    **content.model_dump(mode="json"),
                    "schema_version": "1.0",
                    "execution_id": execution_id,
                    "workflow_name": workflow_name,
                    "base_commit_sha": base_commit_sha,
                    "context_digest": context_digest,
                    "graph_input_digest": graph_input_digest,
                }
            )
            plan_digest = self._storage.store_payload(
                execution_id,
                document.model_dump(mode="json"),
                lock=lock,
            )
            self._publish_projection(execution_id, document)
            return PlanGenerationResult(
                document=document,
                plan_digest=plan_digest,
                response=response,
            )
        except InvalidPlanError:
            raise
        except ValidationError as exc:
            raise InvalidPlanError("provider plan violates the strict planning contract") from exc
        except (
            BudgetExceededError,
            ModelEgressDeniedError,
            ModelResponseBudgetExceededError,
            ModelRoutingConfigurationError,
            ModelRoutingIntegrityError,
            OSError,
            ProviderError,
            SnapshotIntegrityError,
            SnapshotNotFoundError,
            StateStorageError,
            TypeError,
            UnicodeError,
            ValueError,
        ) as exc:
            raise PlanPrerequisiteError("planning prerequisite is unavailable or invalid") from exc

    def recover_plan(
        self,
        *,
        execution_id: str,
        plan_digest: str,
        context_digest: str,
        graph_input_digest: str,
        workflow_name: str,
        base_commit_sha: str,
        lock: ExecutionLock | None = None,
    ) -> PlanDocument:
        """Recover the authoritative payload and restore its projection without a model call."""
        try:
            document = PlanDocument.model_validate(
                self._storage.load_payload(execution_id, plan_digest, lock=lock)
            )
            if (
                document.execution_id != execution_id
                or document.context_digest != context_digest
                or document.graph_input_digest != graph_input_digest
                or document.workflow_name != workflow_name
                or document.base_commit_sha != base_commit_sha
            ):
                raise InvalidPlanError("persisted plan identity does not match the execution")
            self._publish_projection(execution_id, document)
            return document
        except InvalidPlanError:
            raise
        except (OSError, StateStorageError, TypeError, UnicodeError, ValueError, ValidationError) as exc:
            raise PlanPrerequisiteError("persisted plan is unavailable or invalid") from exc

    @staticmethod
    def _validate_context(
        report: ContextSufficiencyReport,
        *,
        context_digest: str,
        request: RetrievalRequest,
        workflow_name: str,
        base_commit_sha: str,
    ) -> None:
        observed_digest = canonical_json_digest(
            canonical_json_object(report.model_dump(mode="json"))
        )
        query_digest = "sha256:" + hashlib.sha256(request.query.encode("utf-8")).hexdigest()
        if (
            observed_digest != context_digest
            or not report.is_sufficient
            or report.recommended_action != "proceed"
            or report.gaps
            or report.commit_sha != base_commit_sha
            or report.workflow_name != workflow_name
            or report.request.requirement_id != request.requirement_id
            or report.request.graph_type != request.graph_type
            or report.request.query_digest != query_digest
        ):
            raise PlanPrerequisiteError("context report does not match the immutable execution")

    def _read_artifacts(
        self,
        report: ContextSufficiencyReport,
    ) -> tuple[dict[str, object], ...]:
        artifacts: list[dict[str, object]] = []
        for evidence in report.artifact_evidence:
            source = self.project_root.joinpath(*evidence.relative_path.split("/"))
            self._require_safe_existing_file(source)
            raw = source.read_bytes()
            if (
                len(raw) != evidence.size_bytes
                or "sha256:" + hashlib.sha256(raw).hexdigest() != evidence.digest
            ):
                raise PlanPrerequisiteError("knowledge artifact no longer matches context evidence")
            artifacts.append(
                {
                    "artifact_id": evidence.artifact_id,
                    "content": raw.decode("utf-8", errors="strict"),
                    "digest": evidence.digest,
                    "path": evidence.relative_path,
                }
            )
        return tuple(artifacts)

    def _validated_structural_evidence(
        self,
        report: ContextSufficiencyReport,
    ) -> tuple[set[str], dict[str, tuple[str, str]]]:
        snapshot = self._snapshot_manager.require_snapshot(report.commit_sha)
        snapshot_evidence = tuple(
            evidence
            for dimension in report.dimensions
            for evidence in dimension.evidence
            if evidence.kind == "snapshot"
        )
        if not snapshot_evidence or any(
            evidence.identifier != report.commit_sha or evidence.digest != snapshot.digest
            for evidence in snapshot_evidence
        ):
            raise PlanPrerequisiteError("structural snapshot does not match context evidence")
        actual_symbols = {
            f"{symbol.path}:{symbol.line_start}:{symbol.qualified_name}": symbol
            for symbol in snapshot.symbols
        }
        reported_symbols = {
            evidence.identifier
            for dimension in report.dimensions
            for evidence in dimension.evidence
            if evidence.kind == "symbol"
        }
        if not reported_symbols or not reported_symbols.issubset(actual_symbols):
            raise PlanPrerequisiteError("structural symbol evidence is absent or invalid")
        symbol_refs = {
            f"symbol:{identifier}": (
                actual_symbols[identifier].path,
                actual_symbols[identifier].qualified_name,
            )
            for identifier in reported_symbols
        }
        return set(symbol_refs), symbol_refs

    @staticmethod
    def _applicable_gates(
        resolved: ResolvedPolicySpec,
        workflow_name: str,
    ) -> tuple[str, ...]:
        if resolved.requested_reference != _VERIFICATION_POLICY_REFERENCE:
            raise PlanPrerequisiteError("compiled verification policy is missing")
        policy = VerificationPolicySpec.model_validate(
            {
                "policy_id": resolved.policy_id,
                "policy_schema_version": resolved.policy_schema_version,
                "definition_version": resolved.definition_version,
                **resolved.effective_policy,
            }
        )
        if workflow_name not in policy.applies_to:
            raise PlanPrerequisiteError("verification policy does not apply to the workflow")
        gates = tuple(gate.id for gate in policy.required_gates if gate.blocking)
        if not gates or len(set(gates)) != len(gates):
            raise PlanPrerequisiteError("compiled verification gates are empty or duplicated")
        return gates

    @staticmethod
    def _allowed_tools(
        resolved: ResolvedPolicySpec,
        active_node_ids: tuple[str, ...],
    ) -> tuple[str, ...]:
        if resolved.requested_reference != _TOOL_POLICY_REFERENCE:
            raise PlanPrerequisiteError("compiled tool policy is missing")
        effective = resolved.effective_policy
        roles = effective.get("roles")
        if type(roles) is not dict:
            raise PlanPrerequisiteError("compiled tool policy has no effective roles")
        active = set(active_node_ids)
        observed_nodes: set[str] = set()
        allowed: set[str] = set()
        for role in roles.values():
            if type(role) is not dict or type(role.get("nodes")) is not list:
                raise PlanPrerequisiteError("compiled tool policy role is invalid")
            for node in role["nodes"]:
                if type(node) is not dict:
                    raise PlanPrerequisiteError("compiled tool policy node is invalid")
                node_id = node.get("node_id")
                tools = node.get("allowed_tools")
                if type(node_id) is not str or type(tools) is not list or not all(
                    type(tool) is str and bool(tool.strip()) and tool == tool.strip()
                    for tool in tools
                ):
                    raise PlanPrerequisiteError("compiled tool policy permissions are invalid")
                if node_id in active:
                    observed_nodes.add(node_id)
                    allowed.update(tools)
        if not observed_nodes.issubset(active):
            raise PlanPrerequisiteError("compiled tool policy references an unknown graph node")
        return tuple(sorted(allowed))

    @staticmethod
    def _validate_specificity(
        content: PlanContent,
        *,
        evidence_refs: set[str],
        symbol_refs: Mapping[str, tuple[str, str]],
        applicable_gates: tuple[str, ...],
        allowed_tools: tuple[str, ...],
    ) -> None:
        cited = {
            reference
            for criterion in content.acceptance_criteria
            for reference in criterion.evidence_refs
        } | {reference for target in content.targets for reference in target.evidence_refs}
        if not cited.issubset(evidence_refs):
            raise InvalidPlanError("plan cites evidence outside the sufficient context")
        for target in content.targets:
            if target.symbol is None:
                continue
            matches = tuple(
                symbol_refs[reference]
                for reference in target.evidence_refs
                if reference in symbol_refs
            )
            if not matches or (target.path, target.symbol) not in matches:
                raise InvalidPlanError("symbol target does not match structural evidence")
        if content.applicable_gates != applicable_gates:
            raise InvalidPlanError("plan gates do not match the compiled verification policy")
        if not set(content.planned_tools).issubset(allowed_tools):
            raise InvalidPlanError("plan tools exceed the compiled tool policy")

    @staticmethod
    def _prompt(
        *,
        request: RetrievalRequest,
        workflow_name: str,
        base_commit_sha: str,
        artifacts: tuple[dict[str, object], ...],
        symbol_refs: tuple[str, ...],
        evidence_refs: tuple[str, ...],
        applicable_gates: tuple[str, ...],
        allowed_tools: tuple[str, ...],
    ) -> str:
        payload = {
            "constraints": {
                "allowed_evidence_refs": list(evidence_refs),
                "allowed_tools": list(allowed_tools),
                "applicable_gates": list(applicable_gates),
                "blocking_remaining_gaps_allowed": False,
                "every_target_requires_evidence": True,
            },
            "evidence": {
                "artifacts": list(artifacts),
                "structural_symbol_refs": list(symbol_refs),
            },
            "identity": {
                "base_commit_sha": base_commit_sha,
                "workflow_name": workflow_name,
            },
            "request": request.model_dump(mode="json"),
        }
        return (
            "Produce a specific implementation plan using only the supplied evidence and "
            "compiled constraints. Do not invent files, symbols, tools, gates, or evidence.\n"
            + canonical_json_object(payload)
        )

    def _publish_projection(self, execution_id: str, document: PlanDocument) -> None:
        validated_id = validate_execution_id(execution_id)
        destination = (
            self.project_root
            / ".harness"
            / "state"
            / "executions"
            / validated_id
            / "plan.json"
        )
        try:
            self._prepare_execution_directory(destination.parent)
            if destination.is_symlink():
                raise OSError("plan projection destination is a symbolic link")
            canonical = canonical_json_object(document.model_dump(mode="json"))
            _atomic_replace_text(destination, canonical)
            if destination.read_text(encoding="utf-8", errors="strict") != canonical:
                raise OSError("plan projection failed read-after-write validation")
        except (OSError, RuntimeError, UnicodeError, ValueError) as exc:
            raise PlanPrerequisiteError("plan projection could not be published atomically") from exc

    def _prepare_execution_directory(self, directory: Path) -> None:
        current = self.project_root
        for part in directory.relative_to(self.project_root).parts:
            current /= part
            if current.is_symlink():
                raise OSError("plan state path traverses a symbolic link")
        directory.mkdir(parents=True, exist_ok=True)
        canonical = directory.resolve(strict=True)
        if not canonical.is_relative_to(self.project_root) or not canonical.is_dir():
            raise OSError("plan state directory escapes the project root")

    def _require_safe_existing_file(self, source: Path) -> None:
        current = self.project_root
        for part in source.relative_to(self.project_root).parts:
            current /= part
            if current.is_symlink():
                raise PlanPrerequisiteError("knowledge path traverses a symbolic link")
        canonical = source.resolve(strict=True)
        if not canonical.is_relative_to(self.project_root) or not canonical.is_file():
            raise PlanPrerequisiteError("knowledge artifact escapes the project root")


def _atomic_replace_text(destination: Path, content: str) -> None:
    file_descriptor, temporary_name = tempfile.mkstemp(
        dir=destination.parent,
        prefix=f".{destination.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
        directory_fd = None
        try:
            directory_fd = os.open(destination.parent, os.O_RDONLY)
            os.fsync(directory_fd)
        except OSError:
            if os.name != "nt":
                raise
        finally:
            if directory_fd is not None:
                os.close(directory_fd)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


__all__ = [
    "InvalidPlanError",
    "PlanDocument",
    "PlanGenerationResult",
    "PlanPrerequisiteError",
    "Planner",
]
