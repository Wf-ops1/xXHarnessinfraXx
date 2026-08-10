"""Deterministic evidence-based context sufficiency evaluation."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from decimal import ROUND_HALF_EVEN, Decimal

from ai_engineering_harness.contracts.nodes import (
    CONTEXT_DIMENSION_ORDER,
    ArtifactEvidence,
    ContextAction,
    ContextDimension,
    ContextRequestIdentity,
    ContextSufficiencyReport,
    EvidenceReference,
    ManifestResult,
    RetrievalRequest,
)
from ai_engineering_harness.contracts.policies import ArtifactManifestSpec, ContextSufficiencyPolicySpec
from ai_engineering_harness.contracts.structural_index import StructuralSnapshot, StructuralSymbol

_SCORE_QUANTUM = Decimal("0.000001")


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(_SCORE_QUANTUM, rounding=ROUND_HALF_EVEN)


def _ratio(numerator: int, denominator: int) -> Decimal:
    if denominator <= 0:
        raise ValueError("context dimension denominator must be positive")
    return _quantize(Decimal(numerator) / Decimal(denominator))


def _artifact_references(
    artifact_ids: tuple[str, ...],
    evidence_by_id: Mapping[str, ArtifactEvidence],
) -> tuple[EvidenceReference, ...]:
    return tuple(
        EvidenceReference(
            kind="artifact",
            identifier=artifact_id,
            digest=evidence_by_id[artifact_id].digest,
        )
        for artifact_id in artifact_ids
        if artifact_id in evidence_by_id
    )


class ContextSufficiencyEvaluator:
    """Calculate the six frozen dimensions and enforce the discrete dual gate."""

    @classmethod
    def evaluate(
        cls,
        *,
        request: RetrievalRequest,
        request_identity: ContextRequestIdentity,
        workflow_name: str,
        commit_sha: str,
        policy: ContextSufficiencyPolicySpec,
        policy_digest: str,
        attempt: int,
        manifest_spec: ArtifactManifestSpec,
        manifest_result: ManifestResult,
        artifact_evidence: tuple[ArtifactEvidence, ...],
        snapshot: StructuralSnapshot,
        query_tokens: frozenset[str],
        symbol_tokens: tuple[tuple[StructuralSymbol, frozenset[str]], ...],
    ) -> ContextSufficiencyReport:
        """Return the exact report used by lifecycle persistence and routing."""

        if request.requirement_id != request_identity.requirement_id:
            raise ValueError("request identity requirement_id does not match retrieval request")
        if request.graph_type != request_identity.graph_type:
            raise ValueError("request identity does not match retrieval request")
        expected_query_digest = "sha256:" + hashlib.sha256(request.query.encode("utf-8")).hexdigest()
        if request_identity.query_digest != expected_query_digest:
            raise ValueError("request identity query_digest does not match retrieval request")
        if manifest_result.graph_type != request.graph_type:
            raise ValueError("manifest result graph_type does not match retrieval request")
        if (
            manifest_result.requirements_expected != manifest_spec.requirements
            or manifest_result.acceptance_criteria_expected != manifest_spec.acceptance_criteria
            or manifest_result.architecture_constraints_expected
            != manifest_spec.architecture_constraints
        ):
            raise ValueError("manifest result does not match the selected manifest specification")
        if snapshot.commit_sha != commit_sha:
            raise ValueError("structural snapshot does not match the execution commit")
        if not query_tokens:
            raise ValueError("query_tokens must not be empty")

        evidence_ids = tuple(item.artifact_id for item in artifact_evidence)
        if len(evidence_ids) != len(set(evidence_ids)) or set(evidence_ids) != set(
            manifest_result.present_artifacts
        ):
            raise ValueError("artifact evidence must exactly match present manifest artifacts")
        evidence_by_id = {item.artifact_id: item for item in artifact_evidence}
        present = set(manifest_result.present_artifacts)
        relevant = tuple((symbol, tokens) for symbol, tokens in symbol_tokens if query_tokens & tokens)
        covered_tokens = frozenset().union(*(query_tokens & tokens for _, tokens in relevant)) if relevant else frozenset()

        requirements_present = tuple(item for item in manifest_spec.requirements if item in present)
        acceptance_present = tuple(item for item in manifest_spec.acceptance_criteria if item in present)
        architecture_present = tuple(
            item for item in manifest_spec.architecture_constraints if item in present
        )

        requirements_score = _ratio(len(requirements_present), len(manifest_spec.requirements))
        acceptance_score = _ratio(len(acceptance_present), len(manifest_spec.acceptance_criteria))
        architecture_score = _ratio(
            len(architecture_present), len(manifest_spec.architecture_constraints)
        )
        structural_score = _ratio(len(covered_tokens), len(query_tokens))

        jaccard_scores = (
            _ratio(len(query_tokens & tokens), len(query_tokens | tokens))
            for _, tokens in relevant
        )
        symbol_relevance_score = max(jaccard_scores, default=Decimal("0.000000"))
        conflict_free = (
            manifest_result.all_required_present
            and bool(snapshot.symbols)
            and bool(relevant)
            and not manifest_result.missing_artifacts
            and not manifest_result.invalid_artifacts
        )
        conflicts_score = Decimal("1.000000") if conflict_free else Decimal("0.000000")

        query_reference = EvidenceReference(
            kind="query",
            identifier="normalized_query",
            digest=request_identity.query_digest,
        )
        snapshot_reference = EvidenceReference(
            kind="snapshot",
            identifier=commit_sha,
            digest=snapshot.digest,
        )
        symbol_references = tuple(
            EvidenceReference(
                kind="symbol",
                identifier=f"{symbol.path}:{symbol.line_start}:{symbol.qualified_name}",
            )
            for symbol, _ in relevant
        )

        dimensions = (
            ContextDimension(
                dimension_id="requirements",
                score=requirements_score,
                evidence=_artifact_references(requirements_present, evidence_by_id),
                reason="valid required knowledge artifacts divided by expected requirement artifacts",
                gaps=() if requirements_score == 1 else ("required knowledge artifacts are missing or invalid",),
                recommended_action="proceed" if requirements_score == 1 else "retrieve_more",
            ),
            ContextDimension(
                dimension_id="acceptance_criteria",
                score=acceptance_score,
                evidence=_artifact_references(acceptance_present, evidence_by_id),
                reason="valid acceptance artifacts divided by expected acceptance artifacts",
                gaps=() if acceptance_score == 1 else ("acceptance criteria artifacts are missing or invalid",),
                recommended_action="proceed" if acceptance_score == 1 else "retrieve_more",
            ),
            ContextDimension(
                dimension_id="structural_coverage",
                score=structural_score,
                evidence=(query_reference, snapshot_reference),
                reason="eligible query tokens found in at least one structural symbol divided by query tokens",
                gaps=() if structural_score == 1 else ("the structural snapshot does not cover every query token",),
                recommended_action="proceed" if structural_score == 1 else "retrieve_more",
            ),
            ContextDimension(
                dimension_id="symbol_relevance",
                score=symbol_relevance_score,
                evidence=(query_reference, *symbol_references),
                reason="maximum Jaccard similarity between query tokens and one relevant structural symbol",
                gaps=() if relevant else ("no structural symbol intersects the normalized query",),
                recommended_action="proceed" if relevant else "retrieve_more",
            ),
            ContextDimension(
                dimension_id="architecture_constraints",
                score=architecture_score,
                evidence=_artifact_references(architecture_present, evidence_by_id),
                reason="valid architecture artifacts divided by expected architecture artifacts",
                gaps=() if architecture_score == 1 else ("architecture artifacts are missing or invalid",),
                recommended_action="proceed" if architecture_score == 1 else "retrieve_more",
            ),
            ContextDimension(
                dimension_id="conflicts_and_gaps",
                score=conflicts_score,
                evidence=(snapshot_reference, *_artifact_references(tuple(sorted(present)), evidence_by_id)),
                reason=(
                    "structural checks found an exact manifest/evidence partition and no missing, "
                    "invalid, case-colliding, snapshot, query, or relevance gap; artifact digests "
                    "identify the bytes read in this attempt, but no external expected digest or "
                    "semantic contradiction analysis is claimed"
                ),
                gaps=() if conflict_free else ("one or more structural evidence gaps remain",),
                recommended_action=(
                    "proceed"
                    if conflict_free
                    else "request_human"
                    if manifest_result.invalid_artifacts
                    else "retrieve_more"
                ),
            ),
        )
        if tuple(dimension.dimension_id for dimension in dimensions) != CONTEXT_DIMENSION_ORDER:
            raise AssertionError("canonical context dimensions are out of order")

        weighted = sum(
            (
                dimension.score * policy.dimension_weights[dimension.dimension_id]
                for dimension in dimensions
            ),
            Decimal(0),
        )
        confidence = _quantize(weighted)
        discrete_gate = (
            manifest_result.all_required_present
            and bool(snapshot.symbols)
            and bool(relevant)
            and conflicts_score == Decimal("1.000000")
        )
        is_sufficient = discrete_gate and confidence >= policy.minimum_confidence

        gaps: list[str] = []
        gaps.extend(f"missing_artifact:{artifact_id}" for artifact_id in manifest_result.missing_artifacts)
        gaps.extend(f"invalid_artifact:{artifact_id}" for artifact_id in manifest_result.invalid_artifacts)
        if not snapshot.symbols:
            gaps.append("structural_snapshot_empty")
        elif not relevant:
            gaps.append("no_relevant_structural_symbol")
        if conflicts_score != Decimal("1.000000"):
            gaps.append("structural_conflicts_or_gaps")
        if confidence < policy.minimum_confidence:
            gaps.append("confidence_below_threshold")
        if not gaps and not is_sufficient:
            gaps.append("dual_gate_not_satisfied")

        action: ContextAction = (
            "proceed"
            if is_sufficient
            else "request_human"
            if manifest_result.invalid_artifacts
            else "retrieve_more"
        )
        return ContextSufficiencyReport(
            request=request_identity,
            workflow_name=workflow_name,
            commit_sha=commit_sha,
            policy_id=policy.policy_id,
            policy_schema_version=policy.policy_schema_version,
            policy_definition_version=policy.definition_version,
            policy_digest=policy_digest,
            attempt=attempt,
            manifest=manifest_result,
            artifact_evidence=tuple(sorted(artifact_evidence, key=lambda item: item.artifact_id)),
            dimensions=dimensions,
            confidence=confidence,
            threshold=_quantize(policy.minimum_confidence),
            is_sufficient=is_sufficient,
            gaps=tuple(gaps),
            recommended_action=action,
        )


__all__ = ["ContextSufficiencyEvaluator"]
