"""Testes unitários de validação e serialização dos contratos Pydantic nativos (TASK-1.2)."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from ai_engineering_harness.contracts.events import ExecutionEvent
from ai_engineering_harness.contracts.nodes import (
    CONTEXT_DIMENSION_ORDER,
    ContextDimension,
    ContextRequestIdentity,
    ContextSufficiencyReport,
    ManifestResult,
)
from ai_engineering_harness.contracts.transactions import KnowledgeTransaction


def test_execution_event_serialization():
    now = datetime.now(UTC)
    event = ExecutionEvent(
        event_id="evt-100",
        execution_id="exec-42",
        event_type="STEP_COMPLETED",
        timestamp=now,
        payload={"step": "code_gen", "status": "GREEN"},
        previous_hash="hash-1",
        current_hash="hash-2"
    )
    json_str = event.model_dump_json()
    restored = ExecutionEvent.model_validate_json(json_str)
    assert restored.event_id == "evt-100"
    assert restored.execution_id == "exec-42"
    assert restored.payload["status"] == "GREEN"

def test_context_sufficiency_report():
    report = ContextSufficiencyReport(
        request=ContextRequestIdentity(
            requirement_id="req-1",
            graph_type="new_feature",
            query_digest="sha256:" + "1" * 64,
        ),
        workflow_name="new-feature",
        commit_sha="a" * 40,
        policy_id="context-sufficiency-v1",
        policy_schema_version="1.0",
        policy_definition_version="3.2.0",
        policy_digest="sha256:" + "2" * 64,
        attempt=1,
        manifest=ManifestResult(
            graph_type="new_feature",
            requirements_expected=("prd",),
            acceptance_criteria_expected=("acceptance_criteria",),
            architecture_constraints_expected=("architecture",),
            present_artifacts=(),
            missing_artifacts=("prd", "acceptance_criteria", "architecture"),
            invalid_artifacts=(),
            all_required_present=False,
        ),
        artifact_evidence=(),
        dimensions=tuple(
            ContextDimension(
                dimension_id=dimension_id,
                score=Decimal("0.000000"),
                evidence=(),
                reason="no validated evidence",
                gaps=("evidence is missing",),
                recommended_action="retrieve_more",
            )
            for dimension_id in CONTEXT_DIMENSION_ORDER
        ),
        confidence=Decimal("0.000000"),
        threshold=Decimal("0.720000"),
        is_sufficient=False,
        gaps=("missing_artifact:prd",),
        recommended_action="retrieve_more",
    )
    assert report.is_sufficient is False
    assert tuple(dimension.dimension_id for dimension in report.dimensions) == CONTEXT_DIMENSION_ORDER

def test_knowledge_transaction_strict_validation():
    now = datetime.now(UTC)
    tx = KnowledgeTransaction(
        tx_id="tx-99",
        status="COMMITTED",
        created_at=now,
        staging_path=".harness/knowledge/staging/tx-99/",
        artifact_ids=["ki-1", "ki-2"]
    )
    assert tx.status == "COMMITTED"
    
    with pytest.raises(ValidationError):
        # Campos faltantes devem disparar ValidationError
        KnowledgeTransaction(tx_id="tx-100")
