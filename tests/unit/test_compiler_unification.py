"""Integration tests for the single fail-closed F1.4 compiler pipeline."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml
from click.testing import CliRunner

from ai_engineering_harness.cli.main import main
from ai_engineering_harness.compiler import (
    GraphCompiler,
    GraphSourceError,
    GraphValidationError,
    GraphWriteError,
)
from ai_engineering_harness.contracts import CompiledGraphArtifact
from ai_engineering_harness.runtime.maf_adapter import ArtifactIntegrityError, MAFAdapter
from ai_engineering_harness.security import TrustAuthorization, TrustBoundaryEvaluator

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GRAPHS = REPOSITORY_ROOT / "src" / "ai_engineering_harness" / "defaults" / "graphs"


def _valid_graph(name: str = "sample") -> dict[str, Any]:
    return {
        "graph": {
            "name": name,
            "graph_schema_version": "1.0",
            "definition_version": "1.0.0",
            "entrypoint": "verify",
            "status": "stable",
        },
        "nodes": [
            {
                "id": "verify",
                "type": "deterministic",
                "executor": "deterministic_gate",
                "gate_name": "verified",
                "on_success": "completed",
                "on_failure": "failed",
            }
        ],
        "terminal_states": [
            {"id": "completed", "outcome": "success"},
            {"id": "failed", "outcome": "failure"},
        ],
        "policies": [],
        "contracts": [],
    }


def _write_graph(project_root: Path, document: dict[str, Any], name: str = "graph.yaml") -> Path:
    project_root.mkdir(parents=True, exist_ok=True)
    source = project_root / name
    source.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    return source


def test_canonical_compiler_emits_only_typed_artifact_after_validation(tmp_path: Path) -> None:
    source = _write_graph(tmp_path, _valid_graph())
    compiler = GraphCompiler(tmp_path)
    assert not compiler.output_dir.exists()

    output = compiler.compile_graph(source)

    assert output == tmp_path / ".harness" / "state" / "compiled" / "sample.json"
    artifact = CompiledGraphArtifact.model_validate_json(output.read_text(encoding="utf-8"))
    assert artifact.graph.graph.name == "sample"
    assert artifact.resolved_contracts == ()
    assert artifact.resolved_policies == ()
    assert set(json.loads(output.read_text(encoding="utf-8"))) == {
        "artifact_schema_version",
        "contract_digests",
        "graph_digest",
        "package_version",
        "policy_digest",
        "required_capabilities",
        "source_manifest",
        "graph",
        "resolved_contracts",
        "resolved_policies",
    }


def _python_contract_graph(reference: str) -> dict[str, Any]:
    document = _valid_graph("python-boundary")
    document["contracts"] = [reference]
    return document


def _write_import_sentinel_contract(project_root: Path, sentinel: Path) -> str:
    module_name = "f53_boundary_contract"
    (project_root / f"{module_name}.py").write_text(
        "from pathlib import Path\n"
        f"Path({str(sentinel)!r}).write_text('imported', encoding='utf-8')\n"
        "from pydantic import BaseModel\n"
        "class Payload(BaseModel):\n"
        "    value: str\n",
        encoding="utf-8",
    )
    return f"python:{module_name}:Payload"


def test_trusted_marker_never_imports_unapproved_project_python(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness_dir = tmp_path / ".harness"
    harness_dir.mkdir()
    (harness_dir / "trusted_repository").touch()
    sentinel = tmp_path / "imported.txt"
    reference = _write_import_sentinel_contract(tmp_path, sentinel)
    source = _write_graph(tmp_path, _python_contract_graph(reference))
    monkeypatch.syspath_prepend(str(tmp_path))
    sys.modules.pop("f53_boundary_contract", None)

    with pytest.raises(GraphValidationError):
        GraphCompiler(tmp_path).compile_graph(source)

    assert not sentinel.exists()


def test_exact_external_authorization_allows_one_project_python_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness_dir = tmp_path / ".harness"
    harness_dir.mkdir()
    (harness_dir / "trusted_repository").touch()
    sentinel = tmp_path / "imported.txt"
    reference = _write_import_sentinel_contract(tmp_path, sentinel)
    source = _write_graph(tmp_path, _python_contract_graph(reference))
    monkeypatch.syspath_prepend(str(tmp_path))
    sys.modules.pop("f53_boundary_contract", None)
    boundary = TrustBoundaryEvaluator(
        tmp_path,
        authorization=TrustAuthorization(
            repository_root=str(tmp_path.resolve()),
            python_contracts=(reference,),
        ),
    ).evaluate()

    output = GraphCompiler(tmp_path, trust_boundary=boundary).compile_graph(source)

    artifact = CompiledGraphArtifact.model_validate_json(output.read_text(encoding="utf-8"))
    assert sentinel.read_text(encoding="utf-8") == "imported"
    assert artifact.resolved_contracts[0].requested_reference == reference


def _remove_entrypoint(document: dict[str, Any]) -> None:
    del document["graph"]["entrypoint"]


def _remove_node_type(document: dict[str, Any]) -> None:
    del document["nodes"][0]["type"]


def _break_edge(document: dict[str, Any]) -> None:
    document["nodes"][0]["on_success"] = "missing"


def _remove_failure_terminal(document: dict[str, Any]) -> None:
    document["terminal_states"] = [{"id": "completed", "outcome": "success"}]


def _add_ungoverned_cycle(document: dict[str, Any]) -> None:
    document["nodes"][0]["on_failure"] = "verify"


@pytest.mark.parametrize(
    "mutation",
    [
        _remove_entrypoint,
        _remove_node_type,
        _break_edge,
        _remove_failure_terminal,
        _add_ungoverned_cycle,
    ],
)
def test_graphspec_failures_never_create_output(
    tmp_path: Path,
    mutation: Callable[[dict[str, Any]], None],
) -> None:
    document = _valid_graph()
    mutation(document)
    source = _write_graph(tmp_path, document)
    compiler = GraphCompiler(tmp_path)

    with pytest.raises(GraphValidationError):
        compiler.compile_graph(source)

    assert not compiler.output_dir.exists()


def _invalid_new_feature(case: str) -> dict[str, Any]:
    document = yaml.safe_load((DEFAULT_GRAPHS / "new-feature.yaml").read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    if case == "contract":
        document["nodes"][0]["input_contract"] = "contracts/missing.py#Payload"
    elif case == "policy":
        document["policies"][0] = "policies/missing.yaml"
    elif case == "role":
        document["nodes"][0]["role"] = "missing_role"
    elif case == "tool":
        document["nodes"][0]["tool_permissions"] = [
            {"tool": "missing_tool", "effect": "allow"}
        ]
    else:  # pragma: no cover - the parametrization is the closed set.
        raise AssertionError(case)
    return document


@pytest.mark.parametrize("case", ["contract", "policy", "role", "tool"])
def test_registry_failures_are_integrated_and_fail_before_output(tmp_path: Path, case: str) -> None:
    project_root = tmp_path / case
    source = _write_graph(project_root, _invalid_new_feature(case))
    compiler = GraphCompiler(project_root)

    with pytest.raises(GraphValidationError):
        compiler.compile_graph(source, "new-feature")

    assert not compiler.output_dir.exists()


def test_harness_init_defaults_all_compile_with_project_overrides(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    initialized = runner.invoke(main, ["init"])
    assert initialized.exit_code == 0, initialized.output

    compiler = GraphCompiler(tmp_path)
    graph_names = ["bug-fix", "incident", "migration", "new-feature", "refactoring"]
    for graph_name in graph_names:
        source = tmp_path / ".harness" / "graphs" / "specs" / f"{graph_name}.yaml"
        output = compiler.compile_graph(source, graph_name)
        artifact = MAFAdapter.load_and_validate(output)
        assert artifact.graph.graph.name == graph_name
        assert artifact.resolved_policies
        assert artifact.artifact_schema_version == "2.0"
        assert artifact.source_manifest

    assert sorted(path.stem for path in compiler.output_dir.glob("*.json")) == graph_names
    assert not (tmp_path / "graphs").exists()


def test_invalid_project_policy_override_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    assert runner.invoke(main, ["init"]).exit_code == 0
    policy_path = tmp_path / ".harness" / "policies" / "verification_policy.yaml"
    document = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
    document["unknown_key"] = True
    policy_path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    compiler = GraphCompiler(tmp_path)
    before = tuple(compiler.output_dir.iterdir())

    with pytest.raises(GraphValidationError):
        compiler.compile_graph(
            tmp_path / ".harness" / "graphs" / "specs" / "new-feature.yaml"
        )

    assert tuple(compiler.output_dir.iterdir()) == before == ()


def test_cli_and_root_wrapper_produce_identical_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cli_project = tmp_path / "cli"
    wrapper_project = tmp_path / "wrapper"
    _write_graph(cli_project, _valid_graph("identical"))
    _write_graph(wrapper_project, _valid_graph("identical"))

    monkeypatch.chdir(cli_project)
    cli_result = CliRunner().invoke(main, ["compile", "graph.yaml", "--workflow", "identical"])
    assert cli_result.exit_code == 0, cli_result.output

    wrapper_result = subprocess.run(
        [sys.executable, str(REPOSITORY_ROOT / "compiler" / "compile.py"), "--graph", "graph.yaml"],
        cwd=wrapper_project,
        text=True,
        capture_output=True,
        check=False,
        shell=False,
    )
    assert wrapper_result.returncode == 0, wrapper_result.stderr
    cli_bytes = (cli_project / ".harness" / "state" / "compiled" / "identical.json").read_bytes()
    wrapper_bytes = (
        wrapper_project / ".harness" / "state" / "compiled" / "identical.json"
    ).read_bytes()
    assert cli_bytes == wrapper_bytes


def test_missing_workflow_fails_before_any_execution_side_effect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(main, ["run", "definitely-missing"])

    assert result.exit_code != 0
    assert "definitely-missing" in result.output
    assert ".harness/graphs/specs/definitely-missing.yaml" in result.output
    assert not (tmp_path / ".harness").exists()


def test_cli_compile_invalid_graph_returns_nonzero_without_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_graph(tmp_path, {"nodes": []})
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(main, ["compile", "graph.yaml"])

    assert result.exit_code != 0
    assert "invalid graph specification" in result.output
    assert not (tmp_path / ".harness").exists()


def test_source_boundary_rejects_external_absolute_traversal_and_extension(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    outside = _write_graph(tmp_path / "outside", _valid_graph())
    wrong_extension = _write_graph(project_root, _valid_graph(), "graph.yml")
    compiler = GraphCompiler(project_root)

    for source in (outside, Path("../outside/graph.yaml"), wrong_extension):
        with pytest.raises(GraphSourceError):
            compiler.compile_graph(source)
    assert not compiler.output_dir.exists()


def test_resolved_symlink_escape_is_rejected_without_platform_symlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    source = _write_graph(project_root, _valid_graph(), "linked.yaml")
    outside = _write_graph(tmp_path / "outside", _valid_graph())
    compiler = GraphCompiler(project_root)
    original_resolve = Path.resolve
    source_resolved = original_resolve(source)
    outside_resolved = original_resolve(outside)

    def redirect_link(path: Path, *args: object, **kwargs: object) -> Path:
        resolved = original_resolve(path, *args, **kwargs)
        return outside_resolved if resolved == source_resolved else resolved

    monkeypatch.setattr(Path, "resolve", redirect_link)
    with pytest.raises(GraphSourceError, match="escapes project root"):
        compiler.compile_graph(source)


@pytest.mark.parametrize("workflow_name", ["different", "../escape", "with/slash"])
def test_workflow_override_must_be_safe_and_match_graph(
    tmp_path: Path,
    workflow_name: str,
) -> None:
    source = _write_graph(tmp_path, _valid_graph("expected"))
    compiler = GraphCompiler(tmp_path)

    with pytest.raises(GraphValidationError):
        compiler.compile_graph(source, workflow_name)
    assert not compiler.output_dir.exists()


def test_unsafe_graph_name_cannot_become_output_path(tmp_path: Path) -> None:
    source = _write_graph(tmp_path, _valid_graph("../escape"))
    compiler = GraphCompiler(tmp_path)

    with pytest.raises(GraphValidationError):
        compiler.compile_graph(source)
    assert not compiler.output_dir.exists()


def test_write_failure_is_typed_after_successful_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _write_graph(tmp_path, _valid_graph())
    compiler = GraphCompiler(tmp_path)
    output = compiler.compile_graph(source)
    previous = output.read_bytes()
    document = _valid_graph()
    document["graph"]["definition_version"] = "2.0.0"
    source.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")

    def fail_artifact_replace(source_path: object, target_path: object) -> None:
        del source_path, target_path
        raise OSError("controlled replace failure")

    monkeypatch.setattr(os, "replace", fail_artifact_replace)
    with pytest.raises(GraphWriteError, match="controlled replace failure"):
        compiler.compile_graph(source)
    assert output.read_bytes() == previous
    assert not tuple(compiler.output_dir.glob("*.tmp"))


def test_output_directory_symlink_escape_is_rejected_before_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    source = _write_graph(project_root, _valid_graph())
    harness_directory = project_root / ".harness"
    harness_directory.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    compiler = GraphCompiler(project_root)
    original_resolve = Path.resolve
    harness_resolved = original_resolve(harness_directory)
    outside_resolved = original_resolve(outside)

    def redirect_link(path: Path, *args: object, **kwargs: object) -> Path:
        resolved = original_resolve(path, *args, **kwargs)
        return outside_resolved if resolved == harness_resolved else resolved

    monkeypatch.setattr(Path, "resolve", redirect_link)
    with pytest.raises(GraphWriteError, match="escapes project root"):
        compiler.compile_graph(source)
    assert tuple(outside.iterdir()) == ()


def test_maf_adapter_returns_typed_artifact_and_rejects_tampering(tmp_path: Path) -> None:
    source = _write_graph(tmp_path, _valid_graph())
    output = GraphCompiler(tmp_path).compile_graph(source)

    artifact = MAFAdapter.load_and_validate(output)
    assert isinstance(artifact, CompiledGraphArtifact)

    tampered = json.loads(output.read_text(encoding="utf-8"))
    del tampered["package_version"]
    output.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(ArtifactIntegrityError):
        MAFAdapter.load_and_validate(output)


def test_legacy_wrapper_contains_no_second_compiler_or_gate_injector() -> None:
    package_source = (
        REPOSITORY_ROOT / "src" / "ai_engineering_harness" / "compiler" / "compiler.py"
    ).read_text(encoding="utf-8")
    wrapper_source = (REPOSITORY_ROOT / "compiler" / "compile.py").read_text(encoding="utf-8")

    assert package_source.count("class GraphCompiler:") == 1
    assert package_source.count("def compile_graph(") == 1
    assert "def compile_graph(" not in wrapper_source
    assert "yaml" not in wrapper_source
    assert "GateInjector" not in wrapper_source
    assert not (REPOSITORY_ROOT / "compiler" / "validators" / "gate_injector.py").exists()
