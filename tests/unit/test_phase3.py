"""Testes unitários para Fase 3 (Doctor & Governance Engine)."""

import pytest

from ai_engineering_harness.doctor.checker import DoctorChecker
from ai_engineering_harness.doctor.probes import HealthProbe
from ai_engineering_harness.governance.evaluation import ContextSufficiencyEvaluator
from ai_engineering_harness.governance.policy_engine import PolicyEngine


def test_doctor_probe_6_stages():
    res = HealthProbe.probe_component("Serena MCP", {})
    assert res.is_healthy is True
    assert len(res.stages) == 6
    assert res.stages["healthy"].status == "OK"

def test_doctor_checker():
    checker = DoctorChecker(config={})
    results = checker.check_all()
    assert len(results) == 4
    assert all(r.is_healthy for r in results)

def test_policy_engine_budget_exceeded():
    engine = PolicyEngine(config={"budget": {"max_tokens": 100}})
    engine.record_usage(50)
    with pytest.raises(RuntimeError) as exc_info:
        engine.record_usage(60)
    assert "[BUDGET EXCEEDED]" in str(exc_info.value)

def test_context_sufficiency_evaluation():
    with pytest.raises(TypeError):
        ContextSufficiencyEvaluator.evaluate(  # type: ignore[call-arg]
            {"requirements": 1.0},
            required_threshold=0.72,
        )
