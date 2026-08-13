"""Fail-closed compiler for typed graph specifications."""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path, PurePath, PurePosixPath
from typing import Any, Literal, TypeAlias, cast

import yaml
from pydantic import ValidationError

from ai_engineering_harness.contracts import (
    AgentNodeSpec,
    CompiledGraphArtifact,
    ContractRegistry,
    ContractRegistryError,
    GraphSpec,
    PolicyRegistry,
    PolicyRegistryError,
    SourceManifestEntry,
)
from ai_engineering_harness.security import (
    TrustBoundaryEvaluator,
    TrustCapabilityDeniedError,
    TrustEvaluationResult,
)

_WORKFLOW_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_PACKAGE_SOURCE_PREFIX = "package://ai_engineering_harness.defaults/"
_SourceKind: TypeAlias = Literal[
    "graph",
    "contract_schema",
    "policy",
    "role",
    "role_prompt",
    "tool_registry",
]


@dataclass(frozen=True)
class _LoadedMapping:
    document: dict[str, Any]
    source: SourceManifestEntry


class GraphCompilerError(Exception):
    """Base error for graph compilation."""


class GraphSourceError(GraphCompilerError):
    """The requested YAML source is missing, unsafe, or unreadable."""


class GraphValidationError(GraphCompilerError):
    """The graph or one of its referenced catalogs is invalid."""


class GraphWriteError(GraphCompilerError):
    """The validated artifact could not be written to its canonical destination."""


