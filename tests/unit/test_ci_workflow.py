"""Contrato local do workflow obrigatório de CI."""

import re
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
EXPECTED_ACTIONS = {
    "actions/checkout": "de0fac2e4500dabe0009e67214ff5f5447ce83dd",
    "actions/setup-python": "a309ff8b426b58ec0e2a45f0f869d46889d02405",
    "astral-sh/setup-uv": "08807647e7069bb48b6ef5acd8ec9567f424441b",
}


def _workflow() -> tuple[str, dict[str, Any]]:
    text = WORKFLOW.read_text(encoding="utf-8", errors="strict")
    parsed = yaml.load(text, Loader=yaml.BaseLoader)
    assert isinstance(parsed, dict)
    return text, parsed


def test_ci_triggers_permissions_and_concurrency_are_frozen() -> None:
    _, workflow = _workflow()

    assert set(workflow["on"]) == {"push", "pull_request", "merge_group", "workflow_dispatch"}
    assert workflow["on"]["push"]["branches"] == ["main", "phase/**"]
    assert workflow["on"]["pull_request"]["branches"] == ["main"]
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["concurrency"]["cancel-in-progress"] == "true"


def test_ci_actions_are_pinned_to_reviewed_commits() -> None:
    text, _ = _workflow()
    observed = dict(re.findall(r"uses:\s+([^@\s]+)@([0-9a-f]{40})", text))

    assert observed == EXPECTED_ACTIONS
    assert re.search(r"uses:\s+[^\s]+@(?:main|master|v\d+)\b", text) is None
    assert text.count("persist-credentials: false") == 4


def test_ci_matrices_cover_supported_boundaries_on_windows_and_linux() -> None:
    _, workflow = _workflow()
    jobs = workflow["jobs"]

    for job_name in ("quality", "tests"):
        matrix = jobs[job_name]["strategy"]["matrix"]
        assert matrix["os"] == ["ubuntu-latest", "windows-latest"]
        assert matrix["python-version"] == ["3.11", "3.14"]
        assert jobs[job_name]["strategy"]["fail-fast"] == "false"

    package_matrix = jobs["package"]["strategy"]["matrix"]
    assert package_matrix["os"] == ["ubuntu-latest", "windows-latest"]
    assert jobs["package"]["env"]["UV_PYTHON"] == "3.12"

    security_coverage = jobs["security-coverage"]
    assert security_coverage["runs-on"] == "ubuntu-latest"
    assert security_coverage["env"]["UV_PYTHON"] == "3.12"


def test_ci_contains_all_required_gates_and_fail_closed_aggregate() -> None:
    text, workflow = _workflow()
    required_commands = (
        "uv lock --check",
        "uv sync --all-extras --locked",
        "tests/unit/test_encoding.py",
        "python -m compileall -q src compiler tests",
        "python -m ruff check .",
        "python -m mypy --strict src",
        "python -m pytest tests/unit -q",
        "python -m pytest tests/e2e -q",
        "python -m build",
        "python tests/ci/smoke_wheel.py",
        "--cov=ai_engineering_harness --cov-branch --cov-report=json:coverage.json",
        "python tests/ci/check_f7_3_coverage.py coverage.json",
        "python tests/ci/check_f7_3_security.py secrets",
        "python tests/ci/check_f7_3_security.py dependencies",
    )

    for command in required_commands:
        assert command in text

    aggregate = workflow["jobs"]["ci-required"]
    assert aggregate["name"] == "CI required"
    assert aggregate["if"] == "${{ always() }}"
    assert aggregate["needs"] == ["quality", "tests", "package", "security-coverage"]
    assert text.count('!= "success"') == 4
