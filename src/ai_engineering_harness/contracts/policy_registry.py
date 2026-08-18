"""Fail-closed registry and resolver for F1.3 policies, roles, and tool capabilities."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from importlib.resources import files
from importlib.resources.abc import Traversable
from typing import Any, cast

import yaml
from pydantic import BaseModel, ValidationError

from ai_engineering_harness.versioning import POLICY_SCHEMA_VERSION

from .graph import AgentNodeSpec, DeterministicNodeSpec, GraphSpec, ToolPermissionSpec
from .policies import (
    AgentRoleSpec,
    ContextSufficiencyPolicySpec,
    EffectiveNodeToolPolicySpec,
    IncidentResponsePolicySpec,
    InvalidPolicyReferenceError,
    InvalidPolicySchemaError,
    KnowledgeSyncPolicySpec,
    PolicyDocument,
    PolicyNotFoundError,
    PolicyRegistryError,
    ProductionHealthPolicySpec,
    ResolvedPolicySpec,
    RetryCostPolicySpec,
    RoleNotFoundError,
    SandboxPolicySpec,
    ToolGovernancePolicySpec,
    ToolNotFoundError,
    ToolRegistrySpec,
    UnauthorizedToolError,
    VerificationPolicySpec,
)

_TOOL_POLICY_REF = "policies/tool_policy.yaml"
_POLICY_MODELS: dict[str, type[BaseModel]] = {
    "policies/context_sufficiency.yaml": ContextSufficiencyPolicySpec,
    "policies/incident_graph.yaml": IncidentResponsePolicySpec,
    "policies/knowledge_sync.yaml": KnowledgeSyncPolicySpec,
    "policies/production_health.yaml": ProductionHealthPolicySpec,
    "policies/retry_cost_policy.yaml": RetryCostPolicySpec,
    "policies/sandbox_policy.yaml": SandboxPolicySpec,
    _TOOL_POLICY_REF: ToolGovernancePolicySpec,
    "policies/verification_policy.yaml": VerificationPolicySpec,
}
_ENVELOPE_FIELDS = frozenset({"policy_id", "policy_schema_version", "definition_version"})


def _load_yaml(resource: Traversable, *, kind: str) -> dict[str, Any]:
    try:
        loaded = yaml.safe_load(resource.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise InvalidPolicySchemaError(f"cannot read {kind}: {exc}") from exc
    if not isinstance(loaded, dict):
        raise InvalidPolicySchemaError(f"{kind} must be a YAML object")
    return cast(dict[str, Any], loaded)


class PolicyRegistry:
    """Resolve only exact packaged policy references and explicit declarative catalogs."""

    def __init__(
        self,
        *,
        policy_documents: Mapping[str, Mapping[str, Any]] | None = None,
        role_documents: Mapping[str, Mapping[str, Any]] | None = None,
        tool_registry_document: Mapping[str, Any] | None = None,
    ) -> None:
        defaults = files("ai_engineering_harness.defaults")
        raw_policies = self._default_policy_documents(defaults)
        if policy_documents is not None:
            self._merge_policy_overrides(raw_policies, policy_documents)

        raw_roles = self._default_role_documents(defaults)
        if role_documents is not None:
            for role_id, document in role_documents.items():
                raw_roles[role_id] = dict(document)

        raw_tools = (
            dict(tool_registry_document)
            if tool_registry_document is not None
            else _load_yaml(defaults.joinpath("tools", "tool_registry.yaml"), kind="tool registry")
        )

        self._policies = self._validate_policies(raw_policies)
        self._roles = self._validate_roles(raw_roles)
        self._tool_registry = cast(
            ToolRegistrySpec,
            self._validate_model(ToolRegistrySpec, raw_tools, "tool registry"),
        )
        self._tools = {tool.id: tool for tool in self._tool_registry.tools}
        self._validate_catalog_consistency()

    @property
    def available_policies(self) -> tuple[str, ...]:
        return tuple(sorted(self._policies))

    @property
    def available_roles(self) -> tuple[str, ...]:
        return tuple(sorted(self._roles))

    @property
    def available_tools(self) -> tuple[str, ...]:
        return tuple(sorted(self._tools))

    def resolve(self, reference: str) -> ResolvedPolicySpec:
        """Resolve one exact reference into a normalized, detached effective view."""
        policy = self._policy_for(reference)
        return self._resolved(reference, policy, self._policy_payload(policy))

    def resolve_many(self, references: Iterable[str]) -> tuple[ResolvedPolicySpec, ...]:
        """Resolve an ordered set, rejecting duplicate references instead of hiding them."""
        normalized = self._validate_reference_sequence(references)
        return tuple(self.resolve(reference) for reference in normalized)

    def resolve_graph(self, graph: GraphSpec) -> tuple[ResolvedPolicySpec, ...]:
        """Resolve a typed graph and calculate its default-deny node tool decisions."""
        references = self._validate_reference_sequence(graph.policies)
        policies = {reference: self._policy_for(reference) for reference in references}
        agent_nodes = [node for node in graph.nodes if isinstance(node, AgentNodeSpec)]
        self._require_tool_policy(agent_nodes, references)
        self._validate_node_policy_references(
            (
                (node.id, node.policy_ref)
                for node in graph.nodes
                if isinstance(node, DeterministicNodeSpec) and node.policy_ref is not None
            ),
            references,
        )
        decisions = tuple(
            self._resolve_node_tools(node.id, node.role, node.tool_permissions)
            for node in agent_nodes
        )
        return self._resolve_effective(references, policies, decisions)

    def resolve_legacy_graph(self, graph_spec: Mapping[str, Any]) -> tuple[ResolvedPolicySpec, ...]:
        """Resolve only F1.3 fields from a legacy graph mapping without claiming topology validation."""
        raw_references = graph_spec.get("policies", [])
        if not isinstance(raw_references, (list, tuple)):
            raise InvalidPolicyReferenceError("legacy graph policies must be a list")
        references = self._validate_reference_sequence(raw_references)
        policies = {reference: self._policy_for(reference) for reference in references}

        raw_nodes = graph_spec.get("nodes", [])
        if not isinstance(raw_nodes, list):
            raise InvalidPolicySchemaError("legacy graph nodes must be a list")

        agent_nodes: list[tuple[str, str, tuple[ToolPermissionSpec, ...]]] = []
        policy_references: list[tuple[str, object]] = []
        for index, raw_node in enumerate(raw_nodes):
            if not isinstance(raw_node, dict):
                raise InvalidPolicySchemaError("every legacy graph node must be an object")
            node_id = raw_node.get("id", f"node_{index}")
            if not isinstance(node_id, str) or not node_id.strip():
                raise InvalidPolicySchemaError("legacy graph node id must be a non-empty string")
            if "policy_ref" in raw_node:
                policy_references.append((node_id, raw_node["policy_ref"]))
            if "role" not in raw_node:
                continue
            role = raw_node["role"]
            if not isinstance(role, str) or not role.strip():
                raise RoleNotFoundError(f"node {node_id!r} role must be a non-empty string")
            raw_permissions = raw_node.get("tool_permissions", [])
            if not isinstance(raw_permissions, list):
                raise InvalidPolicySchemaError(f"node {node_id!r} tool_permissions must be a list")
            try:
                permissions = tuple(ToolPermissionSpec.model_validate(item) for item in raw_permissions)
            except ValidationError as exc:
                raise InvalidPolicySchemaError(
                    f"node {node_id!r} has invalid tool_permissions: {exc}"
                ) from exc
            agent_nodes.append((node_id, role, permissions))

        self._require_tool_policy(agent_nodes, references)
        self._validate_node_policy_references(policy_references, references)
        decisions = tuple(
            self._resolve_node_tools(node_id, role, permissions)
            for node_id, role, permissions in agent_nodes
        )
        return self._resolve_effective(references, policies, decisions)

    @staticmethod
    def _default_policy_documents(defaults: Traversable) -> dict[str, dict[str, Any]]:
        return {
            reference: _load_yaml(defaults.joinpath(*reference.split("/")), kind=reference)
            for reference in _POLICY_MODELS
        }

    @staticmethod
    def _merge_policy_overrides(
        target: dict[str, dict[str, Any]],
        overrides: Mapping[str, Mapping[str, Any]],
    ) -> None:
        for reference, document in overrides.items():
            if reference not in _POLICY_MODELS:
                raise PolicyNotFoundError(f"policy is not registered: {reference}")
            target[reference] = dict(document)

    @staticmethod
    def _default_role_documents(defaults: Traversable) -> dict[str, dict[str, Any]]:
        agents_root = defaults.joinpath("agents")
        documents: dict[str, dict[str, Any]] = {}
        for directory in agents_root.iterdir():
            if not directory.is_dir() or directory.name.startswith("_"):
                continue
            agent_file = directory.joinpath("agent.yaml")
            if not agent_file.is_file():
                continue
            document = _load_yaml(agent_file, kind=f"agent role {directory.name}")
            documents[directory.name] = document
            prompt_name = document.get("system_prompt_file")
            if not isinstance(prompt_name, str) or not directory.joinpath(prompt_name).is_file():
                raise InvalidPolicySchemaError(
                    f"agent role {directory.name!r} references a missing system prompt"
                )
        return documents

    def _validate_policies(
        self,
        documents: Mapping[str, Mapping[str, Any]],
    ) -> dict[str, PolicyDocument]:
        policies: dict[str, PolicyDocument] = {}
        policy_ids: set[str] = set()
        for reference, model in _POLICY_MODELS.items():
            document = documents.get(reference)
            if document is None:
                raise PolicyNotFoundError(f"policy is not registered: {reference}")
            policy = cast(PolicyDocument, self._validate_model(model, document, reference))
            if policy.policy_schema_version != POLICY_SCHEMA_VERSION:
                raise InvalidPolicySchemaError(
                    f"{reference} policy_schema_version must be {POLICY_SCHEMA_VERSION!r}"
                )
            if policy.policy_id in policy_ids:
                raise InvalidPolicySchemaError(f"policy_id must be unique: {policy.policy_id}")
            policy_ids.add(policy.policy_id)
            policies[reference] = policy
        return policies

    def _validate_roles(
        self,
        documents: Mapping[str, Mapping[str, Any]],
    ) -> dict[str, AgentRoleSpec]:
        roles: dict[str, AgentRoleSpec] = {}
        for directory_name, document in documents.items():
            role = cast(
                AgentRoleSpec,
                self._validate_model(AgentRoleSpec, document, f"agent role {directory_name}"),
            )
            if role.name != directory_name:
                raise InvalidPolicySchemaError(
                    f"agent role name {role.name!r} must match directory {directory_name!r}"
                )
            if role.name in roles:
                raise InvalidPolicySchemaError(f"agent role name must be unique: {role.name}")
            roles[role.name] = role
        return roles

    @staticmethod
    def _validate_model(
        model: type[BaseModel],
        document: Mapping[str, Any],
        label: str,
    ) -> BaseModel:
        try:
            return model.model_validate(dict(document))
        except ValidationError as exc:
            raise InvalidPolicySchemaError(f"invalid {label}: {exc}") from exc

    def _validate_catalog_consistency(self) -> None:
        tool_policy = self._tool_policy()
        policy_roles = set(tool_policy.roles_permissions)
        role_ids = set(self._roles)
        missing_role_policies = sorted(role_ids - policy_roles)
        unknown_policy_roles = sorted(policy_roles - role_ids)
        if missing_role_policies or unknown_policy_roles:
            details: list[str] = []
            if missing_role_policies:
                details.append("roles without policy: " + ", ".join(missing_role_policies))
            if unknown_policy_roles:
                details.append("policy roles without agent: " + ", ".join(unknown_policy_roles))
            raise RoleNotFoundError("; ".join(details))

        known_tools = set(self._tools)
        for role_id, role in self._roles.items():
            permission = tool_policy.roles_permissions[role_id]
            referenced = set(role.allowed_tools) | set(permission.allowed_tools) | set(permission.forbidden_tools)
            missing_tools = sorted(referenced - known_tools)
            if missing_tools:
                raise ToolNotFoundError(
                    f"role {role_id!r} references unregistered tools: {', '.join(missing_tools)}"
                )
            outside_role = sorted(set(permission.allowed_tools) - set(role.allowed_tools))
            if outside_role:
                raise UnauthorizedToolError(
                    f"policy for role {role_id!r} exceeds agent allowed_tools: {', '.join(outside_role)}"
                )

    def _policy_for(self, reference: object) -> PolicyDocument:
        if not isinstance(reference, str) or not reference or reference != reference.strip():
            raise InvalidPolicyReferenceError("policy reference must be a non-empty, trimmed string")
        if reference not in _POLICY_MODELS:
            parts = reference.split("/")
            if (
                len(parts) != 2
                or parts[0] != "policies"
                or not parts[1]
                or any(token in reference for token in ("\\", "..", ":"))
                or not reference.endswith(".yaml")
            ):
                raise InvalidPolicyReferenceError(f"unsafe or malformed policy reference: {reference!r}")
            raise PolicyNotFoundError(f"policy is not registered: {reference}")
        return self._policies[reference]

    def _validate_reference_sequence(self, references: Iterable[object]) -> tuple[str, ...]:
        if isinstance(references, (str, bytes)):
            raise InvalidPolicyReferenceError("policy references must be an iterable, not one string")
        normalized: list[str] = []
        seen: set[str] = set()
        for reference in references:
            self._policy_for(reference)
            assert isinstance(reference, str)
            if reference in seen:
                raise InvalidPolicyReferenceError(f"duplicate policy reference: {reference}")
            seen.add(reference)
            normalized.append(reference)
        return tuple(normalized)

    @staticmethod
    def _require_tool_policy(agent_nodes: Iterable[object], references: tuple[str, ...]) -> None:
        if any(True for _ in agent_nodes) and _TOOL_POLICY_REF not in references:
            raise PolicyNotFoundError(f"agent nodes require {_TOOL_POLICY_REF}")

    def _validate_node_policy_references(
        self,
        node_references: Iterable[tuple[str, object]],
        graph_references: tuple[str, ...],
    ) -> None:
        declared = set(graph_references)
        for node_id, reference in node_references:
            self._policy_for(reference)
            assert isinstance(reference, str)
            if reference not in declared:
                raise InvalidPolicyReferenceError(
                    f"node {node_id!r} policy_ref is not declared in graph.policies: {reference}"
                )

    def _resolve_node_tools(
        self,
        node_id: str,
        role_id: str,
        permissions: tuple[ToolPermissionSpec, ...],
    ) -> EffectiveNodeToolPolicySpec:
        role = self._roles.get(role_id)
        if role is None:
            raise RoleNotFoundError(f"node {node_id!r} references unknown role: {role_id}")
        policy = self._tool_policy().roles_permissions[role_id]
        seen: set[str] = set()
        allowed: set[str] = set()
        denied = set(policy.forbidden_tools)
        for permission in permissions:
            if permission.tool not in self._tools:
                raise ToolNotFoundError(
                    f"node {node_id!r} references unregistered tool: {permission.tool}"
                )
            if permission.tool in seen:
                raise UnauthorizedToolError(
                    f"node {node_id!r} repeats or conflicts on tool: {permission.tool}"
                )
            seen.add(permission.tool)
            if permission.effect == "deny":
                denied.add(permission.tool)
                allowed.discard(permission.tool)
                continue
            if (
                permission.tool not in role.allowed_tools
                or permission.tool not in policy.allowed_tools
                or permission.tool in denied
            ):
                raise UnauthorizedToolError(
                    f"node {node_id!r} is not authorized to allow tool {permission.tool!r}"
                )
            allowed.add(permission.tool)

        return EffectiveNodeToolPolicySpec(
            node_id=node_id,
            role=role_id,
            allowed_tools=tuple(sorted(allowed)),
            denied_tools=tuple(sorted(denied)),
            human_approval_required=policy.human_approval_required,
        )

    def _resolve_effective(
        self,
        references: tuple[str, ...],
        policies: Mapping[str, PolicyDocument],
        decisions: tuple[EffectiveNodeToolPolicySpec, ...],
    ) -> tuple[ResolvedPolicySpec, ...]:
        resolved: list[ResolvedPolicySpec] = []
        for reference in references:
            policy = policies[reference]
            if reference == _TOOL_POLICY_REF:
                used_roles = sorted({decision.role for decision in decisions})
                payload = {
                    "roles": {
                        role_id: {
                            "nodes": [
                                decision.model_dump(mode="json")
                                for decision in decisions
                                if decision.role == role_id
                            ]
                        }
                        for role_id in used_roles
                    }
                }
            else:
                payload = self._policy_payload(policy)
            resolved.append(self._resolved(reference, policy, payload))
        return tuple(resolved)

    @staticmethod
    def _policy_payload(policy: PolicyDocument) -> dict[str, Any]:
        return policy.model_dump(mode="json", exclude=set(_ENVELOPE_FIELDS))

    @staticmethod
    def _resolved(
        reference: str,
        policy: PolicyDocument,
        payload: dict[str, Any],
    ) -> ResolvedPolicySpec:
        return ResolvedPolicySpec(
            requested_reference=reference,
            policy_id=policy.policy_id,
            policy_schema_version=policy.policy_schema_version,
            definition_version=policy.definition_version,
            effective_policy=payload,
        )

    def _tool_policy(self) -> ToolGovernancePolicySpec:
        policy = self._policies[_TOOL_POLICY_REF]
        if not isinstance(policy, ToolGovernancePolicySpec):
            raise InvalidPolicySchemaError("registered tool policy has the wrong schema")
        return policy


__all__ = ["PolicyRegistry", "PolicyRegistryError"]
