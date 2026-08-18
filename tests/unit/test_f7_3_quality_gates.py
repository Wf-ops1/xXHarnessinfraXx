"""Executable contracts for the F7.3 coverage and security gates."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
CI_ROOT = ROOT / "tests" / "ci"


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


COVERAGE_GATE = _load_module(
    "f7_3_coverage_gate_for_tests",
    CI_ROOT / "check_f7_3_coverage.py",
)
SECURITY_GATE = _load_module(
    "f7_3_security_gate_for_tests",
    CI_ROOT / "check_f7_3_security.py",
)

EXPECTED_CORE = (
    "src/ai_engineering_harness/governance/approval.py",
    "src/ai_engineering_harness/governance/policy_engine.py",
    "src/ai_engineering_harness/runtime/state_machine.py",
    "src/ai_engineering_harness/security/path_guard.py",
    "src/ai_engineering_harness/security/trust.py",
    "src/ai_engineering_harness/tools/router.py",
)
EXPECTED_DECISIONS = (
    (EXPECTED_CORE[0], "ApprovalRequest.validate_decision_and_binding"),
    (EXPECTED_CORE[0], "ApprovalRequest.approve"),
    (EXPECTED_CORE[0], "ApprovalRequest.expire"),
    (EXPECTED_CORE[0], "ApprovalRequest.invalidate"),
    (EXPECTED_CORE[1], "PolicyEngine.evaluate"),
    (EXPECTED_CORE[1], "PolicyEngine.require_allowed"),
    (EXPECTED_CORE[2], "EventSourcedStateMachine.transition_to"),
    (EXPECTED_CORE[2], "EventSourcedStateMachine._analyze_locked"),
    (EXPECTED_CORE[2], "EventSourcedStateMachine._recover_locked"),
    (EXPECTED_CORE[2], "EventSourcedStateMachine._handle_completed_transition"),
    (EXPECTED_CORE[3], "PathGuard.guard_read"),
    (EXPECTED_CORE[3], "PathGuard.guard_write"),
    (EXPECTED_CORE[3], "PathGuard._resolve_candidate"),
    (EXPECTED_CORE[4], "TrustEvaluationResult.require_root"),
    (EXPECTED_CORE[4], "TrustEvaluationResult.require_executable"),
    (EXPECTED_CORE[4], "TrustEvaluationResult.require_secret"),
    (EXPECTED_CORE[4], "TrustEvaluationResult.validate_hook"),
    (EXPECTED_CORE[4], "TrustEvaluationResult.require_promotion"),
    (EXPECTED_CORE[4], "TrustBoundaryEvaluator.evaluate"),
    (EXPECTED_CORE[5], "ToolRouter.require_trust_mode"),
    (EXPECTED_CORE[5], "ToolRouter._validate_compiled_capabilities"),
    (EXPECTED_CORE[5], "ToolRouter._require_enabled"),
    (EXPECTED_CORE[5], "ToolRouter._require_verified_decision"),
)


def test_manifest_freezes_core_threshold_and_every_decision_kernel() -> None:
    contract = COVERAGE_GATE.load_contract()

    assert contract.minimum_percent == 80.0
    assert contract.core_files == EXPECTED_CORE
    assert tuple(
        (decision.path, decision.qualname) for decision in contract.decision_functions
    ) == EXPECTED_DECISIONS
    assert len(contract.decision_functions) == 23


def _temporary_contract(tmp_path: Path) -> tuple[Path, Path, Path]:
    source = tmp_path / "src" / "ai_engineering_harness" / "decision.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        "def decide(value: bool) -> int:\n"
        "    if value:\n"
        "        return 1\n"
        "    return 0\n",
        encoding="utf-8",
    )
    relative = "src/ai_engineering_harness/decision.py"
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "task_id": "F7.3",
                "core_minimum_percent": 80.0,
                "core_files": [relative],
                "decision_functions": [{"path": relative, "qualname": "decide"}],
            }
        ),
        encoding="utf-8",
    )
    coverage = tmp_path / "coverage.json"
    return manifest, coverage, source


def _write_coverage(
    path: Path,
    *,
    missing_lines: int = 0,
    missing_branches: list[list[int]] | None = None,
) -> None:
    missing = missing_branches or []
    all_edges = [[2, 3], [2, 4]]
    executed = [edge for edge in all_edges if edge not in missing]
    path.write_text(
        json.dumps(
            {
                "files": {
                    "src\\ai_engineering_harness\\decision.py": {
                        "summary": {
                            "num_statements": 4,
                            "missing_lines": missing_lines,
                            "num_branches": 2,
                            "missing_branches": len(missing),
                        },
                        "executed_branches": executed,
                        "missing_branches": missing,
                    }
                }
            }
        ),
        encoding="utf-8",
    )


def test_coverage_gate_accepts_complete_decisions_and_normalizes_windows_paths(
    tmp_path: Path,
) -> None:
    manifest, coverage, _ = _temporary_contract(tmp_path)
    _write_coverage(coverage)

    result = COVERAGE_GATE.evaluate_coverage(
        coverage,
        manifest_path=manifest,
        root=tmp_path,
    )

    assert result.core_percent == 100.0
    assert result.measured_files == 1
    assert result.measured_functions == 1


def test_coverage_gate_fails_on_one_missing_decision_branch(tmp_path: Path) -> None:
    manifest, coverage, _ = _temporary_contract(tmp_path)
    _write_coverage(coverage, missing_branches=[[2, 4]])

    with pytest.raises(COVERAGE_GATE.CoverageGateError, match="below 100%"):
        COVERAGE_GATE.evaluate_coverage(
            coverage,
            manifest_path=manifest,
            root=tmp_path,
        )


def test_coverage_gate_fails_before_decisions_when_core_is_below_80(tmp_path: Path) -> None:
    manifest, coverage, _ = _temporary_contract(tmp_path)
    _write_coverage(coverage, missing_lines=2, missing_branches=[[2, 4]])

    with pytest.raises(COVERAGE_GATE.CoverageGateError, match="below 80.00%"):
        COVERAGE_GATE.evaluate_coverage(
            coverage,
            manifest_path=manifest,
            root=tmp_path,
        )


def test_manifest_rejects_threshold_relaxation_and_path_escape(tmp_path: Path) -> None:
    manifest, _, _ = _temporary_contract(tmp_path)
    document = json.loads(manifest.read_text(encoding="utf-8"))
    document["core_minimum_percent"] = 79.99
    manifest.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(COVERAGE_GATE.CoverageGateError, match="between 80 and 100"):
        COVERAGE_GATE.load_contract(manifest, root=tmp_path)

    document["core_minimum_percent"] = 80.0
    document["core_files"] = ["../outside.py"]
    manifest.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(COVERAGE_GATE.CoverageGateError, match="confined"):
        COVERAGE_GATE.load_contract(manifest, root=tmp_path)


def test_security_commands_are_argv_only_and_strict(tmp_path: Path) -> None:
    baseline = tmp_path / ".secrets.baseline"
    files = ("README.md", "src/package.py")

    assert SECURITY_GATE.build_secret_command(
        files,
        hook_executable="detect-secrets-hook",
        baseline_path=baseline,
    ) == [
        "detect-secrets-hook",
        "--baseline",
        baseline.name,
        *files,
    ]
    assert SECURITY_GATE.build_dependency_command(audit_executable="pip-audit") == [
        "pip-audit",
        "--local",
        "--skip-editable",
        "--progress-spinner",
        "off",
        "--format",
        "json",
    ]


def test_secret_scanner_environment_forces_utf8_without_dropping_existing_values() -> None:
    environment = SECURITY_GATE.build_utf8_environment(
        {"PYTHONUTF8": "0", "RETAINED_SETTING": "present"}
    )

    assert environment == {"PYTHONUTF8": "1", "RETAINED_SETTING": "present"}


def test_dependency_report_must_cover_environment_without_skips() -> None:
    report = {
        "dependencies": [
            {
                "name": "ai-engineering-harness",
                "skip_reason": "distribution marked as editable",
            },
            {"name": "example-dependency", "version": "1.2.3", "vulns": []},
        ],
        "fixes": [],
    }

    assert SECURITY_GATE.validate_dependency_report(
        report,
        installed={
            "ai-engineering-harness": "0.1.0",
            "example-dependency": "1.2.3",
        },
    ) == 1

    report["dependencies"][1] = {
        "name": "example-dependency",
        "skip_reason": "collection failed",
    }
    with pytest.raises(SECURITY_GATE.SecurityGateError, match="skipped locked dependency"):
        SECURITY_GATE.validate_dependency_report(
            report,
            installed={
                "ai-engineering-harness": "0.1.0",
                "example-dependency": "1.2.3",
            },
        )


def test_secret_baseline_requires_explicit_false_positive_review(tmp_path: Path) -> None:
    fixture = tmp_path / "tests" / "fixture.txt"
    fixture.parent.mkdir()
    fixture.write_text("deliberate test fixture", encoding="utf-8")
    baseline = tmp_path / ".secrets.baseline"
    document = {
        "version": "1.5.0",
        "plugins_used": [],
        "filters_used": [],
        "results": {
            "tests/fixture.txt": [
                {
                    "type": "Secret Keyword",
                    "hashed_secret": "digest",
                    "line_number": 1,
                    "is_secret": False,
                }
            ]
        },
    }
    baseline.write_text(json.dumps(document), encoding="utf-8")

    assert SECURITY_GATE.validate_reviewed_baseline(baseline, root=tmp_path) == 1

    del document["results"]["tests/fixture.txt"][0]["is_secret"]
    baseline.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(SECURITY_GATE.SecurityGateError, match="explicitly reviewed"):
        SECURITY_GATE.validate_reviewed_baseline(baseline, root=tmp_path)
