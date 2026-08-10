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
    ArtifactEvidence,
    ContextRequestIdentity,
    ContextSufficiencyReport,
    ManifestResult,
    RetrievalRequest,
)
from ai_engineering_harness.contracts.policies import (
    ArtifactManifestSpec,
    ContextSufficiencyPolicySpec,
)
from ai_engineering_harness.contracts.structural_index import StructuralSymbol
from ai_engineering_harness.governance import ContextSufficiencyEvaluator
from ai_engineering_harness.indexer import SnapshotManager
from ai_engineering_harness.persistence import canonical_json_digest, canonical_json_object
from ai_engineering_harness.runtime import (
    ContextAssembler,
    ContextPackage,
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


def _evaluate_direct(
    package: ContextPackage,
    *,
    request: RetrievalRequest | None = None,
    request_identity: ContextRequestIdentity | None = None,
    manifest_spec: ArtifactManifestSpec | None = None,
    manifest_result: ManifestResult | None = None,
    artifact_evidence: tuple[ArtifactEvidence, ...] | None = None,
) -> ContextSufficiencyReport:
    policy = _policy()
    selected_request = request if request is not None else _request()
    selected_manifest = (
        manifest_spec
        if manifest_spec is not None
        else policy.required_artifacts_manifest[selected_request.graph_type]
    )
    selected_evidence = (
        artifact_evidence if artifact_evidence is not None else package.knowledge_refs
    )
    return ContextSufficiencyEvaluator.evaluate(
        request=selected_request,
        request_identity=(
            request_identity if request_identity is not None else package.report.request
        ),
        workflow_name="new-feature",
        commit_sha=COMMIT_SHA,
        policy=policy,
        policy_digest=_policy_digest(policy),
        attempt=1,
        manifest_spec=selected_manifest,
        manifest_result=(
            manifest_result if manifest_result is not None else package.report.manifest
        ),
        artifact_evidence=selected_evidence,
        snapshot=package.structural_snapshot,
        query_tokens=frozenset({"logging"}),
        symbol_tokens=tuple(
            (symbol, frozenset({"logging"}))
            for symbol in package.structural_snapshot.symbols
        ),
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
    conflicts = report.dimensions[-1]
    assert "external expected digest" in conflicts.reason
    assert "digest-divergent" not in conflicts.reason


def test_artifact_evidence_path_must_match_artifact_identity() -> None:
    with pytest.raises(ValidationError, match="path must match artifact_id"):
        ArtifactEvidence(
            artifact_id="prd",
            relative_path=".harness/knowledge/artifacts/architecture.md",
            digest="sha256:" + "0" * 64,
            size_bytes=1,
            has_markdown_heading=True,
        )


def test_evaluator_rejects_missing_or_extra_artifact_evidence(tmp_path: Path) -> None:
    _save_snapshot(tmp_path)
    _write_required_artifacts(tmp_path)
    package = _assemble(tmp_path)

    with pytest.raises(ValueError, match="exactly match present manifest artifacts"):
        _evaluate_direct(package, artifact_evidence=())

    extra = ArtifactEvidence(
        artifact_id="extra",
        relative_path=".harness/knowledge/artifacts/extra.md",
        digest="sha256:" + "0" * 64,
        size_bytes=1,
        has_markdown_heading=True,
    )
    with pytest.raises(ValueError, match="exactly match present manifest artifacts"):
        _evaluate_direct(package, artifact_evidence=(*package.knowledge_refs, extra))


def test_canonical_report_rejects_manifest_without_exact_artifact_evidence(
    tmp_path: Path,
) -> None:
    _save_snapshot(tmp_path)
    _write_required_artifacts(tmp_path)
    package = _assemble(tmp_path)
    document = package.report.model_dump(mode="python")
    document["artifact_evidence"] = ()

    with pytest.raises(ValidationError, match="exactly match present manifest artifacts"):
        ContextSufficiencyReport.model_validate(document)


def test_evaluator_binds_request_requirement_and_query_digest(tmp_path: Path) -> None:
    _save_snapshot(tmp_path)
    _write_required_artifacts(tmp_path)
    package = _assemble(tmp_path)
    wrong_requirement = ContextRequestIdentity(
        requirement_id="req-other",
        graph_type="new_feature",
        query_digest=package.report.request.query_digest,
    )
    wrong_query = ContextRequestIdentity(
        requirement_id=_request().requirement_id,
        graph_type="new_feature",
        query_digest="sha256:" + "0" * 64,
    )

    with pytest.raises(ValueError, match="requirement_id does not match"):
        _evaluate_direct(package, request_identity=wrong_requirement)
    with pytest.raises(ValueError, match="query_digest does not match"):
        _evaluate_direct(package, request_identity=wrong_query)


def test_evaluator_binds_manifest_result_to_selected_spec(tmp_path: Path) -> None:
    _save_snapshot(tmp_path)
    _write_required_artifacts(tmp_path)
    package = _assemble(tmp_path)
    original = package.report.manifest
    mismatched = ManifestResult(
        graph_type=original.graph_type,
        requirements_expected=(
            original.acceptance_criteria_expected[0],
            *original.requirements_expected[1:],
        ),
        acceptance_criteria_expected=(original.requirements_expected[0],),
        architecture_constraints_expected=original.architecture_constraints_expected,
        present_artifacts=original.present_artifacts,
        missing_artifacts=(),
        invalid_artifacts=(),
        all_required_present=True,
    )

    with pytest.raises(ValueError, match="selected manifest specification"):
        _evaluate_direct(package, manifest_result=mismatched)


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
