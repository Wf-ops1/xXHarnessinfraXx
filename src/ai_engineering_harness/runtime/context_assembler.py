"""Commit-bound, evidence-based context assembly for lifecycle preflight."""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
import unicodedata
from pathlib import Path
from typing import Final

from pydantic import BaseModel, ConfigDict, field_validator

from ai_engineering_harness.contracts.execution import ExecutionState, validate_execution_id
from ai_engineering_harness.contracts.nodes import (
    ArtifactEvidence,
    ContextRequestIdentity,
    ContextSufficiencyReport,
    ManifestResult,
    RetrievalRequest,
)
from ai_engineering_harness.contracts.policies import ContextSufficiencyPolicySpec
from ai_engineering_harness.contracts.structural_index import StructuralSnapshot, StructuralSymbol
from ai_engineering_harness.governance.evaluation import ContextSufficiencyEvaluator
from ai_engineering_harness.indexer.snapshot_manager import (
    SnapshotIntegrityError,
    SnapshotManager,
    SnapshotNotFoundError,
)
from ai_engineering_harness.persistence.base import canonical_json_object

_ARTIFACT_ID = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")
_TOKEN = re.compile(r"[a-z0-9]+")
_MARKDOWN_HEADING = re.compile(r"(?m)^ {0,3}#{1,6}[ \t]+\S")
_STOPLIST: Final[frozenset[str]] = frozenset(
    {
        "a",
        "add",
        "an",
        "and",
        "as",
        "at",
        "by",
        "da",
        "das",
        "de",
        "do",
        "dos",
        "e",
        "em",
        "for",
        "from",
        "in",
        "na",
        "nas",
        "no",
        "nos",
        "of",
        "on",
        "or",
        "para",
        "por",
        "the",
        "to",
        "um",
        "uma",
        "with",
    }
)


class ContextAssemblyError(RuntimeError):
    """Base error for context preparation without raw evidence in its message."""


class ContextPrerequisiteError(ContextAssemblyError):
    """An operational prerequisite was absent, corrupt, or could not be persisted."""

    state = ExecutionState.BLOCKED_PREREQUISITE


class InsufficientContextError(ContextAssemblyError):
    """The persisted evidence report failed at least one side of the dual gate."""

    state = ExecutionState.BLOCKED_INSUFFICIENT_CONTEXT

    def __init__(self, package: ContextPackage | ContextSufficiencyReport) -> None:
        report = package.report if isinstance(package, ContextPackage) else package
        super().__init__(
            f"context is insufficient at attempt {report.attempt}; "
            f"action={report.recommended_action}"
        )
        self.package = package if isinstance(package, ContextPackage) else None
        self.report = report
        self.gaps = report.gaps
        self.recommended_action = report.recommended_action


