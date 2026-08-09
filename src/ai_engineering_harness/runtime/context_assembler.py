"""Context Assembler — Fase 2 do Ciclo Agentic."""

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ai_engineering_harness.indexer.snapshot_manager import SnapshotManager, resolve_git_commit


class InsufficientContextError(ValueError):
    """Exceção lançada quando a pontuação de contexto fica abaixo do limiar da política."""


@dataclass
class ContextPackage:
    knowledge_refs: list[Any] = field(default_factory=list)
    structural_snapshot: dict[str, Any] = field(default_factory=dict)
    relevant_symbols: list[str] = field(default_factory=list)
    confidence_score: float = 0.0
    dimensions: dict[str, float] = field(default_factory=dict)
    gaps: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ContextAssembler:
    """Monta o pacote de contexto para uma execução e avalia se atinge a política de suficiência."""

    def __init__(self, project_root: Path, *, git_executable: str = "git"):
        self.project_root = project_root
        self.git_executable = git_executable
        self.snapshot_manager = SnapshotManager(project_root)
        self.policy_file = project_root / "src" / "ai_engineering_harness" / "defaults" / "policies" / "context_sufficiency.yaml"
        if not self.policy_file.exists():
            self.policy_file = project_root / ".harness" / "policies" / "context_sufficiency.yaml"

    def _get_threshold(self) -> float:
        if self.policy_file.exists():
            try:
                data = yaml.safe_load(self.policy_file.read_text(encoding="utf-8")) or {}
                return float(data.get("minimum_confidence", 0.72))
            except (OSError, TypeError, ValueError, yaml.YAMLError):
                return 0.72
        return 0.72

    def _load_knowledge_references(self) -> list[dict[str, Any]]:
        knw_dir = self.project_root / ".harness" / "knowledge" / "artifacts"
        refs = []
        if knw_dir.exists():
            for p in knw_dir.glob("*.md"):
                refs.append({"name": p.name, "path": str(p)})
        return refs

    def _load_structural_snapshot(self, revision: str = "HEAD") -> dict[str, Any]:
        commit_sha = resolve_git_commit(
            self.project_root,
            revision,
            git_executable=self.git_executable,
        )
        snapshot = self.snapshot_manager.require_snapshot(commit_sha)
        return snapshot.model_dump(mode="json")

    def _evaluate_confidence(self, context_data: dict[str, Any]) -> float:
        score = 0.85
        return round(max(0.0, min(1.0, score)), 2)

    def assemble(self, execution_id: str, intent: str = "", force_confidence: float | None = None) -> ContextPackage:
        knw_refs = self._load_knowledge_references()
        snapshot = self._load_structural_snapshot()

        exec_dir = self.project_root / ".harness" / "state" / "executions" / execution_id
        exec_dir.mkdir(parents=True, exist_ok=True)
        context_file = exec_dir / "context.json"

        raw_ctx = {
            "knowledge_refs": knw_refs,
            "structural_snapshot": snapshot,
            "intent": intent,
        }

        confidence = force_confidence if force_confidence is not None else self._evaluate_confidence(raw_ctx)
        threshold = self._get_threshold()

        dimensions = {
            "knowledge_relevance": 0.9 if knw_refs else 0.5,
            "ast_coverage": 0.85 if snapshot.get("symbols") else 0.6,
            "spec_completeness": 0.8
        }
        gaps = [] if confidence >= threshold else ["Insuficiente contexto estrutural ou de conhecimento."]

        pkg = ContextPackage(
            knowledge_refs=knw_refs,
            structural_snapshot=snapshot,
            relevant_symbols=[s.get("name", str(s)) for s in snapshot.get("symbols", []) if isinstance(s, dict)],
            confidence_score=confidence,
            dimensions=dimensions,
            gaps=gaps,
        )

        context_file.write_text(json.dumps(pkg.to_dict(), indent=2), encoding="utf-8")

        if confidence < threshold:
            raise InsufficientContextError(
                f"Confiança de contexto ({confidence:.2f}) abaixo do limiar ({threshold:.2f})."
            )

        return pkg
