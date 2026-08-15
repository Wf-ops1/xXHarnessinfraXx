"""Security and behavior tests for the F1.2 contract registry."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

import ai_engineering_harness.contracts as public_contracts
from ai_engineering_harness.contracts import (
    CompiledGraphArtifact,
    ContractCompatibilityError,
    ContractNotFoundError,
    ContractRegistry,
    ContractRegistryError,
    GraphSpec,
    InvalidContractReferenceError,
    InvalidContractSchemaError,
    ResolvedContractSpec,
    SourceManifestEntry,
    UntrustedPythonContractError,
)
from ai_engineering_harness.contracts.nodes.context_sufficiency import RetrievalRequest
from ai_engineering_harness.versioning import ARTIFACT_SCHEMA_VERSION, GRAPH_SCHEMA_VERSION, PACKAGE_VERSION
from compiler.validators.contract_validator import ContractValidationError, ContractValidator

PUBLIC_REGISTRY_SYMBOLS = {
    "ContractCompatibilityError",
    "ContractNotFoundError",
    "ContractRegistry",
    "ContractRegistryError",
    "InvalidContractReferenceError",
    "InvalidContractSchemaError",
    "ResolvedContractSpec",
    "UntrustedPythonContractError",
}
DEFAULT_GRAPHS = Path(__file__).resolve().parents[2] / "src" / "ai_engineering_harness" / "defaults" / "graphs"


def _write_schema(path: Path, schema: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(schema, ensure_ascii=False), encoding="utf-8")


def _object_schema(
    *,
    required: list[str],
    properties: dict[str, dict[str, Any]],
    additional_properties: bool = True,
) -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": additional_properties,
    }


def _resolved_from_file(registry: ContractRegistry, path: Path, schema: dict[str, Any]) -> ResolvedContractSpec:
    _write_schema(path, schema)
    return registry.resolve(f"jsonschema:{path.name}")


def _valid_graph() -> GraphSpec:
    contract_name = (
        "ai_engineering_harness.contracts.nodes.context_sufficiency.RetrievalRequest"
    )
    return GraphSpec.model_validate(
        {
            "graph": {
                "name": "registry-fixture",
                "graph_schema_version": GRAPH_SCHEMA_VERSION,
                "definition_version": "1.0.0",
                "entrypoint": "agent",
                "status": "stable",
            },
            "nodes": [
                {
                    "id": "agent",
                    "type": "agent",
                    "role": "analyst",
                    "input_contract": contract_name,
                    "output_contract": contract_name,
                    "on_success": "completed",
                    "on_failure": "failed",
                }
            ],
            "terminal_states": [
                {"id": "completed", "outcome": "success"},
                {"id": "failed", "outcome": "failure"},
            ],
            "contracts": [contract_name],
        }
    )


def test_public_contract_registry_api_exports_frozen_symbols() -> None:
    assert PUBLIC_REGISTRY_SYMBOLS <= set(public_contracts.__all__)
    assert issubclass(ContractNotFoundError, ContractRegistryError)
    for symbol in PUBLIC_REGISTRY_SYMBOLS:
        assert getattr(public_contracts, symbol) is not None


def test_internal_catalog_uses_qualified_names_and_exact_legacy_aliases() -> None:
    registry = ContractRegistry()

    assert len(registry.available_contracts) == 18
    assert len(registry.legacy_aliases) == 15
    assert all(name.startswith("ai_engineering_harness.contracts.") for name in registry.available_contracts)
    assert (
        "ai_engineering_harness.contracts.nodes.context_sufficiency.ContextSufficiencyReport"
        in registry.available_contracts
    )
    assert not any(
        name.endswith("node_contracts.ContextSufficiencyReport")
        for name in registry.available_contracts
    )
    for alias in registry.legacy_aliases:
        resolved = registry.resolve(alias)
        assert resolved.source == "internal"
        assert resolved.requested_reference == alias
        assert resolved.digest.startswith("sha256:")


def test_internal_alias_and_canonical_name_resolve_to_same_schema_digest() -> None:
    registry = ContractRegistry()
    alias = "contracts/nodes/context_sufficiency.py#RetrievalRequest"
    canonical = "ai_engineering_harness.contracts.nodes.context_sufficiency.RetrievalRequest"

    assert registry.resolve(alias).digest == registry.resolve(canonical).digest


def test_legacy_aliases_exactly_cover_references_used_by_default_graphs() -> None:
    references: list[str] = []
    for graph_path in sorted(DEFAULT_GRAPHS.glob("*.yaml")):
        graph = yaml.safe_load(graph_path.read_text(encoding="utf-8"))
        for node in graph.get("nodes", []):
            references.extend(
                node[key]
                for key in ("input_contract", "output_contract")
                if key in node
            )

    registry = ContractRegistry()

    assert len(references) == 24
    historical_names = {
        "ai_engineering_harness.contracts.events.execution_event.KnowledgeSyncEvent",
        "ai_engineering_harness.contracts.events.knowledge_sync.KnowledgeUpdateEvent",
        "ai_engineering_harness.contracts.events.knowledge_sync.KnowledgeSyncCompleted",
        "ai_engineering_harness.contracts.events.knowledge_sync.KnowledgeSyncFailed",
    }
    assert set(references) < set(registry.legacy_aliases)
    assert set(registry.legacy_aliases) - set(references) == historical_names


def test_historical_knowledge_contract_names_resolve_to_canonical_models() -> None:
    registry = ContractRegistry()
    expected_suffixes = {
        "ai_engineering_harness.contracts.events.execution_event.KnowledgeSyncEvent": ".ExecutionEvent",
        "ai_engineering_harness.contracts.events.knowledge_sync.KnowledgeUpdateEvent": ".ExecutionEvent",
        "ai_engineering_harness.contracts.events.knowledge_sync.KnowledgeSyncCompleted": ".KnowledgeSyncCompletedDetails",
        "ai_engineering_harness.contracts.events.knowledge_sync.KnowledgeSyncFailed": ".KnowledgeSyncFailedDetails",
    }

    for reference, suffix in expected_suffixes.items():
        resolved = registry.resolve(reference)
        assert resolved.requested_reference == reference
        assert resolved.canonical_name.endswith(suffix)


def test_unknown_short_name_and_arbitrary_file_alias_fail_closed() -> None:
    registry = ContractRegistry()

    with pytest.raises(ContractNotFoundError, match="not registered"):
        registry.resolve("ContextSufficiencyReport")
    with pytest.raises(InvalidContractReferenceError, match="not allowlisted"):
        registry.resolve("contracts/malicious.py#Payload")


def test_internal_registration_rejects_duplicate_and_non_pydantic_model() -> None:
    registry = ContractRegistry()

    with pytest.raises(InvalidContractReferenceError, match="already registered"):
        registry.register_internal(RetrievalRequest)
    with pytest.raises(InvalidContractSchemaError, match="Pydantic"):
        registry.register_internal(object)


def test_resolve_many_preserves_order_and_deduplicates_identical_references() -> None:
    registry = ContractRegistry()
    first = "contracts/nodes/context_sufficiency.py#RetrievalRequest"
    second = "contracts/nodes/code_generation.py#CodeGenerationInput"

    resolved = registry.resolve_many([first, first, second])

    assert [item.requested_reference for item in resolved] == [first, second]


def test_resolve_many_rejects_one_bare_string() -> None:
    with pytest.raises(InvalidContractReferenceError, match="iterable"):
        ContractRegistry().resolve_many("not-an-iterable-of-refs")
    with pytest.raises(InvalidContractReferenceError, match="every contract reference"):
        ContractRegistry().resolve_many([123])


def test_approved_python_contracts_rejects_one_bare_string() -> None:
    with pytest.raises(InvalidContractReferenceError, match="iterable"):
        ContractRegistry(approved_python_contracts="python:package.module:Payload")


def test_valid_external_json_schema_and_pointer_are_resolved(tmp_path: Path) -> None:
    schema_file = tmp_path / "contracts.json"
    _write_schema(
        schema_file,
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$defs": {
                "Payload": {
                    "type": "object",
                    "properties": {"value": {"type": "string"}},
                    "required": ["value"],
                }
            },
        },
    )

    resolved = ContractRegistry(tmp_path).resolve("jsonschema:contracts.json#/$defs/Payload")

    assert resolved.source == "json_schema"
    assert resolved.canonical_name == "jsonschema:contracts.json#/$defs/Payload"
    assert resolved.contract_schema["required"] == ["value"]


def test_external_schema_digest_is_canonical_across_key_order(tmp_path: Path) -> None:
    left = {"type": "object", "required": ["value"], "properties": {"value": {"type": "string"}}}
    right = {"properties": {"value": {"type": "string"}}, "required": ["value"], "type": "object"}
    registry = ContractRegistry(tmp_path)

    left_resolved = _resolved_from_file(registry, tmp_path / "left.json", left)
    right_resolved = _resolved_from_file(registry, tmp_path / "right.json", right)

    assert left_resolved.digest == right_resolved.digest


@pytest.mark.parametrize(
    "reference",
    [
        "jsonschema:../outside.json",
        "jsonschema:folder/./schema.json",
        "jsonschema:C:/outside.json",
        "jsonschema:schema.yaml",
    ],
)
def test_external_schema_unsafe_path_syntax_is_rejected(reference: str, tmp_path: Path) -> None:
    with pytest.raises(InvalidContractReferenceError):
        ContractRegistry(tmp_path).resolve(reference)


def test_external_schema_resolved_symlink_escape_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "root"
    root.mkdir()
    linked = root / "linked.json"
    outside = tmp_path / "outside.json"
    _write_schema(linked, {"type": "object"})
    _write_schema(outside, {"type": "object"})
    registry = ContractRegistry(root)
    original_resolve = Path.resolve
    linked_resolved = original_resolve(linked)
    outside_resolved = original_resolve(outside)

    def redirect_link(path: Path, *args: object, **kwargs: object) -> Path:
        resolved = original_resolve(path, *args, **kwargs)
        return outside_resolved if resolved == linked_resolved else resolved

    monkeypatch.setattr(Path, "resolve", redirect_link)

    with pytest.raises(InvalidContractReferenceError, match="escapes schema root"):
        registry.resolve("jsonschema:linked.json")


def test_external_schema_missing_invalid_json_and_invalid_schema_fail(tmp_path: Path) -> None:
    registry = ContractRegistry(tmp_path)
    (tmp_path / "syntax.json").write_text("{broken", encoding="utf-8")
    _write_schema(tmp_path / "invalid.json", {"type": "not-a-json-type"})

    with pytest.raises(ContractNotFoundError, match="does not exist"):
        registry.resolve("jsonschema:missing.json")
    with pytest.raises(InvalidContractSchemaError, match="cannot read"):
        registry.resolve("jsonschema:syntax.json")
    with pytest.raises(InvalidContractSchemaError, match="invalid JSON Schema"):
        registry.resolve("jsonschema:invalid.json")


@pytest.mark.parametrize(
    "reference",
    [
        "jsonschema:contract.json#not-a-pointer",
        "jsonschema:contract.json#/$defs/Missing",
        "jsonschema:contract.json#/title",
    ],
)
def test_external_schema_invalid_pointer_fails(reference: str, tmp_path: Path) -> None:
    _write_schema(
        tmp_path / "contract.json",
        {"title": "Contract", "$defs": {"Payload": {"type": "object"}}},
    )

    with pytest.raises(ContractRegistryError):
        ContractRegistry(tmp_path).resolve(reference)


@pytest.mark.parametrize(
    ("repository_trusted", "approved"),
    [
        (False, True),
        (True, False),
    ],
)
def test_untrusted_or_unapproved_python_never_imports(
    repository_trusted: bool,
    approved: bool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module_name = "f12_malicious_contract"
    reference = f"python:{module_name}:Payload"
    sentinel = tmp_path / "executed.txt"
    (tmp_path / f"{module_name}.py").write_text(
        "from pathlib import Path\n"
        f"Path({str(sentinel)!r}).write_text('executed', encoding='utf-8')\n"
        "from pydantic import BaseModel\n"
        "class Payload(BaseModel):\n"
        "    value: str\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    registry = ContractRegistry(
        tmp_path,
        repository_trusted=repository_trusted,
        approved_python_contracts=[reference] if approved else [],
    )

    with pytest.raises(UntrustedPythonContractError):
        registry.resolve(reference)

    assert not sentinel.exists()
    assert module_name not in sys.modules


def test_explicitly_trusted_and_approved_python_model_is_resolved(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module_name = "f12_approved_contract"
    reference = f"python:{module_name}:Payload"
    (tmp_path / f"{module_name}.py").write_text(
        "from pydantic import BaseModel\n"
        "class Payload(BaseModel):\n"
        "    value: str\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    registry = ContractRegistry(
        tmp_path,
        repository_trusted=True,
        approved_python_contracts=[reference],
    )

    try:
        resolved = registry.resolve(reference)
    finally:
        sys.modules.pop(module_name, None)

    assert resolved.source == "trusted_python"
    assert resolved.contract_schema["properties"]["value"]["type"] == "string"


@pytest.mark.parametrize(
    ("module_body", "symbol", "error"),
    [
        ("class Other:\n    pass\n", "Missing", ContractNotFoundError),
        ("class Payload:\n    pass\n", "Payload", InvalidContractSchemaError),
    ],
)
def test_approved_python_requires_existing_pydantic_symbol(
    module_body: str,
    symbol: str,
    error: type[ContractRegistryError],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module_name = f"f12_invalid_{symbol.lower()}"
    reference = f"python:{module_name}:{symbol}"
    (tmp_path / f"{module_name}.py").write_text(module_body, encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    registry = ContractRegistry(
        tmp_path,
        repository_trusted=True,
        approved_python_contracts=[reference],
    )

    try:
        with pytest.raises(error):
            registry.resolve(reference)
    finally:
        sys.modules.pop(module_name, None)


def test_malformed_python_reference_fails_before_trust_lookup(tmp_path: Path) -> None:
    with pytest.raises(InvalidContractReferenceError, match="must use"):
        ContractRegistry(tmp_path, repository_trusted=True).resolve("python:path/to/file.py#Payload")


def test_resolved_contract_rejects_tampered_digest() -> None:
    resolved = ContractRegistry().resolve(
        "ai_engineering_harness.contracts.nodes.context_sufficiency.RetrievalRequest"
    )

    with pytest.raises(InvalidContractSchemaError, match="does not match"):
        ResolvedContractSpec(
            canonical_name=resolved.canonical_name,
            requested_reference=resolved.requested_reference,
            source=resolved.source,
            contract_schema=resolved.contract_schema,
            digest="sha256:" + "0" * 64,
        )


def test_compiled_artifact_round_trip_contains_resolved_schema_and_digest() -> None:
    graph = _valid_graph()
    registry = ContractRegistry()
    references = [
        graph.nodes[0].input_contract,
        graph.nodes[0].output_contract,
        *graph.contracts,
    ]
    artifact = CompiledGraphArtifact.build(
        graph=graph,
        resolved_contracts=registry.resolve_many(references),
        resolved_policies=(),
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
    assert len(restored.resolved_contracts) == 1
    assert restored.resolved_contracts[0].contract_schema["type"] == "object"
    assert restored.resolved_contracts[0].digest.startswith("sha256:")


def test_compilation_step_fails_before_artifact_for_missing_contract() -> None:
    with pytest.raises(ContractNotFoundError, match="not registered"):
        ContractRegistry().resolve_many(["ai_engineering_harness.contracts.nodes.Missing"])


def test_identical_contract_is_compatible() -> None:
    registry = ContractRegistry()
    reference = "ai_engineering_harness.contracts.nodes.context_sufficiency.RetrievalRequest"

    assert registry.validate_compatibility(reference, reference) is True


def test_structural_compatibility_accepts_guaranteed_required_fields(tmp_path: Path) -> None:
    registry = ContractRegistry(tmp_path)
    output = _resolved_from_file(
        registry,
        tmp_path / "output.json",
        _object_schema(
            required=["id", "count"],
            properties={"id": {"type": "string"}, "count": {"type": "integer"}},
        ),
    )
    input_ = _resolved_from_file(
        registry,
        tmp_path / "input.json",
        _object_schema(required=["id"], properties={"id": {"type": "string"}}),
    )

    assert registry.validate_compatibility(output, input_) is True


def test_structural_compatibility_accepts_integer_output_for_number_input(tmp_path: Path) -> None:
    registry = ContractRegistry(tmp_path)
    output = _resolved_from_file(
        registry,
        tmp_path / "integer.json",
        _object_schema(required=["value"], properties={"value": {"type": "integer"}}),
    )
    input_ = _resolved_from_file(
        registry,
        tmp_path / "number.json",
        _object_schema(required=["value"], properties={"value": {"type": "number"}}),
    )

    assert registry.validate_compatibility(output, input_) is True


def test_structural_compatibility_rejects_missing_required_and_wrong_type(tmp_path: Path) -> None:
    registry = ContractRegistry(tmp_path)
    output = _resolved_from_file(
        registry,
        tmp_path / "output.json",
        _object_schema(required=["other"], properties={"other": {"type": "string"}}),
    )
    input_ = _resolved_from_file(
        registry,
        tmp_path / "input.json",
        _object_schema(required=["id"], properties={"id": {"type": "string"}}),
    )

    with pytest.raises(ContractCompatibilityError, match="required input"):
        registry.validate_compatibility(output, input_)

    wrong_type = _resolved_from_file(
        registry,
        tmp_path / "wrong-type.json",
        _object_schema(required=["id"], properties={"id": {"type": "integer"}}),
    )
    with pytest.raises(ContractCompatibilityError, match="not accepted"):
        registry.validate_compatibility(wrong_type, input_)


def test_structural_compatibility_rejects_indeterminate_keyword_and_closed_input(tmp_path: Path) -> None:
    registry = ContractRegistry(tmp_path)
    patterned = _resolved_from_file(
        registry,
        tmp_path / "patterned.json",
        _object_schema(
            required=["id"],
            properties={"id": {"type": "string", "pattern": "^[a-z]+$"}},
        ),
    )
    open_input = _resolved_from_file(
        registry,
        tmp_path / "open-input.json",
        _object_schema(required=["id"], properties={"id": {"type": "string"}}),
    )
    with pytest.raises(ContractCompatibilityError, match="unsupported"):
        registry.validate_compatibility(patterned, open_input)

    output = _resolved_from_file(
        registry,
        tmp_path / "extra-output.json",
        _object_schema(
            required=["id", "extra"],
            properties={"id": {"type": "string"}, "extra": {"type": "string"}},
            additional_properties=False,
        ),
    )
    closed_input = _resolved_from_file(
        registry,
        tmp_path / "closed-input.json",
        _object_schema(
            required=["id"],
            properties={"id": {"type": "string"}},
            additional_properties=False,
        ),
    )
    with pytest.raises(ContractCompatibilityError, match="closed input"):
        registry.validate_compatibility(output, closed_input)


def test_structural_compatibility_checks_optional_output_fields(tmp_path: Path) -> None:
    registry = ContractRegistry(tmp_path)
    output = _resolved_from_file(
        registry,
        tmp_path / "optional-output.json",
        _object_schema(required=["id"], properties={"id": {"type": "integer"}}),
    )
    input_ = _resolved_from_file(
        registry,
        tmp_path / "optional-input.json",
        _object_schema(required=[], properties={"id": {"type": "string"}}),
    )

    with pytest.raises(ContractCompatibilityError, match="not accepted"):
        registry.validate_compatibility(output, input_)


def test_legacy_adapter_preserves_known_contracts_and_rejects_arbitrary_path(tmp_path: Path) -> None:
    validator = ContractValidator(tmp_path)
    valid_graph = {
        "nodes": [
            {
                "id": "known",
                "input_contract": "contracts/nodes/context_sufficiency.py#RetrievalRequest",
                "output_contract": "contracts/nodes/context_sufficiency.py#ContextSufficiencyReport",
            }
        ]
    }
    assert validator.validate(valid_graph) is True

    sentinel = tmp_path / "executed.txt"
    malicious = tmp_path / "malicious.py"
    malicious.write_text(
        "from pathlib import Path\n"
        f"Path({str(sentinel)!r}).write_text('executed', encoding='utf-8')\n",
        encoding="utf-8",
    )
    invalid_graph = {"nodes": [{"id": "malicious", "input_contract": "malicious.py#Payload"}]}

    with pytest.raises(ContractValidationError, match="not allowlisted"):
        validator.validate(invalid_graph)
    assert not sentinel.exists()


def test_legacy_adapter_preserves_error_type_for_missing_contract(tmp_path: Path) -> None:
    graph = {"nodes": [{"id": "missing", "input_contract": "MissingContract"}]}

    with pytest.raises(ContractValidationError, match="MissingContract"):
        ContractValidator(tmp_path).validate(graph)
