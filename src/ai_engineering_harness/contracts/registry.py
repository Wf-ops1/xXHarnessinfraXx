"""Fail-closed registry for internal, JSON Schema, and explicitly approved contracts."""

from __future__ import annotations

import hashlib
import importlib
import json
import re
from collections.abc import Iterable, Mapping
from pathlib import Path, PurePosixPath
from typing import Any, Literal, Self, TypeAlias
from urllib.parse import unquote

from jsonschema.exceptions import SchemaError
from jsonschema.validators import validator_for
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .events.execution_event import ExecutionEvent
from .events.knowledge_sync import (
    KnowledgeSyncCompletedDetails,
    KnowledgeSyncDetails,
    KnowledgeSyncFailedDetails,
    KnowledgeUpdateDetails,
)
from .nodes.architecture_analysis import ArchitectureAnalysisInput, ArchitectureAnalysisOutput
from .nodes.code_generation import CodeGenerationInput, CodeGenerationOutput
from .nodes.context_sufficiency import ContextSufficiencyReport, RetrievalRequest
from .nodes.node_contracts import ArchitectureAnalysis, CodeGenNode
from .nodes.test_generation import TestGenerationInput, TestGenerationOutput
from .transactions.knowledge_transaction import ArtifactVersionItem, JournalState, KnowledgeTransaction

ContractModel: TypeAlias = type[BaseModel]
ContractSource: TypeAlias = Literal["internal", "json_schema", "trusted_python"]

_PYTHON_REFERENCE_RE = re.compile(
    r"^python:(?P<module>[A-Za-z_]\w*(?:\.[A-Za-z_]\w)*):(?P<symbol>[A-Za-z_]\w*)$"
)
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_COMPOSITION_KEYWORDS = frozenset({"$ref", "allOf", "anyOf", "oneOf", "not", "if", "then", "else"})
_PROPERTY_ANNOTATIONS = frozenset(
    {"type", "title", "description", "default", "examples", "deprecated", "readOnly", "writeOnly"}
)


class ContractRegistryError(Exception):
    """Base error for safe contract resolution."""


class InvalidContractReferenceError(ContractRegistryError):
    """A contract reference has invalid or unsafe syntax."""


class ContractNotFoundError(ContractRegistryError):
    """A well-formed contract reference cannot be resolved."""


class UntrustedPythonContractError(ContractRegistryError):
    """Python execution was requested without exact trust and approval."""


class InvalidContractSchemaError(ContractRegistryError):
    """A resolved contract does not contain a valid, intact JSON Schema."""


class ContractCompatibilityError(ContractRegistryError):
    """Output-to-input schema compatibility cannot be proven safely."""


def _canonical_json(value: object) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise InvalidContractSchemaError(f"contract schema is not canonical JSON: {exc}") from exc


def _schema_digest(schema: Mapping[str, Any]) -> str:
    canonical = _canonical_json(schema).encode("utf-8")
    return f"sha256:{hashlib.sha256(canonical).hexdigest()}"