class GraphCompiler:
    """Compile one YAML graph into the canonical typed artifact."""

    def __init__(
        self,
        project_root: Path,
        *,
        trust_boundary: TrustEvaluationResult | None = None,
    ):
        try:
            resolved_root = Path(project_root).resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise GraphSourceError(f"project root cannot be resolved: {project_root}") from exc
        if not resolved_root.is_dir():
            raise GraphSourceError(f"project root is not a directory: {resolved_root}")

        self.project_root = resolved_root
        self.output_dir = self.project_root / ".harness" / "state" / "compiled"
        boundary = trust_boundary or TrustBoundaryEvaluator(self.project_root).evaluate()
        if not isinstance(boundary, TrustEvaluationResult):
            raise GraphSourceError("trust_boundary must be a TrustEvaluationResult")
        try:
            boundary.require_root(self.project_root)
        except TrustCapabilityDeniedError as exc:
            raise GraphSourceError("compiler trust boundary must match project root") from exc
        if Path(boundary.repository_root) != self.project_root:
            raise GraphSourceError("compiler trust boundary belongs to another repository")
        self.trust_boundary = boundary

    def compile_graph(self, yaml_path: Path, workflow_name: str | None = None) -> Path:
        """Validate and compile a graph without producing output on validation failure."""
        try:
            self.trust_boundary.require_root(self.project_root)
        except TrustCapabilityDeniedError as exc:
            raise GraphValidationError(
                "compiler trust boundary diverged before compilation"
            ) from exc
        source_path = self._resolve_source(yaml_path)
        graph_bytes = self._read_path_bytes(source_path, source=True, label="graph source")
        raw_graph = self._parse_yaml_mapping(graph_bytes, source_path, source=True)

        try:
            graph = GraphSpec.model_validate(raw_graph)
        except ValidationError as exc:
            raise GraphValidationError(f"invalid graph specification {source_path}: {exc}") from exc

        self._validate_workflow_identity(graph.graph.name, workflow_name)

        contract_references = list(graph.contracts)
        for node in graph.nodes:
            if isinstance(node, AgentNodeSpec):
                contract_references.extend((node.input_contract, node.output_contract))

        try:
            contract_sources = self._load_external_contract_sources(contract_references)
            contract_registry = ContractRegistry(
                schema_root=self._contract_schema_root(),
                repository_trusted=self.trust_boundary.is_trusted,
                approved_python_contracts=self.trust_boundary.python_contracts,
            )
            resolved_contracts = contract_registry.resolve_many(contract_references)
            self._verify_external_contract_sources_unchanged(contract_sources)
            policy_registry, catalog_sources = self._policy_registry()
            resolved_policies = policy_registry.resolve_graph(graph)
            graph_source = self._project_manifest_entry("graph", source_path, graph_bytes)
            artifact = CompiledGraphArtifact.build(
                graph=graph,
                resolved_contracts=resolved_contracts,
                resolved_policies=resolved_policies,
                source_manifest=(
                    graph_source,
                    *(source for _, source in contract_sources.values()),
                    *catalog_sources,
                ),
            )
        except (ContractRegistryError, PolicyRegistryError, ValidationError, ValueError) as exc:
            raise GraphValidationError(f"graph references are invalid: {exc}") from exc

        output_file = self.compiled_path(graph.graph.name)
        try:
            self._prepare_output_directory()
            self._atomic_write(output_file, artifact.canonical_json().encode("utf-8"))
        except (OSError, UnicodeError, ValueError) as exc:
            raise GraphWriteError(f"cannot write compiled graph {output_file}: {exc}") from exc
        return output_file

    def compiled_path(self, workflow_name: str) -> Path:
        """Return the canonical output path for a safe workflow identifier."""
        self._validate_workflow_name(workflow_name)
        self._validate_existing_output_directories()
        output_file = self.output_dir / f"{workflow_name}.json"
        if output_file.is_symlink():
            raise GraphWriteError(f"compiled graph path cannot be a symlink: {output_file}")
        if output_file.exists():
            try:
                resolved = output_file.resolve(strict=True)
            except (OSError, RuntimeError) as exc:
                raise GraphWriteError(f"cannot resolve compiled graph path: {output_file}") from exc
            if not resolved.is_file() or not resolved.is_relative_to(self.project_root):
                raise GraphWriteError(f"compiled graph path escapes project root: {output_file}")
        return output_file

    def _resolve_source(self, yaml_path: Path) -> Path:
        candidate = Path(yaml_path)
        if not candidate.is_absolute() and ".." in candidate.parts:
            raise GraphSourceError(f"graph source cannot contain traversal: {yaml_path}")
        if candidate.suffix != ".yaml":
            raise GraphSourceError(f"graph source must use the .yaml extension: {yaml_path}")

        joined = candidate if candidate.is_absolute() else self.project_root / candidate
        try:
            resolved = joined.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise GraphSourceError(f"graph source does not exist or cannot be resolved: {yaml_path}") from exc
        if not resolved.is_relative_to(self.project_root):
            raise GraphSourceError(f"graph source escapes project root: {yaml_path}")
        if not resolved.is_file():
            raise GraphSourceError(f"graph source is not a regular file: {resolved}")
        return resolved

    def _policy_registry(self) -> tuple[PolicyRegistry, tuple[SourceManifestEntry, ...]]:
        try:
            base_registry = PolicyRegistry()
            manifest: list[SourceManifestEntry] = []

            policy_documents: dict[str, Mapping[str, Any]] = {}
            for reference in base_registry.available_policies:
                override = self._load_optional_mapping(
                    self.project_root / ".harness" / "policies" / PurePosixPath(reference).name,
                    allowed_root=self.project_root / ".harness" / "policies",
                    label=f"policy override {reference}",
                    source_kind="policy",
                )
                selected = override or self._load_package_mapping(
                    reference,
                    source_kind="policy",
                    label=reference,
                )
                policy_documents[reference] = selected.document
                manifest.append(selected.source)

            role_overrides, role_override_sources = self._load_role_overrides()
            manifest.extend(role_override_sources)
            role_documents: dict[str, Mapping[str, Any]] = {}
            for role_id in sorted(set(base_registry.available_roles) | set(role_overrides)):
                override = role_overrides.get(role_id)
                if override is not None:
                    role_documents[role_id] = override.document
                    continue
                role = self._load_package_mapping(
                    f"agents/{role_id}/agent.yaml",
                    source_kind="role",
                    label=f"agent role {role_id}",
                )
                prompt_name = self._safe_prompt_name(role_id, role.document)
                prompt_source = self._load_package_source(
                    f"agents/{role_id}/{prompt_name}",
                    source_kind="role_prompt",
                    label=f"agent role {role_id} system prompt",
                )
                role_documents[role_id] = role.document
                manifest.extend((role.source, prompt_source))

            tool_override = self._load_optional_mapping(
                self.project_root / ".harness" / "tools" / "tool_registry.yaml",
                allowed_root=self.project_root / ".harness" / "tools",
                label="tool registry override",
                source_kind="tool_registry",
            )
            tool = tool_override or self._load_package_mapping(
                "tools/tool_registry.yaml",
                source_kind="tool_registry",
                label="tool registry",
            )
            manifest.append(tool.source)

            registry = PolicyRegistry(
                policy_documents=policy_documents,
                role_documents=role_documents,
                tool_registry_document=tool.document,
            )
            return registry, tuple(manifest)
        except GraphValidationError:
            raise
        except (OSError, UnicodeError, yaml.YAMLError, PolicyRegistryError, ValidationError) as exc:
            raise GraphValidationError(f"cannot load policy catalogs: {exc}") from exc

    def _load_external_contract_sources(
        self,
        references: list[str],
    ) -> dict[Path, tuple[bytes, SourceManifestEntry]]:
        sources: dict[Path, tuple[bytes, SourceManifestEntry]] = {}
        schema_root = self._contract_schema_root()
        for reference in references:
            if not reference.startswith("jsonschema:"):
                continue
            raw_path = reference.removeprefix("jsonschema:").partition("#")[0]
            relative = PurePosixPath(raw_path)
            if (
                not raw_path
                or "\\" in raw_path
                or ":" in raw_path
                or relative.is_absolute()
                or any(part in {"", ".", ".."} for part in raw_path.split("/"))
            ):
                raise GraphValidationError(f"invalid JSON Schema source path: {raw_path!r}")
            candidate = schema_root.joinpath(*relative.parts)
            try:
                resolved = candidate.resolve(strict=True)
            except (OSError, RuntimeError) as exc:
                raise GraphValidationError(
                    f"cannot resolve JSON Schema source: {raw_path!r}"
                ) from exc
            if not resolved.is_file() or not resolved.is_relative_to(schema_root):
                raise GraphValidationError(f"unsafe JSON Schema source: {raw_path!r}")
            if resolved not in sources:
                content = self._read_path_bytes(
                    resolved,
                    source=False,
                    label=f"JSON Schema source {raw_path!r}",
                )
                sources[resolved] = (
                    content,
                    self._project_manifest_entry("contract_schema", resolved, content),
                )
        return sources

    def _verify_external_contract_sources_unchanged(
        self,
        sources: Mapping[Path, tuple[bytes, SourceManifestEntry]],
    ) -> None:
        for path, (expected, _) in sources.items():
            observed = self._read_path_bytes(path, source=False, label="JSON Schema source")
            if observed != expected:
                raise GraphValidationError(
                    f"JSON Schema source changed during compilation: {path}"
                )

    def _contract_schema_root(self) -> Path:
        schema_root = self.project_root / ".harness" / "contracts"
        if not schema_root.exists() and not schema_root.is_symlink():
            return schema_root
        try:
            resolved = schema_root.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise GraphValidationError(f"cannot resolve contract schema root: {schema_root}") from exc
        if not resolved.is_dir() or not resolved.is_relative_to(self.project_root):
            raise GraphValidationError(f"contract schema root escapes project root: {schema_root}")
        return resolved

    def _prepare_output_directory(self) -> None:
        self._validate_existing_output_directories()
        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            resolved_output = self.output_dir.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise GraphWriteError(f"cannot create output directory: {self.output_dir}") from exc
        if not resolved_output.is_dir() or not resolved_output.is_relative_to(self.project_root):
            raise GraphWriteError(f"output directory escapes project root: {self.output_dir}")

    def _validate_existing_output_directories(self) -> None:
        current = self.project_root
        for part in (".harness", "state", "compiled"):
            current = current / part
            if current.is_symlink():
                raise GraphWriteError(f"output directory cannot be a symlink: {current}")
            if not current.exists() and not current.is_symlink():
                continue
            try:
                resolved = current.resolve(strict=True)
            except (OSError, RuntimeError) as exc:
                raise GraphWriteError(f"cannot resolve output directory: {current}") from exc
            if not resolved.is_dir() or not resolved.is_relative_to(self.project_root):
                raise GraphWriteError(f"output directory escapes project root: {current}")

    def _load_role_overrides(
        self,
    ) -> tuple[dict[str, _LoadedMapping], tuple[SourceManifestEntry, ...]]:
        roles_root = self.project_root / ".harness" / "agents"
        if not roles_root.exists() and not roles_root.is_symlink():
            return {}, ()
        try:
            resolved_root = roles_root.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise GraphValidationError(f"cannot resolve agent overrides directory: {roles_root}") from exc
        if not resolved_root.is_dir() or not resolved_root.is_relative_to(self.project_root):
            raise GraphValidationError(f"unsafe agent overrides directory: {roles_root}")

        overrides: dict[str, _LoadedMapping] = {}
        sources: list[SourceManifestEntry] = []
        try:
            directories = sorted(resolved_root.iterdir(), key=lambda item: item.name)
        except OSError as exc:
            raise GraphValidationError(f"cannot enumerate agent overrides: {exc}") from exc
        for directory in directories:
            if directory.name.startswith("_") or not directory.is_dir():
                continue
            document = self._load_optional_mapping(
                directory / "agent.yaml",
                allowed_root=resolved_root,
                label=f"agent role override {directory.name}",
                source_kind="role",
            )
            if document is None:
                continue
            prompt_source = self._validate_role_prompt(directory, document.document)
            overrides[directory.name] = document
            sources.extend((document.source, prompt_source))
        return overrides, tuple(sources)

    def _validate_role_prompt(
        self,
        role_directory: Path,
        document: Mapping[str, Any],
    ) -> SourceManifestEntry:
        prompt_name = self._safe_prompt_name(role_directory.name, document)
        prompt_path = role_directory / prompt_name
        try:
            resolved_prompt = prompt_path.resolve(strict=True)
            resolved_role = role_directory.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise GraphValidationError(
                f"agent role override {role_directory.name!r} references a missing system prompt"
            ) from exc
        if not resolved_prompt.is_file() or not resolved_prompt.is_relative_to(resolved_role):
            raise GraphValidationError(
                f"agent role override {role_directory.name!r} references an unsafe system prompt"
            )
        content = self._read_path_bytes(
            resolved_prompt,
            source=False,
            label=f"agent role override {role_directory.name!r} system prompt",
        )
        return self._project_manifest_entry("role_prompt", resolved_prompt, content)

    @staticmethod
    def _safe_prompt_name(role_id: str, document: Mapping[str, Any]) -> str:
        prompt_name = document.get("system_prompt_file")
        if (
            not isinstance(prompt_name, str)
            or not prompt_name
            or PurePath(prompt_name).name != prompt_name
        ):
            raise GraphValidationError(
                f"agent role {role_id!r} has an unsafe system_prompt_file"
            )
        return prompt_name

    def _load_optional_mapping(
        self,
        path: Path,
        *,
        allowed_root: Path,
        label: str,
        source_kind: _SourceKind,
    ) -> _LoadedMapping | None:
        if not path.exists() and not path.is_symlink():
            return None
        try:
            resolved = path.resolve(strict=True)
            resolved_root = allowed_root.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise GraphValidationError(f"cannot resolve {label}: {path}") from exc
        if not resolved.is_relative_to(resolved_root) or not resolved.is_relative_to(self.project_root):
            raise GraphValidationError(f"{label} escapes its allowed directory: {path}")
        if not resolved.is_file():
            raise GraphValidationError(f"{label} is not a regular file: {path}")
        content = self._read_path_bytes(resolved, source=False, label=label)
        return _LoadedMapping(
            document=self._parse_yaml_mapping(content, resolved, source=False),
            source=self._project_manifest_entry(source_kind, resolved, content),
        )

    def _load_package_mapping(
        self,
        relative_path: str,
        *,
        source_kind: _SourceKind,
        label: str,
    ) -> _LoadedMapping:
        resource, content = self._read_package_source(relative_path, label=label)
        return _LoadedMapping(
            document=self._parse_yaml_mapping(content, resource, source=False),
            source=self._package_manifest_entry(source_kind, relative_path, content),
        )

    def _load_package_source(
        self,
        relative_path: str,
        *,
        source_kind: _SourceKind,
        label: str,
    ) -> SourceManifestEntry:
        _, content = self._read_package_source(relative_path, label=label)
        return self._package_manifest_entry(source_kind, relative_path, content)

    @staticmethod
    def _read_package_source(
        relative_path: str,
        *,
        label: str,
    ) -> tuple[Traversable, bytes]:
        resource = files("ai_engineering_harness.defaults").joinpath(
            *PurePosixPath(relative_path).parts
        )
        try:
            if not resource.is_file():
                raise OSError("resource is not a regular file")
            content = resource.read_bytes()
            content.decode("utf-8")
        except (OSError, UnicodeError) as exc:
            raise GraphValidationError(f"cannot read packaged {label}: {exc}") from exc
        return resource, content

    @staticmethod
    def _read_path_bytes(path: Path, *, source: bool, label: str) -> bytes:
        error_type = GraphSourceError if source else GraphValidationError
        try:
            content = path.read_bytes()
            content.decode("utf-8")
        except (OSError, UnicodeError) as exc:
            raise error_type(f"cannot read {label} {path}: {exc}") from exc
        return content

    @staticmethod
    def _parse_yaml_mapping(
        content: bytes,
        location: object,
        *,
        source: bool,
    ) -> dict[str, Any]:
        error_type = GraphSourceError if source else GraphValidationError
        try:
            loaded = yaml.safe_load(content.decode("utf-8"))
        except (UnicodeError, yaml.YAMLError) as exc:
            raise error_type(f"cannot read YAML object {location}: {exc}") from exc
        if not isinstance(loaded, Mapping):
            raise error_type(f"YAML document must be a non-empty object: {location}")
        return cast(dict[str, Any], dict(loaded))

    def _project_manifest_entry(
        self,
        source_kind: _SourceKind,
        path: Path,
        content: bytes,
    ) -> SourceManifestEntry:
        try:
            relative = path.relative_to(self.project_root).as_posix()
        except ValueError as exc:
            raise GraphValidationError(f"manifest source escapes project root: {path}") from exc
        return SourceManifestEntry(
            source_kind=source_kind,
            source_id=f"project://{relative}",
            content_digest=self._content_digest(content),
        )

    @staticmethod
    def _package_manifest_entry(
        source_kind: _SourceKind,
        relative_path: str,
        content: bytes,
    ) -> SourceManifestEntry:
        return SourceManifestEntry(
            source_kind=source_kind,
            source_id=f"{_PACKAGE_SOURCE_PREFIX}{relative_path}",
            content_digest=GraphCompiler._content_digest(content),
        )

    @staticmethod
    def _content_digest(content: bytes) -> str:
        return f"sha256:{hashlib.sha256(content).hexdigest()}"

    def _atomic_write(self, output_file: Path, content: bytes) -> None:
        descriptor: int | None = None
        temp_path: Path | None = None
        try:
            descriptor, raw_temp_path = tempfile.mkstemp(
                prefix=f".{output_file.name}.",
                suffix=".tmp",
                dir=self.output_dir,
            )
            temp_path = Path(raw_temp_path)
            with os.fdopen(descriptor, "wb") as stream:
                descriptor = None
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_path, output_file)
            temp_path = None
            self._fsync_output_directory()
        finally:
            if descriptor is not None:
                os.close(descriptor)
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

    def _fsync_output_directory(self) -> None:
        if os.name == "nt":
            return
        descriptor = os.open(self.output_dir, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    @classmethod
    def _validate_workflow_identity(cls, graph_name: str, workflow_name: str | None) -> None:
        cls._validate_workflow_name(graph_name)
        if workflow_name is None:
            return
        cls._validate_workflow_name(workflow_name)
        if workflow_name != graph_name:
            raise GraphValidationError(
                f"workflow name {workflow_name!r} does not match graph name {graph_name!r}"
            )

    @staticmethod
    def _validate_workflow_name(workflow_name: str) -> None:
        if not isinstance(workflow_name, str) or not _WORKFLOW_NAME_RE.fullmatch(workflow_name):
            raise GraphValidationError(
                "workflow name must match [A-Za-z0-9][A-Za-z0-9._-]*"
            )


__all__ = [
    "GraphCompiler",
    "GraphCompilerError",
    "GraphSourceError",
    "GraphValidationError",
    "GraphWriteError",
]
