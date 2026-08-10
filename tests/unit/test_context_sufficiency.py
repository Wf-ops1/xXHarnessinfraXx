"""Frozen F4.3 evidence, formula, persistence, and negative-path acceptance."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

import ai_engineering_harness.runtime.context_assembler as context_module
from ai_engineering_harness.contracts.nodes import (
    CONTEXT_DIMENSION_ORDER,
    ContextSufficiencyReport,
    RetrievalRequest,
)
from ai_engineering_harness.contracts.policies import ContextSufficiencyPolicySpec
from ai_engineering_harness.contracts.structural_index import StructuralSymbol
from ai_engineering_harness.indexer import SnapshotManager
from ai_engineering_harness.persistence import canonical_json_digest, canonical_json_object
from ai_engineering_harness.runtime import (
    ContextAssembler,
    ContextPrerequisiteError,
    InsufficientContextError,
)

ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = (
    ROOT
    / "src"
    / "ai_engineering_harness"
    / "defaults"
    / "policies"
    / "context_sufficiency.yaml"
)
COMMIT_SHA = "a" * 40


def _policy_document() -> dict[str, object]:
    document = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def _policy() -> ContextSufficiencyPolicySpec:
    return ContextSufficiencyPolicySpec.model_validate(_policy_document())


def _policy_digest(policy: ContextSufficiencyPolicySpec) -> str:
    return canonical_json_digest(canonical_json_object(policy.model_dump(mode="json")))


def _request() -> RetrievalRequest:
    return RetrievalRequest(
        requirement_id="req-logging",
        graph_type="new_feature",
        query="Add logging",
    )


def _save_snapshot(project_root: Path, *, symbols: bool = True) -> None:
    selected = (
        [
            StructuralSymbol(
                kind="function",
                name="logging",
                qualified_name="logging",
                path="logging",
                line_start=1,
                line_end=3,
            )
        ]
        if symbols
        else []
    )
    SnapshotManager(project_root).save_snapshot(COMMIT_SHA, selected)


def _write_required_artifacts(project_root: Path, *, omit: str | None = None) -> None:
    manifest = _policy().required_artifacts_manifest["new_feature"]
    root = project_root / ".harness" / "knowledge" / "artifacts"
    root.mkdir(parents=True, exist_ok=True)
    for artifact_id in (
        manifest.requirements
        + manifest.acceptance_criteria
        + manifest.architecture_constraints
    ):
        if artifact_id == omit:
            continue
        (root / f"{artifact_id}.md").write_text(
            f"# {artifact_id}\n\nprivate-evidence-{artifact_id}\n",
            encoding="utf-8",
        )


def _assemble(project_root: Path, *, execution_id: str = "exec-context"):
    policy = _policy()
    return ContextAssembler(project_root).assemble(
        execution_id=execution_id,
        request=_request(),
        workflow_name="new-feature",
        commit_sha=COMMIT_SHA,
        policy=policy,
        policy_digest=_policy_digest(policy),
        attempt=1,
    )


def test_sufficient_context_uses_six_decimal_formulas_and_full_relevant_symbols(
    tmp_path: Path,
) -> None:
    _save_snapshot(tmp_path)
    _write_required_artifacts(tmp_path)

    package = _assemble(tmp_path)
    report = package.report
    dimensions = {dimension.dimension_id: dimension.score for dimension in report.dimensions}

    assert tuple(dimensions) == CONTEXT_DIMENSION_ORDER
    assert dimensions == {
        "requirements": Decimal("1.000000"),
        "acceptance_criteria": Decimal("1.000000"),
        "structural_coverage": Decimal("1.000000"),
        "symbol_relevance": Decimal("1.000000"),
        "architecture_constraints": Decimal("1.000000"),
        "conflicts_and_gaps": Decimal("1.000000"),
    }
    assert report.confidence == Decimal("1.000000")
    assert report.threshold == Decimal("0.720000")
    assert report.is_sufficient is True
    assert report.recommended_action == "proceed"
    assert package.relevant_structural_symbols == package.structural_snapshot.symbols
    assert package.relevant_symbols == ("logging",)


def test_report_projection_is_canonical_deterministic_and_contains_no_raw_artifact(
    tmp_path: Path,
) -> None:
    _save_snapshot(tmp_path)
    _write_required_artifacts(tmp_path)

    first = _assemble(tmp_path, execution_id="exec-context-a")
    second = _assemble(tmp_path, execution_id="exec-context-b")
    first_path = tmp_path / ".harness" / "state" / "executions" / "exec-context-a" / "context.json"
    second_path = tmp_path / ".harness" / "state" / "executions" / "exec-context-b" / "context.json"

    assert first.report == second.report
    assert first_path.read_bytes() == second_path.read_bytes()
    persisted = first_path.read_text(encoding="utf-8")
    assert persisted == canonical_json_object(first.report.model_dump(mode="json"))
    assert "private-evidence" not in persisted
    assert "Add logging" not in persisted
    assert ContextSufficiencyReport.model_validate_json(persisted) == first.report


def test_missing_required_artifact_blocks_even_when_weighted_score_is_high(tmp_path: Path) -> None:
    _save_snapshot(tmp_path)
    _write_required_artifacts(tmp_path, omit="prd")

    with pytest.raises(InsufficientContextError) as raised:
        _assemble(tmp_path)

    report = raised.value.report
    assert report.is_sufficient is False
    assert report.confidence >= report.threshold
    assert report.manifest.missing_artifacts == ("prd",)
    assert "missing_artifact:prd" in report.gaps
    assert report.recommended_action == "retrieve_more"
    assert (
        tmp_path / ".harness" / "state" / "executions" / "exec-context" / "context.json"
    ).is_file()


def test_empty_snapshot_and_zero_relevance_are_insufficient_without_fabricated_score(
    tmp_path: Path,
) -> None:
    _save_snapshot(tmp_path, symbols=False)
    _write_required_artifacts(tmp_path)

    with pytest.raises(InsufficientContextError) as raised:
        _assemble(tmp_path)

    dimensions = {
        dimension.dimension_id: dimension.score for dimension in raised.value.report.dimensions
    }
    assert dimensions["structural_coverage"] == Decimal("0.000000")
    assert dimensions["symbol_relevance"] == Decimal("0.000000")
    assert dimensions["conflicts_and_gaps"] == Decimal("0.000000")
    assert "structural_snapshot_empty" in raised.value.gaps


def test_invalid_utf8_and_case_divergent_artifacts_are_structural_conflicts(tmp_path: Path) -> None:
    _save_snapshot(tmp_path)
    _write_required_artifacts(tmp_path, omit="prd")
    artifact_root = tmp_path / ".harness" / "knowledge" / "artifacts"
    (artifact_root / "PRD.md").write_bytes(b"\xff\xfe")

    with pytest.raises(InsufficientContextError) as raised:
        _assemble(tmp_path)

    assert raised.value.report.manifest.invalid_artifacts == ("prd",)
    assert raised.value.report.recommended_action == "request_human"
    assert all(item.artifact_id != "prd" for item in raised.value.report.artifact_evidence)


def test_symbolic_link_artifact_is_invalid_and_never_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _save_snapshot(tmp_path)
    _write_required_artifacts(tmp_path, omit="prd")
    artifact_root = tmp_path / ".harness" / "knowledge" / "artifacts"
    linked_artifact = artifact_root / "prd.md"
    original_is_symlink = Path.is_symlink

    def report_link(path: Path) -> bool:
        return path == linked_artifact or original_is_symlink(path)

    monkeypatch.setattr(Path, "is_symlink", report_link)

    with pytest.raises(InsufficientContextError) as raised:
        _assemble(tmp_path)

    assert raised.value.report.manifest.invalid_artifacts == ("prd",)
    projection = tmp_path / ".harness" / "state" / "executions" / "exec-context" / "context.json"
    assert "prd" not in {
        item["artifact_id"]
        for item in json.loads(projection.read_text(encoding="utf-8"))["artifact_evidence"]
    }


def test_execution_identity_cannot_escape_context_state_root(tmp_path: Path) -> None:
    _save_snapshot(tmp_path)
    _write_required_artifacts(tmp_path)

    with pytest.raises(ContextPrerequisiteError, match="execution identity"):
        _assemble(tmp_path, execution_id="../escape")

    assert not (tmp_path / ".harness" / "state" / "escape" / "context.json").exists()


def test_missing_or_corrupt_snapshot_is_a_prerequisite_and_writes_no_projection(
    tmp_path: Path,
) -> None:
    _write_required_artifacts(tmp_path)

    with pytest.raises(ContextPrerequisiteError, match="snapshot"):
        _assemble(tmp_path)

    assert not (tmp_path / ".harness" / "state" / "executions" / "exec-context").exists()


def test_atomic_projection_failure_leaves_no_partial_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _save_snapshot(tmp_path)
    _write_required_artifacts(tmp_path)

    def fail_atomic_write(_destination: Path, _content: str) -> None:
        raise OSError("controlled atomic write failure")

    monkeypatch.setattr(context_module, "_atomic_replace_text", fail_atomic_write)
    with pytest.raises(ContextPrerequisiteError, match="atomically"):
        _assemble(tmp_path)

    context_path = tmp_path / ".harness" / "state" / "executions" / "exec-context" / "context.json"
    assert not context_path.exists()
    assert not tuple(context_path.parent.glob("*.tmp"))


def test_context_projection_refuses_symbolic_link_destination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _save_snapshot(tmp_path)
    _write_required_artifacts(tmp_path)
    context_path = tmp_path / ".harness" / "state" / "executions" / "exec-context" / "context.json"
    original_is_symlink = Path.is_symlink

    def report_link(path: Path) -> bool:
        return path == context_path or original_is_symlink(path)

    monkeypatch.setattr(Path, "is_symlink", report_link)

    with pytest.raises(ContextPrerequisiteError, match="atomically"):
        _assemble(tmp_path)

    assert not context_path.exists()


def test_policy_rejects_free_text_conditional_and_noncanonical_weights() -> None:
    conditional = _policy_document()
    manifests = conditional["required_artifacts_manifest"]
    assert isinstance(manifests, dict)
    new_feature = manifests["new_feature"]
    assert isinstance(new_feature, dict)
    new_feature["conditional"] = ["architecture_change_required == true"]
    with pytest.raises(ValidationError, match="conditional artifacts"):
        ContextSufficiencyPolicySpec.model_validate(conditional)

    wrong_weight = _policy_document()
    weights = wrong_weight["dimension_weights"]
    assert isinstance(weights, dict)
    weights["requirements"] = "0.24"
    with pytest.raises(ValidationError, match="canonical weights"):
        ContextSufficiencyPolicySpec.model_validate(wrong_weight)


def test_request_rejects_incident_empty_query_and_score_override(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        RetrievalRequest(requirement_id="req", graph_type="incident", query="failure")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        RetrievalRequest(requirement_id="req", graph_type="new_feature", query=" ")

    _save_snapshot(tmp_path)
    _write_required_artifacts(tmp_path)
    with pytest.raises(TypeError, match="force_confidence"):
        ContextAssembler(tmp_path).assemble(  # type: ignore[call-arg]
            execution_id="exec-context",
            request=_request(),
            workflow_name="new-feature",
            commit_sha=COMMIT_SHA,
            policy=_policy(),
            policy_digest=_policy_digest(_policy()),
            attempt=1,
            force_confidence=Decimal(1),
        )


def test_context_json_is_valid_json_without_nan(tmp_path: Path) -> None:
    _save_snapshot(tmp_path)
    _write_required_artifacts(tmp_path)
    _assemble(tmp_path)
    context_path = tmp_path / ".harness" / "state" / "executions" / "exec-context" / "context.json"
    document = json.loads(context_path.read_text(encoding="utf-8"))
    assert document["schema_version"] == "1.0"
