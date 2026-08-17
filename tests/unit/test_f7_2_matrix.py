"""Contract tests for the canonical F7.2 executable matrix."""

from __future__ import annotations

import copy
import subprocess
import sys
from pathlib import Path
from typing import cast

import pytest

from tests import run_f7_2_matrix as matrix_runner


def _requirements(matrix: dict[str, object], layer_index: int) -> dict[str, list[str]]:
    layers = cast(list[dict[str, object]], matrix["layers"])
    return cast(dict[str, list[str]], layers[layer_index]["requirements"])


def test_canonical_matrix_has_all_plan_layers_requirements_and_unique_real_nodes() -> None:
    matrix = matrix_runner.load_matrix()

    node_ids = matrix_runner.validate_matrix(matrix)

    assert matrix_runner.matrix_counts(matrix) == (12, 42)
    assert len(node_ids) == 46
    assert len(set(node_ids)) == 46
    assert tuple(layer for layer, _requirements in matrix_runner.EXPECTED_REQUIREMENTS) == (
        "contracts",
        "compiler",
        "runtime",
        "persistence",
        "models",
        "tools",
        "git",
        "verification",
        "security",
        "observability",
        "e2e",
        "recovery",
    )
    assert all(node_id.startswith(("tests/unit/", "tests/e2e/")) for node_id in node_ids)
    assert all((matrix_runner.ROOT / node_id.split("::", maxsplit=1)[0]).is_file() for node_id in node_ids)


def test_recovery_requirement_covers_five_distinct_write_ahead_checkpoints() -> None:
    matrix = matrix_runner.load_matrix()

    recovery_nodes = _requirements(matrix, 11)["crash_injection_critical_checkpoints"]

    assert len(recovery_nodes) == 5
    assert any("event_sourced_execution" in node_id for node_id in recovery_nodes)
    assert any("graph_executor" in node_id for node_id in recovery_nodes)
    assert any("verification_lifecycle" in node_id for node_id in recovery_nodes)
    assert any("safe_promotion" in node_id for node_id in recovery_nodes)
    assert any("knowledge_transaction" in node_id for node_id in recovery_nodes)


@pytest.mark.parametrize(
    ("mutation", "match"),
    (
        ("unknown_root_key", "matrix keys"),
        ("unknown_requirement", "requirements keys"),
        ("duplicate_node", "duplicate pytest node ID"),
        ("external_path", "relative Python file"),
        ("path_traversal", "without traversal"),
        ("missing_file", "file does not exist"),
        ("missing_function", "function does not exist"),
    ),
)
def test_matrix_fails_closed_for_schema_and_reference_mutations(mutation: str, match: str) -> None:
    matrix = copy.deepcopy(matrix_runner.load_matrix())
    first_requirements = _requirements(matrix, 0)
    if mutation == "unknown_root_key":
        matrix["unexpected"] = True
    elif mutation == "unknown_requirement":
        first_requirements["unexpected"] = first_requirements.pop("serialization")
    elif mutation == "duplicate_node":
        _requirements(matrix, 11)["crash_injection_critical_checkpoints"][-1] = first_requirements["validation"][0]
    elif mutation == "external_path":
        first_requirements["validation"][0] = "README.md::test_not_allowed"
    elif mutation == "path_traversal":
        first_requirements["validation"][0] = "tests/unit/../unit/test_graph_contracts.py::test_missing_entrypoint_is_rejected"
    elif mutation == "missing_file":
        first_requirements["validation"][0] = "tests/unit/test_missing.py::test_missing"
    else:
        first_requirements["validation"][0] = "tests/unit/test_graph_contracts.py::test_missing_symbol"

    with pytest.raises(matrix_runner.MatrixValidationError, match=match):
        matrix_runner.validate_matrix(matrix)


def test_loader_rejects_duplicate_json_keys(tmp_path: Path) -> None:
    matrix_path = tmp_path / "duplicate.json"
    matrix_path.write_text('{"schema_version":"1.0","schema_version":"2.0"}', encoding="utf-8")

    with pytest.raises(matrix_runner.MatrixValidationError, match="duplicate JSON key"):
        matrix_runner.load_matrix(matrix_path)


def test_runner_uses_active_python_argv_fixed_root_and_shell_false(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    matrix = matrix_runner.load_matrix()
    node_ids = matrix_runner.validate_matrix(matrix)
    observed: dict[str, object] = {}

    def fake_run(
        command: list[str], *, cwd: Path, check: bool, shell: bool
    ) -> subprocess.CompletedProcess[str]:
        observed.update(command=command, cwd=cwd, check=check, shell=shell)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(matrix_runner, "load_matrix", lambda: matrix)
    monkeypatch.setattr(matrix_runner.subprocess, "run", fake_run)
    monkeypatch.setenv("HARNESS_F7_2_TEMP_PARENT", str(tmp_path))

    assert matrix_runner.main(["--collect-only"]) == 0
    command = cast(list[str], observed["command"])
    assert command[:7] == [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"]
    assert command[7] == "--basetemp"
    assert Path(command[8]).parent == tmp_path
    assert command[9:] == list(node_ids)
    assert observed["cwd"] == matrix_runner.ROOT
    assert observed["check"] is False
    assert observed["shell"] is False
    assert "F7.2 matrix: 12 layers, 42 requirements, 46 unique pytest nodes" in capsys.readouterr().out


def test_runner_does_not_spawn_pytest_when_validation_fails(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    matrix = matrix_runner.load_matrix()
    _requirements(matrix, 0)["validation"][0] = "tests/unit/test_missing.py::test_missing"
    monkeypatch.setattr(matrix_runner, "load_matrix", lambda: matrix)

    def unexpected_run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        pytest.fail("pytest subprocess must not start for an invalid matrix")

    monkeypatch.setattr(matrix_runner.subprocess, "run", unexpected_run)

    assert matrix_runner.main([]) == 2
    assert "F7.2 matrix error:" in capsys.readouterr().err