class ContextPackage(BaseModel):
    """Typed context output with full commit-bound symbols and a canonical report."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid", arbitrary_types_allowed=False)

    report: ContextSufficiencyReport
    knowledge_refs: tuple[ArtifactEvidence, ...]
    structural_snapshot: StructuralSnapshot
    relevant_structural_symbols: tuple[StructuralSymbol, ...]
    relevant_symbols: tuple[str, ...]

    @field_validator(
        "knowledge_refs",
        "relevant_structural_symbols",
        "relevant_symbols",
        mode="before",
    )
    @classmethod
    def freeze_sequences(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    def to_dict(self) -> dict[str, object]:
        return self.model_dump(mode="json")


class ContextAssembler:
    """Load exact evidence, calculate the frozen dimensions, and publish the latest report."""

    def __init__(self, project_root: Path):
        try:
            self.project_root = Path(project_root).resolve(strict=True)
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            raise ContextPrerequisiteError("project root is not an existing canonical directory") from exc
        if not self.project_root.is_dir():
            raise ContextPrerequisiteError("project root is not an existing canonical directory")
        self.snapshot_manager = SnapshotManager(self.project_root)

    def assemble(
        self,
        *,
        execution_id: str,
        request: RetrievalRequest,
        workflow_name: str,
        commit_sha: str,
        policy: ContextSufficiencyPolicySpec,
        policy_digest: str,
        attempt: int,
    ) -> ContextPackage:
        """Assemble one immutable attempt and raise after persisting an insufficient report."""

        try:
            validated_execution_id = validate_execution_id(execution_id)
        except (TypeError, ValueError) as exc:
            raise ContextPrerequisiteError("execution identity is invalid for context persistence") from exc
        expected_workflow = request.graph_type.replace("_", "-")
        if workflow_name != expected_workflow:
            raise ContextPrerequisiteError("context graph_type does not match the compiled workflow")
        if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1:
            raise ContextPrerequisiteError("context attempt must be a positive integer")

        try:
            snapshot = self.snapshot_manager.require_snapshot(commit_sha)
        except (SnapshotNotFoundError, SnapshotIntegrityError, ValueError) as exc:
            raise ContextPrerequisiteError("the execution structural snapshot is unavailable or invalid") from exc

        query_tokens = _normalize_tokens(request.query)
        if not query_tokens:
            raise ContextPrerequisiteError("context query has no eligible normalized token")
        manifest_spec = policy.required_artifacts_manifest[request.graph_type]
        artifact_evidence, manifest_result = self._load_artifacts(request, manifest_spec)
        symbol_tokens = tuple(
            (symbol, _normalize_tokens(f"{symbol.name} {symbol.qualified_name} {symbol.path}"))
            for symbol in snapshot.symbols
        )
        query_digest = "sha256:" + hashlib.sha256(request.query.encode("utf-8")).hexdigest()
        request_identity = ContextRequestIdentity(
            requirement_id=request.requirement_id,
            graph_type=request.graph_type,
            query_digest=query_digest,
        )
        try:
            report = ContextSufficiencyEvaluator.evaluate(
                request=request,
                request_identity=request_identity,
                workflow_name=workflow_name,
                commit_sha=commit_sha,
                policy=policy,
                policy_digest=policy_digest,
                attempt=attempt,
                manifest_spec=manifest_spec,
                manifest_result=manifest_result,
                artifact_evidence=artifact_evidence,
                snapshot=snapshot,
                query_tokens=query_tokens,
                symbol_tokens=symbol_tokens,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ContextPrerequisiteError("context evaluation inputs are inconsistent") from exc

        relevant_symbols = tuple(
            symbol for symbol, tokens in symbol_tokens if query_tokens & tokens
        )
        package = ContextPackage(
            report=report,
            knowledge_refs=artifact_evidence,
            structural_snapshot=snapshot,
            relevant_structural_symbols=relevant_symbols,
            relevant_symbols=tuple(symbol.qualified_name for symbol in relevant_symbols),
        )
        self._publish_latest(validated_execution_id, report)
        if not report.is_sufficient:
            raise InsufficientContextError(package)
        return package

    def _load_artifacts(
        self,
        request: RetrievalRequest,
        manifest_spec: object,
    ) -> tuple[tuple[ArtifactEvidence, ...], ManifestResult]:
        from ai_engineering_harness.contracts.policies import ArtifactManifestSpec

        if not isinstance(manifest_spec, ArtifactManifestSpec):
            raise ContextPrerequisiteError("compiled context manifest has an invalid type")
        expected = (
            manifest_spec.requirements
            + manifest_spec.acceptance_criteria
            + manifest_spec.architecture_constraints
        )
        root = self.project_root / ".harness" / "knowledge" / "artifacts"
        root_safe = self._artifact_root_is_safe(root)
        entries = self._artifact_directory_entries(root) if root_safe else ()

        evidence: list[ArtifactEvidence] = []
        missing: list[str] = []
        invalid: list[str] = []
        for artifact_id in expected:
            if _ARTIFACT_ID.fullmatch(artifact_id) is None:
                raise ContextPrerequisiteError("compiled context manifest contains an invalid artifact identity")
            exact_name = f"{artifact_id}.md"
            collisions = tuple(entry for entry in entries if entry.name.casefold() == exact_name.casefold())
            exact = root / exact_name
            if not root_safe:
                invalid.append(artifact_id)
                continue
            if len(collisions) > 1 or any(entry.name != exact_name for entry in collisions):
                invalid.append(artifact_id)
                continue
            if not exact.exists() and not exact.is_symlink():
                missing.append(artifact_id)
                continue
            item = self._read_artifact(artifact_id, exact)
            if item is None:
                invalid.append(artifact_id)
            else:
                evidence.append(item)

        present = tuple(item.artifact_id for item in evidence)
        result = ManifestResult(
            graph_type=request.graph_type,
            requirements_expected=manifest_spec.requirements,
            acceptance_criteria_expected=manifest_spec.acceptance_criteria,
            architecture_constraints_expected=manifest_spec.architecture_constraints,
            present_artifacts=present,
            missing_artifacts=tuple(missing),
            invalid_artifacts=tuple(invalid),
            all_required_present=len(present) == len(expected) and not missing and not invalid,
        )
        return tuple(evidence), result

    def _artifact_root_is_safe(self, root: Path) -> bool:
        current = self.project_root
        for part in root.relative_to(self.project_root).parts:
            current /= part
            if current.is_symlink():
                return False
        if not root.exists():
            return True
        try:
            return root.is_dir() and root.resolve(strict=True).is_relative_to(self.project_root)
        except (OSError, RuntimeError, ValueError):
            return False

    @staticmethod
    def _artifact_directory_entries(root: Path) -> tuple[Path, ...]:
        if not root.exists():
            return ()
        try:
            return tuple(sorted(root.iterdir(), key=lambda path: path.name))
        except OSError as exc:
            raise ContextPrerequisiteError(
                "context artifact directory could not be enumerated"
            ) from exc

    def _read_artifact(self, artifact_id: str, path: Path) -> ArtifactEvidence | None:
        if path.is_symlink() or not path.is_file():
            return None
        try:
            if not path.resolve(strict=True).is_relative_to(self.project_root):
                return None
            raw = path.read_bytes()
            text = raw.decode("utf-8", errors="strict")
            stat = path.stat(follow_symlinks=False)
        except (OSError, RuntimeError, UnicodeError, ValueError):
            return None
        if not text.strip() or stat.st_size <= 0:
            return None
        return ArtifactEvidence(
            artifact_id=artifact_id,
            relative_path=f".harness/knowledge/artifacts/{artifact_id}.md",
            digest="sha256:" + hashlib.sha256(raw).hexdigest(),
            size_bytes=stat.st_size,
            has_markdown_heading=_MARKDOWN_HEADING.search(text) is not None,
        )

    def _publish_latest(self, execution_id: str, report: ContextSufficiencyReport) -> None:
        destination = (
            self.project_root / ".harness" / "state" / "executions" / execution_id / "context.json"
        )
        try:
            self._prepare_execution_directory(destination.parent)
            if destination.is_symlink():
                raise OSError("context projection destination is a symbolic link")
            canonical = canonical_json_object(report.model_dump(mode="json"))
            _atomic_replace_text(destination, canonical)
            persisted = destination.read_text(encoding="utf-8", errors="strict")
            if persisted != canonical:
                raise OSError("context projection failed read-after-write validation")
        except (OSError, RuntimeError, UnicodeError, ValueError) as exc:
            raise ContextPrerequisiteError("context report could not be published atomically") from exc

    def _prepare_execution_directory(self, directory: Path) -> None:
        current = self.project_root
        for part in directory.relative_to(self.project_root).parts:
            current /= part
            if current.is_symlink():
                raise OSError("context state path traverses a symbolic link")
        directory.mkdir(parents=True, exist_ok=True)
        canonical = directory.resolve(strict=True)
        if not canonical.is_relative_to(self.project_root) or not canonical.is_dir():
            raise OSError("context state directory escapes the project root")


def _normalize_tokens(value: str) -> frozenset[str]:
    normalized = unicodedata.normalize("NFKD", value)
    without_marks = "".join(character for character in normalized if not unicodedata.combining(character))
    ascii_lower = without_marks.encode("ascii", errors="ignore").decode("ascii").lower()
    return frozenset(
        token for token in _TOKEN.findall(ascii_lower) if len(token) >= 2 and token not in _STOPLIST
    )


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
    "ContextAssembler",
    "ContextAssemblyError",
    "ContextPackage",
    "ContextPrerequisiteError",
    "InsufficientContextError",
]