def _detached_schema(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise InvalidContractSchemaError("contract schema must be a JSON object")
    detached = json.loads(_canonical_json(value))
    if not isinstance(detached, dict):  # Defensive: the Mapping guard above should make this unreachable.
        raise InvalidContractSchemaError("contract schema must normalize to a JSON object")
    return detached


class ResolvedContractSpec(BaseModel):
    """A contract schema and its deterministic identity in a compiled artifact."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    canonical_name: str = Field(min_length=1)
    requested_reference: str = Field(min_length=1)
    source: ContractSource
    contract_schema: dict[str, Any]
    digest: str = Field(pattern=_DIGEST_RE.pattern)

    @field_validator("contract_schema", mode="before")
    @classmethod
    def detach_schema(cls, value: object) -> dict[str, Any]:
        return _detached_schema(value)

    @model_validator(mode="after")
    def validate_digest(self) -> Self:
        expected = _schema_digest(self.contract_schema)
        if self.digest != expected:
            raise InvalidContractSchemaError(
                f"contract digest does not match schema: expected {expected}, received {self.digest}"
            )
        return self

    def verify_integrity(self) -> None:
        """Recheck integrity after crossing a boundary that may have held mutable data."""
        expected = _schema_digest(self.contract_schema)
        if self.digest != expected:
            raise InvalidContractSchemaError(
                f"contract digest does not match schema: expected {expected}, received {self.digest}"
            )


_INTERNAL_MODELS: tuple[ContractModel, ...] = (
    ArchitectureAnalysisInput,
    ArchitectureAnalysisOutput,
    CodeGenerationInput,
    CodeGenerationOutput,
    ContextSufficiencyReport,
    RetrievalRequest,
    ArchitectureAnalysis,
    CodeGenNode,
    TestGenerationInput,
    TestGenerationOutput,
    ExecutionEvent,
    KnowledgeSyncDetails,
    KnowledgeUpdateDetails,
    KnowledgeSyncCompletedDetails,
    KnowledgeSyncFailedDetails,
    ArtifactVersionItem,
    KnowledgeTransaction,
    JournalState,
)

_LEGACY_ALIAS_MODELS: dict[str, ContractModel] = {
    "ai_engineering_harness.contracts.events.execution_event.KnowledgeSyncEvent": ExecutionEvent,
    "ai_engineering_harness.contracts.events.knowledge_sync.KnowledgeUpdateEvent": ExecutionEvent,
    "ai_engineering_harness.contracts.events.knowledge_sync.KnowledgeSyncCompleted": KnowledgeSyncCompletedDetails,
    "ai_engineering_harness.contracts.events.knowledge_sync.KnowledgeSyncFailed": KnowledgeSyncFailedDetails,
    "contracts/events/knowledge_sync.py#KnowledgeSyncCompleted": KnowledgeSyncCompletedDetails,
    "contracts/events/knowledge_sync.py#KnowledgeSyncFailed": KnowledgeSyncFailedDetails,
    "contracts/nodes/architecture_analysis.py#ArchitectureAnalysisInput": ArchitectureAnalysisInput,
    "contracts/nodes/architecture_analysis.py#ArchitectureAnalysisOutput": ArchitectureAnalysisOutput,
    "contracts/nodes/code_generation.py#CodeGenerationInput": CodeGenerationInput,
    "contracts/nodes/code_generation.py#CodeGenerationOutput": CodeGenerationOutput,
    "contracts/nodes/context_sufficiency.py#ContextSufficiencyReport": ContextSufficiencyReport,
    "contracts/nodes/context_sufficiency.py#RetrievalRequest": RetrievalRequest,
    "contracts/nodes/test_generation.py#TestGenerationInput": TestGenerationInput,
    "contracts/nodes/test_generation.py#TestGenerationOutput": TestGenerationOutput,
    "contracts/transactions/knowledge_transaction.py#KnowledgeTransaction": KnowledgeTransaction,
}


def _qualified_model_name(model: ContractModel) -> str:
    return f"{model.__module__}.{model.__qualname__}"


class ContractRegistry:
    """Resolve contracts without deriving Python imports from untrusted references."""

    def __init__(
        self,
        schema_root: Path | None = None,
        *,
        repository_trusted: bool = False,
        approved_python_contracts: Iterable[str] = (),
    ) -> None:
        if type(repository_trusted) is not bool:
            raise InvalidContractReferenceError("repository_trusted must be an explicit bool")
        if isinstance(approved_python_contracts, (str, bytes)):
            raise InvalidContractReferenceError("approved_python_contracts must be an iterable of exact references")

        self.schema_root = (schema_root or Path.cwd()).resolve()
        self.repository_trusted = repository_trusted
        self.approved_python_contracts = frozenset(approved_python_contracts)
        self._internal_models: dict[str, ContractModel] = {}
        self._aliases: dict[str, str] = {}

        for model in _INTERNAL_MODELS:
            self.register_internal(model)
        for alias, model in _LEGACY_ALIAS_MODELS.items():
            self._register_alias(alias, _qualified_model_name(model))

    @property
    def available_contracts(self) -> tuple[str, ...]:
        """Return canonical internal names in stable order."""
        return tuple(sorted(self._internal_models))

    @property
    def legacy_aliases(self) -> tuple[str, ...]:
        """Return the exact allowlisted legacy aliases in stable order."""
        return tuple(sorted(self._aliases))

    def register_internal(self, model: ContractModel, *, aliases: Iterable[str] = ()) -> str:
        """Register an already-imported internal Pydantic model and optional exact aliases."""
        if not isinstance(model, type) or not issubclass(model, BaseModel):
            raise InvalidContractSchemaError("internal contract must be a Pydantic BaseModel subclass")

        canonical_name = _qualified_model_name(model)
        if canonical_name in self._internal_models:
            raise InvalidContractReferenceError(f"contract is already registered: {canonical_name}")
        aliases_to_add = tuple(aliases)
        for alias in aliases_to_add:
            self._validate_alias(alias)
        if len(set(aliases_to_add)) != len(aliases_to_add):
            raise InvalidContractReferenceError("contract aliases must be unique within one registration")

        self._internal_models[canonical_name] = model
        for alias in aliases_to_add:
            self._aliases[alias] = canonical_name
        return canonical_name

    def resolve(self, reference: str) -> ResolvedContractSpec:
        """Resolve one reference using only its explicit source namespace."""
        if not isinstance(reference, str) or not reference.strip() or reference != reference.strip():
            raise InvalidContractReferenceError("contract reference must be a non-empty, trimmed string")

        if reference.startswith("jsonschema:"):
            return self._resolve_json_schema(reference)
        if reference.startswith("python:"):
            return self._resolve_trusted_python(reference)
        return self._resolve_internal(reference)

    def resolve_many(self, references: Iterable[str]) -> tuple[ResolvedContractSpec, ...]:
        """Resolve references in order, de-duplicating only identical requested strings."""
        if isinstance(references, (str, bytes)):
            raise InvalidContractReferenceError("resolve_many expects an iterable of references, not one string")

        resolved: list[ResolvedContractSpec] = []
        seen: set[str] = set()
        for reference in references:
            if not isinstance(reference, str):
                raise InvalidContractReferenceError("every contract reference must be a string")
            if reference in seen:
                continue
            resolved.append(self.resolve(reference))
            seen.add(reference)
        return tuple(resolved)

    def validate_compatibility(
        self,
        output_contract: str | ResolvedContractSpec,
        input_contract: str | ResolvedContractSpec,
    ) -> bool:
        """Prove a conservative output-to-input relationship or fail closed."""
        output = self.resolve(output_contract) if isinstance(output_contract, str) else output_contract
        input_ = self.resolve(input_contract) if isinstance(input_contract, str) else input_contract
        output.verify_integrity()
        input_.verify_integrity()

        if output.digest == input_.digest:
            return True

        output_properties, output_required, output_extra = self._object_shape(output)
        input_properties, input_required, input_extra = self._object_shape(input_)

        missing_required = sorted(input_required - output_required)
        if missing_required:
            raise ContractCompatibilityError(
                f"{output.canonical_name} does not guarantee required input fields: {', '.join(missing_required)}"
            )

        for field_name in sorted(input_required):
            output_field = output_properties.get(field_name)
            input_field = input_properties.get(field_name)
            if not isinstance(output_field, Mapping) or not isinstance(input_field, Mapping):
                raise ContractCompatibilityError(f"cannot prove schema for required field {field_name!r}")
            self._validate_field_compatibility(field_name, output_field, input_field)

        overlapping_optional = (set(output_properties) & set(input_properties)) - input_required
        for field_name in sorted(overlapping_optional):
            output_field = output_properties[field_name]
            input_field = input_properties[field_name]
            if not isinstance(output_field, Mapping) or not isinstance(input_field, Mapping):
                raise ContractCompatibilityError(f"cannot prove schema for optional field {field_name!r}")
            self._validate_field_compatibility(field_name, output_field, input_field)

        unexpected = sorted(set(output_properties) - set(input_properties))
        if input_extra is False:
            if unexpected or output_extra is not False:
                detail = f"unexpected output fields: {', '.join(unexpected)}" if unexpected else "open output object"
                raise ContractCompatibilityError(
                    f"{output.canonical_name} is incompatible with closed input {input_.canonical_name}: {detail}"
                )
        elif isinstance(input_extra, dict) and input_extra:
            for field_name in unexpected:
                output_field = output_properties[field_name]
                if not isinstance(output_field, Mapping):
                    raise ContractCompatibilityError(f"cannot prove schema for additional field {field_name!r}")
                self._validate_field_compatibility(field_name, output_field, input_extra)
            if output_extra is True:
                raise ContractCompatibilityError(
                    f"open output {output.canonical_name} cannot be proven against constrained additional properties"
                )
            if isinstance(output_extra, dict) and output_extra:
                self._validate_field_compatibility("<additionalProperties>", output_extra, input_extra)
        return True

    def _register_alias(self, alias: str, canonical_name: str) -> None:
        self._validate_alias(alias)
        if canonical_name not in self._internal_models:
            raise ContractNotFoundError(f"alias target is not registered: {canonical_name}")
        self._aliases[alias] = canonical_name

    def _validate_alias(self, alias: str) -> None:
        if not isinstance(alias, str) or not alias or alias != alias.strip():
            raise InvalidContractReferenceError("contract alias must be a non-empty, trimmed string")
        if alias in self._aliases or alias in self._internal_models:
            raise InvalidContractReferenceError(f"contract alias is already registered: {alias}")

    def _resolve_internal(self, reference: str) -> ResolvedContractSpec:
        canonical_name = self._aliases.get(reference, reference)
        model = self._internal_models.get(canonical_name)
        if model is None:
            if any(token in reference for token in ("/", "\\", "#")):
                raise InvalidContractReferenceError(
                    f"filesystem-style contract reference is not allowlisted: {reference}"
                )
            raise ContractNotFoundError(f"internal contract is not registered: {reference}")
        return self._resolved(
            canonical_name=canonical_name,
            requested_reference=reference,
            source="internal",
            schema=model.model_json_schema(),
        )

    def _resolve_json_schema(self, reference: str) -> ResolvedContractSpec:
        raw = reference.removeprefix("jsonschema:")
        raw_path, separator, raw_pointer = raw.partition("#")
        if not raw_path or "\\" in raw_path or ":" in raw_path:
            raise InvalidContractReferenceError(f"invalid JSON Schema path: {raw_path!r}")

        raw_parts = raw_path.split("/")
        relative = PurePosixPath(raw_path)
        if relative.is_absolute() or any(part in {"", ".", ".."} for part in raw_parts):
            raise InvalidContractReferenceError(f"JSON Schema path must be normalized and relative: {raw_path!r}")
        if relative.suffix.lower() != ".json":
            raise InvalidContractReferenceError("external JSON Schema reference must use a .json file")

        candidate = (self.schema_root / Path(*relative.parts)).resolve()
        if not candidate.is_relative_to(self.schema_root):
            raise InvalidContractReferenceError(f"JSON Schema path escapes schema root: {raw_path!r}")
        if not candidate.is_file():
            raise ContractNotFoundError(f"JSON Schema file does not exist: {raw_path}")

        try:
            document = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise InvalidContractSchemaError(f"cannot read JSON Schema {raw_path!r}: {exc}") from exc
        if not isinstance(document, dict):
            raise InvalidContractSchemaError("external JSON Schema must be a JSON object")
        self._check_json_schema(document, reference)

        pointer = unquote(raw_pointer) if separator else ""
        schema = self._resolve_json_pointer(document, pointer, reference)
        self._check_json_schema(schema, reference)
        canonical_reference = f"jsonschema:{relative.as_posix()}" + (f"#{pointer}" if separator else "")
        return self._resolved(
            canonical_name=canonical_reference,
            requested_reference=reference,
            source="json_schema",
            schema=schema,
        )

    def _resolve_trusted_python(self, reference: str) -> ResolvedContractSpec:
        match = _PYTHON_REFERENCE_RE.fullmatch(reference)
        if match is None:
            raise InvalidContractReferenceError(
                "trusted Python reference must use python:<qualified.module>:<PydanticClass>"
            )
        if not self.repository_trusted or reference not in self.approved_python_contracts:
            raise UntrustedPythonContractError(
                f"Python contract requires trusted repository and exact approval: {reference}"
            )

        module_name = match.group("module")
        symbol = match.group("symbol")
        try:
            module = importlib.import_module(module_name)
        except Exception as exc:
            raise InvalidContractSchemaError(f"approved Python contract module failed to import: {reference}: {exc}") from exc

        model = getattr(module, symbol, None)
        if model is None:
            raise ContractNotFoundError(f"approved Python contract symbol does not exist: {reference}")
        if not isinstance(model, type) or not issubclass(model, BaseModel):
            raise InvalidContractSchemaError(f"approved Python contract is not a Pydantic model: {reference}")

        canonical_name = _qualified_model_name(model)
        return self._resolved(
            canonical_name=canonical_name,
            requested_reference=reference,
            source="trusted_python",
            schema=model.model_json_schema(),
        )

    @staticmethod
    def _resolve_json_pointer(
        document: dict[str, Any],
        pointer: str,
        reference: str,
    ) -> dict[str, Any]:
        if not pointer:
            return document
        if not pointer.startswith("/"):
            raise InvalidContractReferenceError(f"JSON Schema fragment must be a JSON Pointer: {reference}")

        current: Any = document
        for raw_token in pointer[1:].split("/"):
            token = raw_token.replace("~1", "/").replace("~0", "~")
            if isinstance(current, dict) and token in current:
                current = current[token]
                continue
            if isinstance(current, list) and token.isdigit() and int(token) < len(current):
                current = current[int(token)]
                continue
            raise ContractNotFoundError(f"JSON Pointer does not exist in contract schema: {reference}")
        if not isinstance(current, dict):
            raise InvalidContractSchemaError(f"JSON Pointer does not select a schema object: {reference}")
        return current

    @staticmethod
    def _check_json_schema(schema: dict[str, Any], reference: str) -> None:
        try:
            validator_for(schema).check_schema(schema)
        except SchemaError as exc:
            raise InvalidContractSchemaError(f"invalid JSON Schema for {reference}: {exc.message}") from exc

    @classmethod
    def _resolved(
        cls,
        *,
        canonical_name: str,
        requested_reference: str,
        source: ContractSource,
        schema: Mapping[str, Any],
    ) -> ResolvedContractSpec:
        normalized = _detached_schema(schema)
        cls._check_json_schema(normalized, requested_reference)
        return ResolvedContractSpec(
            canonical_name=canonical_name,
            requested_reference=requested_reference,
            source=source,
            contract_schema=normalized,
            digest=_schema_digest(normalized),
        )

    @staticmethod
    def _object_shape(
        contract: ResolvedContractSpec,
    ) -> tuple[dict[str, Any], set[str], bool | dict[str, Any]]:
        schema = contract.contract_schema
        composition = sorted(_COMPOSITION_KEYWORDS & schema.keys())
        if composition:
            raise ContractCompatibilityError(
                f"cannot prove compatibility for {contract.canonical_name}; composition: {', '.join(composition)}"
            )
        if schema.get("type") != "object":
            raise ContractCompatibilityError(
                f"cannot prove compatibility for non-object contract: {contract.canonical_name}"
            )

        properties = schema.get("properties", {})
        required = schema.get("required", [])
        additional = schema.get("additionalProperties", True)
        if not isinstance(properties, dict) or not isinstance(required, list) or not all(
            isinstance(item, str) for item in required
        ):
            raise ContractCompatibilityError(f"invalid object shape for compatibility: {contract.canonical_name}")
        if not isinstance(additional, (bool, dict)):
            raise ContractCompatibilityError(
                f"invalid additionalProperties in contract: {contract.canonical_name}"
            )
        return properties, set(required), additional

    @staticmethod
    def _validate_field_compatibility(
        field_name: str,
        output_schema: Mapping[str, Any],
        input_schema: Mapping[str, Any],
    ) -> None:
        unsupported = sorted(
            (set(output_schema) | set(input_schema)) - _PROPERTY_ANNOTATIONS
        )
        if unsupported or (_COMPOSITION_KEYWORDS & output_schema.keys()) or (_COMPOSITION_KEYWORDS & input_schema.keys()):
            detail = ", ".join(unsupported or sorted(_COMPOSITION_KEYWORDS))
            raise ContractCompatibilityError(
                f"cannot prove compatibility for field {field_name!r}; unsupported schema keywords: {detail}"
            )

        output_types = ContractRegistry._json_types(output_schema.get("type"), field_name)
        input_types = ContractRegistry._json_types(input_schema.get("type"), field_name)
        for output_type in output_types:
            if output_type in input_types:
                continue
            if output_type == "integer" and "number" in input_types:
                continue
            raise ContractCompatibilityError(
                f"field {field_name!r} output type {output_type!r} is not accepted by input types {sorted(input_types)}"
            )

    @staticmethod
    def _json_types(value: object, field_name: str) -> set[str]:
        valid_types = {"null", "boolean", "object", "array", "number", "string", "integer"}
        if isinstance(value, str):
            result = {value}
        elif isinstance(value, list) and value and all(isinstance(item, str) for item in value):
            result = set(value)
        else:
            raise ContractCompatibilityError(f"field {field_name!r} does not declare a provable JSON type")
        if not result <= valid_types:
            raise ContractCompatibilityError(f"field {field_name!r} declares unknown JSON types: {sorted(result)}")
        return result
