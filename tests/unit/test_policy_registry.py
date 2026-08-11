"""Behavior, schema, and security tests for the F1.3 policy registry."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

import ai_engineering_harness.contracts as public_contracts
from ai_engineering_harness.contracts import (
    CANONICAL_VERIFICATION_GATE_IDS,
    CompiledGraphArtifact,
    ContractRegistry,
    GraphSpec,
    InvalidPolicyReferenceError,
    InvalidPolicySchemaError,
    PolicyNotFoundError,
    PolicyRegistry,
    PolicyRegistryError,
    ResolvedPolicySpec,
    RoleNotFoundError,
    SourceManifestEntry,
    ToolNotFoundError,
    UnauthorizedToolError,
)
from ai_engineering_harness.versioning import ARTIFACT_SCHEMA_VERSION, GRAPH_SCHEMA_VERSION, PACKAGE_VERSION

ROOT = Path(__file__).resolve().parents[2]
DEFAULTS = ROOT / "src" / "ai_engineering_harness" / "defaults"
POLICY_REFERENCES = (
    "policies/context_sufficiency.yaml",
    "policies/incident_graph.yaml",
    "policies/knowledge_sync.yaml",
    "policies/production_health.yaml",
    "policies/retry_cost_policy.yaml",
    "policies/sandbox_policy.yaml",
    "policies/tool_policy.yaml",
    "policies/verification_policy.yaml",
)
PUBLIC_POLICY_SYMBOLS = {
    "AgentRoleSpec",
    "EffectiveNodeToolPolicySpec",
    "InvalidPolicyReferenceError",
    "InvalidPolicySchemaError",
    "PolicyNotFoundError",
    "PolicyRegistry",
    "PolicyRegistryError",
    "ResolvedPolicySpec",
    "RoleNotFoundError",
    "ToolCapabilitySpec",
    "ToolGovernancePolicySpec",
    "ToolNotFoundError",
    "ToolRegistrySpec",
    "UnauthorizedToolError",
}


def _load_yaml(relative: str) -> dict[str, Any]:
    loaded = yaml.safe_load((DEFAULTS / relative).read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _valid_graph_data() -> dict[str, Any]:
    return {
        "graph": {
            "name": "policy-fixture",
            "graph_schema_version": GRAPH_SCHEMA_VERSION,
            "definition_version": "3.2.0",
            "entrypoint": "analyze",
            "status": "stable",
        },
        "policies": ["policies/tool_policy.yaml", "policies/verification_policy.yaml"],
        "nodes": [
            {
                "id": "analyze",
                "type": "agent",
                "role": "requirement_analyst",
                "input_contract": "RetrievalRequest",
                "output_contract": "ContextSufficiencyReport",
                "tool_permissions": [{"tool": "knowledge_retriever", "effect": "allow"}],
                "on_success": "verify",
                "on_failure": "failed",
            },
            {
                "id": "verify",
                "type": "deterministic",
                "executor": "deterministic_policy",
                "policy_ref": "policies/verification_policy.yaml",
                "on_success": "completed",
                "on_failure": "failed",
            },
        ],
        "terminal_states": [
            {"id": "completed", "outcome": "success"},
            {"id": "failed", "outcome": "failure"},
        ],
    }


def _valid_graph() -> GraphSpec:
    return GraphSpec.model_validate(_valid_graph_data())


def _tool_effective(resolved: tuple[ResolvedPolicySpec, ...]) -> dict[str, Any]:
    return next(
        policy.effective_policy
        for policy in resolved
        if policy.requested_reference == "policies/tool_policy.yaml"
    )


def test_public_policy_api_and_catalog_cardinality_are_frozen() -> None:
    assert PUBLIC_POLICY_SYMBOLS <= set(public_contracts.__all__)
    assert issubclass(PolicyNotFoundError, PolicyRegistryError)
    registry = PolicyRegistry()

    assert registry.available_policies == POLICY_REFERENCES
    assert registry.available_roles == (
        "architecture_analyst",
        "code_agent",
        "knowledge_updater",
        "production_operator",
        "requirement_analyst",
        "security_agent",
        "test_agent",
    )
    assert len(registry.available_tools) == 18
    assert {"git_tool", "terminal_tool", "serena_mcp", "terminal_executor"} <= set(
        registry.available_tools
    )


def test_all_packaged_policies_resolve_to_normalized_views() -> None:
    resolved = PolicyRegistry().resolve_many(POLICY_REFERENCES)

    assert len(resolved) == 8
    assert [policy.requested_reference for policy in resolved] == list(POLICY_REFERENCES)
    assert all(policy.policy_schema_version == "1.0" for policy in resolved)
    assert all("policy_id" not in policy.effective_policy for policy in resolved)
    assert all("definition_version" not in policy.effective_policy for policy in resolved)


def test_default_verification_policy_uses_only_canonical_gate_ids() -> None:
    policy = PolicyRegistry().resolve("policies/verification_policy.yaml")
    gate_ids = tuple(gate["id"] for gate in policy.effective_policy["required_gates"])

    assert gate_ids == ("typecheck", "lint", "unit_test", "build")
    assert set(gate_ids) < set(CANONICAL_VERIFICATION_GATE_IDS)
    assert "tests" not in gate_ids


@pytest.mark.parametrize(
    ("required_gates", "match"),
    [
        ([], "at least one gate"),
        (
            [
                {
                    "id": "unknown",
                    "executor": "deterministic",
                    "command": "unknown",
                    "blocking": True,
                }
            ],
            "Input should be",
        ),
        (
            [
                {
                    "id": "lint",
                    "executor": "deterministic",
                    "command": "ruff check .",
                    "blocking": True,
                },
                {
                    "id": "lint",
                    "executor": "deterministic",
                    "command": "ruff check .",
                    "blocking": True,
                },
            ],
            "unique canonical ids",
        ),
        (
            [
                {
                    "id": "security_scan",
                    "executor": "deterministic",
                    "command": "configured later",
                    "blocking": False,
                }
            ],
            "at least one blocking gate",
        ),
    ],
)
def test_verification_policy_gate_contract_fails_closed(
    required_gates: list[dict[str, object]],
    match: str,
) -> None:
    document = _load_yaml("policies/verification_policy.yaml")
    document["required_gates"] = required_gates

    with pytest.raises(InvalidPolicySchemaError, match=match):
        PolicyRegistry(policy_documents={"policies/verification_policy.yaml": document})


@pytest.mark.parametrize("reference", POLICY_REFERENCES)
def test_every_packaged_policy_rejects_unknown_top_level_key(reference: str) -> None:
    document = _load_yaml(reference)
    document["unknown_key"] = True

    with pytest.raises(InvalidPolicySchemaError, match="Extra inputs are not permitted"):
        PolicyRegistry(policy_documents={reference: document})


def test_tool_authorization_objects_are_recursively_strict() -> None:
    document = _load_yaml("policies/tool_policy.yaml")
    document["roles_permissions"]["code_agent"]["implicit_allow"] = True

    with pytest.raises(InvalidPolicySchemaError, match="Extra inputs are not permitted"):
        PolicyRegistry(policy_documents={"policies/tool_policy.yaml": document})


def test_role_and_tool_catalog_documents_are_strict() -> None:
    role = _load_yaml("agents/code_agent/agent.yaml")
    role["unknown_key"] = True
    with pytest.raises(InvalidPolicySchemaError, match="Extra inputs are not permitted"):
        PolicyRegistry(role_documents={"code_agent": role})

    tool_registry = _load_yaml("tools/tool_registry.yaml")
    tool_registry["tools"][0]["runtime_available"] = True
    with pytest.raises(InvalidPolicySchemaError, match="Extra inputs are not permitted"):
        PolicyRegistry(tool_registry_document=tool_registry)


@pytest.mark.parametrize(
    "reference",
    [
        "",
        " policies/tool_policy.yaml",
        "../policies/tool_policy.yaml",
        "policies\\tool_policy.yaml",
        "C:/policies/tool_policy.yaml",
        "/policies/tool_policy.yaml",
        "policies/tool_policy.json",
    ],
)
def test_unsafe_or_malformed_policy_reference_fails(reference: str) -> None:
    with pytest.raises((InvalidPolicyReferenceError, PolicyNotFoundError)):
        PolicyRegistry().resolve(reference)


def test_unregistered_well_formed_policy_fails_closed() -> None:
    with pytest.raises(PolicyNotFoundError, match="not registered"):
        PolicyRegistry().resolve("policies/missing.yaml")


def test_duplicate_policy_reference_is_rejected() -> None:
    with pytest.raises(InvalidPolicyReferenceError, match="duplicate"):
        PolicyRegistry().resolve_many(
            ["policies/tool_policy.yaml", "policies/tool_policy.yaml"]
        )


def test_all_default_graphs_resolve_without_compiler_fallback() -> None:
    registry = PolicyRegistry()
    graph_paths = sorted((DEFAULTS / "graphs").glob("*.yaml"))

    for graph_path in graph_paths:
        graph = yaml.safe_load(graph_path.read_text(encoding="utf-8"))
        resolved = registry.resolve_legacy_graph(graph)
        assert resolved
        if any("role" in node for node in graph["nodes"]):
            tool_policy = _tool_effective(resolved)
            decisions = [
                node
                for role in tool_policy["roles"].values()
                for node in role["nodes"]
            ]
            assert all(node["allowed_tools"] == [] for node in decisions)


def test_valid_allow_is_in_effective_default_deny_view() -> None:
    resolved = PolicyRegistry().resolve_graph(_valid_graph())
    tool_policy = _tool_effective(resolved)
    node = tool_policy["roles"]["requirement_analyst"]["nodes"][0]

    assert node["node_id"] == "analyze"
    assert node["allowed_tools"] == ["knowledge_retriever"]
    assert {"file_writer", "git_committer", "terminal_executor"} <= set(node["denied_tools"])


def test_explicit_deny_wins_and_default_allow_stays_empty() -> None:
    data = _valid_graph_data()
    data["nodes"][0]["tool_permissions"] = [
        {"tool": "knowledge_retriever", "effect": "deny"}
    ]
    resolved = PolicyRegistry().resolve_graph(GraphSpec.model_validate(data))
    node = _tool_effective(resolved)["roles"]["requirement_analyst"]["nodes"][0]

    assert node["allowed_tools"] == []
    assert "knowledge_retriever" in node["denied_tools"]


@pytest.mark.parametrize("tool", ["file_writer", "test_runner"])
def test_node_cannot_expand_role_or_policy(tool: str) -> None:
    data = _valid_graph_data()
    data["nodes"][0]["tool_permissions"] = [{"tool": tool, "effect": "allow"}]

    with pytest.raises(UnauthorizedToolError, match="not authorized"):
        PolicyRegistry().resolve_graph(GraphSpec.model_validate(data))


def test_unknown_tool_and_role_fail_with_typed_errors() -> None:
    data = _valid_graph_data()
    data["nodes"][0]["tool_permissions"] = [{"tool": "missing_tool", "effect": "allow"}]
    with pytest.raises(ToolNotFoundError, match="missing_tool"):
        PolicyRegistry().resolve_graph(GraphSpec.model_validate(data))

    data = _valid_graph_data()
    data["nodes"][0]["role"] = "missing_role"
    with pytest.raises(RoleNotFoundError, match="missing_role"):
        PolicyRegistry().resolve_graph(GraphSpec.model_validate(data))


def test_repeated_or_conflicting_node_tool_declaration_fails() -> None:
    data = _valid_graph_data()
    data["nodes"][0]["tool_permissions"] = [
        {"tool": "knowledge_retriever", "effect": "allow"},
        {"tool": "knowledge_retriever", "effect": "deny"},
    ]

    with pytest.raises(UnauthorizedToolError, match="repeats or conflicts"):
        PolicyRegistry().resolve_graph(GraphSpec.model_validate(data))


def test_agent_graph_requires_tool_policy_and_node_policy_ref_must_be_declared() -> None:
    data = _valid_graph_data()
    data["policies"] = ["policies/verification_policy.yaml"]
    with pytest.raises(PolicyNotFoundError, match="tool_policy"):
        PolicyRegistry().resolve_graph(GraphSpec.model_validate(data))

    data = _valid_graph_data()
    data["policies"] = ["policies/tool_policy.yaml"]
    with pytest.raises(InvalidPolicyReferenceError, match="not declared"):
        PolicyRegistry().resolve_graph(GraphSpec.model_validate(data))


def test_catalog_rejects_unknown_tool_and_role_policy_drift() -> None:
    tool_registry = _load_yaml("tools/tool_registry.yaml")
    tool_registry["tools"] = [
        tool for tool in tool_registry["tools"] if tool["id"] != "knowledge_retriever"
    ]
    with pytest.raises(ToolNotFoundError, match="knowledge_retriever"):
        PolicyRegistry(tool_registry_document=tool_registry)

    tool_policy = _load_yaml("policies/tool_policy.yaml")
    del tool_policy["roles_permissions"]["knowledge_updater"]
    with pytest.raises(RoleNotFoundError, match="knowledge_updater"):
        PolicyRegistry(policy_documents={"policies/tool_policy.yaml": tool_policy})

    tool_policy = _load_yaml("policies/tool_policy.yaml")
    tool_policy["roles_permissions"]["requirement_analyst"]["allowed_tools"].append("test_runner")
    with pytest.raises(UnauthorizedToolError, match="exceeds agent"):
        PolicyRegistry(policy_documents={"policies/tool_policy.yaml": tool_policy})


def test_effective_policy_is_detached_from_subsequent_mutation() -> None:
    registry = PolicyRegistry()
    first = registry.resolve("policies/verification_policy.yaml")
    first.effective_policy["required_gates"] = []

    second = registry.resolve("policies/verification_policy.yaml")
    assert second.effective_policy["required_gates"]
    assert str(ROOT.resolve()) not in json.dumps(second.effective_policy)


def test_compiled_artifact_round_trip_preserves_additive_policy_view() -> None:
    contract_reference = "ai_engineering_harness.contracts.nodes.context_sufficiency.RetrievalRequest"
    graph_data = _valid_graph_data()
    graph_data["nodes"][0]["input_contract"] = contract_reference
    graph_data["nodes"][0]["output_contract"] = contract_reference
    graph = GraphSpec.model_validate(graph_data)
    artifact = CompiledGraphArtifact.build(
        graph=graph,
        resolved_contracts=ContractRegistry().resolve_many([contract_reference]),
        resolved_policies=PolicyRegistry().resolve_graph(graph),
        source_manifest=(
            SourceManifestEntry(
                source_kind="graph",
                source_id="project://graph.yaml",
                content_digest="sha256:" + "0" * 64,
            ),
        ),
    )

    restored = CompiledGraphArtifact.model_validate_json(artifact.canonical_json())

    assert restored == artifact
    assert restored.artifact_schema_version == ARTIFACT_SCHEMA_VERSION
    assert restored.package_version == PACKAGE_VERSION
    assert restored.resolved_contracts[0].digest.startswith("sha256:")
    assert isinstance(restored.resolved_policies, tuple)
    assert restored.resolved_policies[0].requested_reference == "policies/tool_policy.yaml"


def test_compiled_artifact_rejects_legacy_envelope_and_duplicate_views() -> None:
    with pytest.raises(ValidationError, match="Field required"):
        CompiledGraphArtifact.model_validate(
            {
                "artifact_schema_version": ARTIFACT_SCHEMA_VERSION,
                "package_version": PACKAGE_VERSION,
                "graph": _valid_graph().model_dump(mode="json"),
            }
        )

    contract_reference = "ai_engineering_harness.contracts.nodes.context_sufficiency.RetrievalRequest"
    graph_data = _valid_graph_data()
    graph_data["nodes"][0]["input_contract"] = contract_reference
    graph_data["nodes"][0]["output_contract"] = contract_reference
    graph = GraphSpec.model_validate(graph_data)
    artifact = CompiledGraphArtifact.build(
        graph=graph,
        resolved_contracts=ContractRegistry().resolve_many([contract_reference]),
        resolved_policies=PolicyRegistry().resolve_graph(graph),
        source_manifest=(
            SourceManifestEntry(
                source_kind="graph",
                source_id="project://graph.yaml",
                content_digest="sha256:" + "0" * 64,
            ),
        ),
    )
    duplicate = artifact.model_dump(mode="json")
    duplicate["resolved_policies"].append(duplicate["resolved_policies"][-1])
    with pytest.raises(ValidationError, match="must be unique"):
        CompiledGraphArtifact.model_validate(duplicate)
