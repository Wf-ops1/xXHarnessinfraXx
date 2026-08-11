"""Regression tests for independent package and serialized-schema versions."""

import importlib.resources
from importlib.resources.abc import Traversable
from typing import Any

import yaml

from ai_engineering_harness.versioning import (
    ARTIFACT_SCHEMA_VERSION,
    GRAPH_SCHEMA_VERSION,
    POLICY_SCHEMA_VERSION,
)

DEFAULTS = importlib.resources.files("ai_engineering_harness.defaults")


def test_compiled_artifact_schema_version_is_exactly_2_0() -> None:
    assert ARTIFACT_SCHEMA_VERSION == "2.0"


def _load_yaml(resource: Traversable) -> dict[str, Any]:
    loaded = yaml.safe_load(resource.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def test_default_graph_versions_use_separate_namespaces() -> None:
    graph_resources = sorted(DEFAULTS.joinpath("graphs").iterdir(), key=lambda resource: resource.name)

    assert graph_resources
    for resource in graph_resources:
        if resource.name.endswith(".yaml"):
            graph_metadata = _load_yaml(resource)["graph"]
            assert graph_metadata["graph_schema_version"] == GRAPH_SCHEMA_VERSION
            assert graph_metadata["definition_version"] == "3.2.0"
            assert "version" not in graph_metadata


def test_default_policy_versions_use_separate_namespaces() -> None:
    policy_resources = sorted(DEFAULTS.joinpath("policies").iterdir(), key=lambda resource: resource.name)

    assert policy_resources
    for resource in policy_resources:
        if resource.name.endswith(".yaml"):
            policy = _load_yaml(resource)
            assert policy["policy_schema_version"] == POLICY_SCHEMA_VERSION
            expected = "3.3.0" if resource.name == "retry_cost_policy.yaml" else "3.2.0"
            assert policy["definition_version"] == expected
            assert "version" not in policy
