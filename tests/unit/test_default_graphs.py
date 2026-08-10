"""F4.3 policy declarations for every supported packaged workflow."""

from pathlib import Path

import pytest
import yaml

from ai_engineering_harness.compiler import GraphCompiler
from ai_engineering_harness.runtime.maf_adapter import MAFAdapter

ROOT = Path(__file__).resolve().parents[2]
GRAPH_ROOT = ROOT / "src" / "ai_engineering_harness" / "defaults" / "graphs"
CONTEXT_POLICY = "policies/context_sufficiency.yaml"


@pytest.mark.parametrize("workflow", ["new-feature", "bug-fix", "refactoring", "migration"])
def test_supported_default_graphs_compile_with_context_policy(
    tmp_path: Path,
    workflow: str,
) -> None:
    source = GRAPH_ROOT / f"{workflow}.yaml"
    document = yaml.safe_load(source.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    assert CONTEXT_POLICY in document["policies"]
    source_copy = tmp_path / source.name
    source_copy.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

    artifact_path = GraphCompiler(tmp_path).compile_graph(source_copy, workflow)
    artifact = MAFAdapter.load_and_validate(artifact_path)
    resolved = tuple(
        policy
        for policy in artifact.resolved_policies
        if policy.requested_reference == CONTEXT_POLICY
    )

    assert len(resolved) == 1
    assert resolved[0].policy_id == "context-sufficiency-v1"


def test_incident_default_remains_outside_context_sufficiency_mvp() -> None:
    document = yaml.safe_load((GRAPH_ROOT / "incident.yaml").read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    assert CONTEXT_POLICY not in document["policies"]
