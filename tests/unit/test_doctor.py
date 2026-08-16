"""Focused tests for the real, fail-closed F6.4 doctor."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

import httpx
import pytest

import ai_engineering_harness.doctor.components as COMPONENTS
from ai_engineering_harness.core import ConfigResolver
from ai_engineering_harness.doctor.checker import DoctorChecker
from ai_engineering_harness.doctor.components import (
    DisabledMcpProbe,
    GitProbe,
    ProviderProbe,
    PythonToolchainProbe,
    RequiredGatesProbe,
    SerenaMcpProbe,
    StateStorageProbe,
    WorktreePermissionsProbe,
    selected_mcp_probe,
)
from ai_engineering_harness.doctor.probes import (
    DoctorResult,
    HealthProbe,
    ProbeStage,
    ProbeStageResult,
    ProbeStatus,
)
from ai_engineering_harness.doctor.report import DoctorReport
from ai_engineering_harness.tools.adapters import SerenaCapabilities


class _HealthyProbe(HealthProbe):
    component_id = "test-component"
    component_name = "Test component"

    def configured(self) -> ProbeStageResult:
        return self.passed(ProbeStage.CONFIGURED, "TEST_CONFIGURED", "Configured.")

    def installed(self) -> ProbeStageResult:
        return self.passed(ProbeStage.INSTALLED, "TEST_INSTALLED", "Installed.")

    def reachable(self) -> ProbeStageResult:
        return self.passed(ProbeStage.REACHABLE, "TEST_REACHABLE", "Reachable.")

    def authenticated(self) -> ProbeStageResult:
        return self.not_applicable(ProbeStage.AUTHENTICATED, "TEST_AUTH_NA", "No credential required.")

    def capable(self) -> ProbeStageResult:
        return self.passed(ProbeStage.CAPABLE, "TEST_CAPABLE", "Capable.")

    def healthy(self) -> ProbeStageResult:
        return self.passed(ProbeStage.HEALTHY, "TEST_HEALTHY", "Healthy.")


class _FailingProbe(_HealthyProbe):
    def reachable(self) -> ProbeStageResult:
        return self.failed(ProbeStage.REACHABLE, "TEST_UNREACHABLE", "Unreachable.")

    def authenticated(self) -> ProbeStageResult:  # pragma: no cover - must be skipped
        raise AssertionError("downstream stage executed")


class _ExplodingProbe(_HealthyProbe):
    def installed(self) -> ProbeStageResult:
        raise RuntimeError("doctor-secret-canary")


def _local_provider_config(*, model: str = "llama3") -> dict[str, object]:
    return {
        "models": {
            "providers": {
                "local": {
                    "adapter": "local",
                    "model": model,
                    "base_url": "http://doctor.invalid/v1",
                }
            },
            "routing": {"primary_provider": "local", "fallback_providers": []},
        }
    }


def _openai_provider_config() -> dict[str, object]:
    return {
        "models": {
            "providers": {
                "openai": {
                    "adapter": "openai",
                    "model": "gpt-doctor",
                    "base_url": "https://doctor.invalid/v1",
                    "api_key_env": "DOCTOR_API_KEY",
                }
            },
            "routing": {"primary_provider": "openai", "fallback_providers": []},
        }
    }


def _fake_runner(
    argv: Sequence[str],
    *,
    cwd: Path,
    environment: Mapping[str, str],
    timeout_seconds: float,
) -> subprocess.CompletedProcess[str]:
    del environment, timeout_seconds
    arguments = tuple(argv[1:])
    if arguments == ("--version",):
        executable = Path(argv[0]).name.casefold()
        output = "Python 3.12.0\n" if "python" in executable else "git version 2.45.0\n"
    elif arguments == ("rev-parse", "--is-inside-work-tree"):
        output = "true\n"
    elif arguments == ("rev-parse", "--show-toplevel"):
        output = f"{cwd}\n"
    elif arguments == ("worktree", "list", "--porcelain"):
        output = f"worktree {cwd}\n"
    else:
        output = ""
    return subprocess.CompletedProcess(list(argv), 0, output, "")


def _write_workflow(project_root: Path) -> None:
    graph_dir = project_root / ".harness" / "graphs" / "specs"
    graph_dir.mkdir(parents=True)
    (graph_dir / "new-feature.yaml").write_text(
        """graph:
  name: new-feature
  graph_schema_version: "1.0"
  definition_version: "1.0.0"
  entrypoint: verify
  status: stable
nodes:
  - id: verify
    type: deterministic
    executor: deterministic_gate
    gate_name: unit_test
    on_success: completed
    on_failure: failed
terminal_states:
  - id: completed
    outcome: success
  - id: failed
    outcome: failure
policies:
  - policies/verification_policy.yaml
contracts: []
""",
        encoding="utf-8",
    )
    (project_root / "pyproject.toml").write_text(
        """[build-system]
requires = ["setuptools"]
build-backend = "setuptools.build_meta"

[project]
name = "doctor-fixture"
version = "0.0.0"
dependencies = ["pytest", "ruff", "mypy", "build"]

[tool.pytest.ini_options]

[tool.ruff]

[tool.mypy]
""",
        encoding="utf-8",
    )


def test_health_probe_uses_canonical_order_and_fail_closed_short_circuit() -> None:
    result = _FailingProbe().probe()

    assert tuple(stage.stage for stage in result.stages) == tuple(ProbeStage)
    assert tuple(stage.status for stage in result.stages) == (
        ProbeStatus.PASS,
        ProbeStatus.PASS,
        ProbeStatus.FAIL,
        ProbeStatus.SKIPPED,
        ProbeStatus.SKIPPED,
        ProbeStatus.SKIPPED,
    )
    assert result.is_healthy is False


def test_unexpected_probe_exception_is_redacted_and_blocks_downstream() -> None:
    result = _ExplodingProbe().probe()
    rendered = DoctorReport.to_json(DoctorResult.build((result,), workflow=None))

    assert result.stages[1].code == "UNEXPECTED_PROBE_ERROR"
    assert all(stage.status is ProbeStatus.SKIPPED for stage in result.stages[2:])
    assert "doctor-secret-canary" not in rendered


def test_disabled_optional_mcp_is_explicitly_not_applicable() -> None:
    result = DisabledMcpProbe().probe()

    assert result.mandatory is False
    assert result.is_healthy is True
    assert all(stage.status is ProbeStatus.NOT_APPLICABLE for stage in result.stages)


def test_git_probe_fails_installed_when_path_is_empty(tmp_path: Path) -> None:
    result = GitProbe(tmp_path, environment={"PATH": ""}).probe()

    assert result.stages[1].status is ProbeStatus.FAIL
    assert result.stages[1].code == "GIT_NOT_INSTALLED"
    assert all(stage.status is ProbeStatus.SKIPPED for stage in result.stages[2:])


def test_python_probe_runs_real_read_only_smoke(tmp_path: Path) -> None:
    result = PythonToolchainProbe(
        tmp_path,
        environment=os.environ,
        executable=sys.executable,
    ).probe()

    assert result.is_healthy is True
    assert result.stages[3].status is ProbeStatus.NOT_APPLICABLE
    assert result.stages[-1].code == "PYTHON_HEALTHY"


def test_provider_probe_observes_configured_model_via_read_only_discovery() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/v1/models"
        return httpx.Response(200, json={"data": [{"id": "llama3"}]})

    result = ProviderProbe(
        _local_provider_config(),
        environment={},
        transport=httpx.MockTransport(handler),
    ).probe()

    assert result.is_healthy is True
    assert result.stages[3].status is ProbeStatus.NOT_APPLICABLE
    assert result.stages[4].code == "PROVIDER_CAPABLE"


def test_provider_auth_failure_never_exposes_credential() -> None:
    canary = "doctor-secret-canary"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == f"Bearer {canary}"
        return httpx.Response(401, json={"error": "rejected"})

    result = ProviderProbe(
        _openai_provider_config(),
        environment={"DOCTOR_API_KEY": canary},
        transport=httpx.MockTransport(handler),
    ).probe()
    rendered = DoctorReport.to_json(DoctorResult.build((result,), workflow=None))

    assert result.stages[3].code == "PROVIDER_AUTH_REJECTED"
    assert result.is_healthy is False
    assert canary not in rendered


def test_provider_missing_credential_fails_authenticated_stage() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"data": [{"id": "gpt-doctor"}]})
    )
    result = ProviderProbe(
        _openai_provider_config(),
        environment={},
        transport=transport,
    ).probe()

    assert result.stages[3].code == "PROVIDER_CREDENTIAL_MISSING"
    assert result.stages[4].status is ProbeStatus.SKIPPED


def test_provider_transport_failure_stops_before_authentication() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("doctor-secret-canary", request=request)

    result = ProviderProbe(
        _local_provider_config(),
        environment={},
        transport=httpx.MockTransport(handler),
    ).probe()

    assert result.stages[2].code == "PROVIDER_UNREACHABLE"
    assert result.stages[3].status is ProbeStatus.SKIPPED
    assert "doctor-secret-canary" not in DoctorReport.to_json(
        DoctorResult.build((result,), workflow=None)
    )


def test_invalid_provider_configuration_fails_configured_stage() -> None:
    result = ProviderProbe({}, environment={}).probe()

    assert result.stages[0].code == "PROVIDER_CONFIG_INVALID"
    assert all(stage.status is ProbeStatus.SKIPPED for stage in result.stages[1:])


def test_provider_missing_model_fails_capability() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"data": [{"id": "another-model"}]})
    )
    result = ProviderProbe(
        _local_provider_config(),
        environment={},
        transport=transport,
    ).probe()

    assert result.stages[4].code == "PROVIDER_MODEL_MISSING"
    assert result.stages[5].status is ProbeStatus.SKIPPED


def test_serena_probe_uses_adapter_probe_without_editing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(COMPONENTS, "_find_executable", lambda alias, environment: Path(sys.executable))
    calls: list[str] = []

    class Adapter:
        def probe(self) -> SerenaCapabilities:
            calls.append("probe")
            return SerenaCapabilities(
                transport="stdio",
                protocol_version="2025-03-26",
                server_name="serena-test",
                tools=("find_symbol",),
            )

    def factory(path_guard, configuration, authorization):
        assert path_guard.authorized_root == tmp_path.resolve()
        assert configuration.transport.value == "stdio"
        assert authorization is None
        return Adapter()

    result = SerenaMcpProbe(
        tmp_path.resolve(),
        {"transport": "stdio", "command": "serena-test"},
        environment={"PATH": os.environ.get("PATH", "")},
        adapter_factory=factory,
    ).probe()

    assert result.is_healthy is True
    assert calls == ["probe"]
    assert result.stages[4].code == "SERENA_CAPABLE"


def test_enabled_mcp_without_operational_adapter_fails_closed(tmp_path: Path) -> None:
    probe = selected_mcp_probe(
        tmp_path,
        {"project": {"mcp": {"codebase_memory": {"enabled": True}}}},
        environment={},
    )
    result = probe.probe()

    assert result.stages[0].code == "MCP_ADAPTER_UNSUPPORTED"
    assert result.is_healthy is False


def test_malformed_mcp_configuration_is_not_treated_as_disabled(tmp_path: Path) -> None:
    result = selected_mcp_probe(
        tmp_path,
        {"project": {"mcp": {"serena": {"enabled": "true"}}}},
        environment={},
    ).probe()

    assert result.stages[0].code == "MCP_CONFIG_INVALID"
    assert result.is_healthy is False


def test_state_storage_missing_root_fails_reachable(tmp_path: Path) -> None:
    result = StateStorageProbe(tmp_path).probe()

    assert result.stages[2].code == "STATE_ROOT_MISSING"
    assert result.stages[3].status is ProbeStatus.SKIPPED


def test_state_storage_insufficient_permission_fails_capability(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / ".harness" / "state" / "executions").mkdir(parents=True)
    monkeypatch.setattr(COMPONENTS.os, "access", lambda path, mode: False)
    result = StateStorageProbe(tmp_path).probe()

    assert result.stages[4].code == "STATE_PERMISSION_DENIED"
    assert result.stages[5].status is ProbeStatus.SKIPPED


def test_worktree_probe_rejects_base_inside_repository(tmp_path: Path) -> None:
    result = WorktreePermissionsProbe(
        tmp_path.resolve(),
        environment={},
        external_base=tmp_path / "nested-worktrees",
    ).probe()

    assert result.stages[0].code == "WORKTREE_PATH_UNSAFE"
    assert all(stage.status is ProbeStatus.SKIPPED for stage in result.stages[1:])


def test_worktree_probe_detects_insufficient_external_permission(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    external_base = tmp_path / "external"
    project_root.mkdir()
    external_base.mkdir()
    monkeypatch.setattr(COMPONENTS, "_find_executable", lambda alias, environment: Path(sys.executable))
    monkeypatch.setattr(COMPONENTS.os, "access", lambda path, mode: False)
    result = WorktreePermissionsProbe(
        project_root.resolve(),
        environment={},
        external_base=external_base,
        runner=_fake_runner,
    ).probe()

    assert result.stages[5].code == "WORKTREE_PERMISSION_DENIED"
    assert result.is_healthy is False


def test_required_gates_resolve_canonical_commands_without_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_workflow(tmp_path)
    monkeypatch.setattr(COMPONENTS.importlib.util, "find_spec", lambda name: object())

    result = RequiredGatesProbe(
        tmp_path,
        "new-feature",
        environment={"PATH": os.environ.get("PATH", "")},
    ).probe()

    assert result.is_healthy is True
    assert result.stages[4].code == "WORKFLOW_GATES_CAPABLE"
    assert result.stages[5].code == "GATES_HEALTHY"


def test_required_gates_fail_when_workflow_spec_is_missing(tmp_path: Path) -> None:
    result = RequiredGatesProbe(tmp_path, "new-feature", environment={}).probe()

    assert result.mandatory is True
    assert result.stages[0].code == "WORKFLOW_SPEC_MISSING"
    assert result.is_healthy is False


def test_required_gates_fail_when_required_tool_is_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_workflow(tmp_path)

    def find_spec(name: str):
        return None if name == "mypy" else object()

    monkeypatch.setattr(COMPONENTS.importlib.util, "find_spec", find_spec)
    result = RequiredGatesProbe(tmp_path, "new-feature", environment={}).probe()

    assert result.stages[5].code == "GATE_PREREQUISITE_MISSING"
    assert result.is_healthy is False


def test_checker_composes_seven_real_component_classes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / ".harness" / "state" / "executions").mkdir(parents=True)
    config = ConfigResolver(tmp_path).resolve()
    git_executable = tmp_path / "git.exe"
    git_executable.write_text("test executable", encoding="utf-8")
    git_executable.chmod(0o755)
    monkeypatch.setattr(COMPONENTS, "_find_executable", lambda alias, environment: git_executable)
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"data": [{"id": "llama3"}]})
    )
    result = DoctorChecker(
        config=config,
        project_root=tmp_path,
        environment={
            "PATH": os.environ.get("PATH", ""),
            "LOCALAPPDATA": os.fspath(tmp_path.parent / "localappdata"),
        },
        runner=_fake_runner,
        provider_transport=transport,
    ).check()

    assert tuple(component.component_id for component in result.components) == (
        "git",
        "python-toolchain",
        "selected-provider",
        "selected-mcp",
        "state-storage",
        "worktree-permissions",
        "required-gates",
    )
    assert result.is_healthy is True


def test_json_report_is_versioned_parseable_and_structurally_deterministic() -> None:
    report = DoctorResult.build((_HealthyProbe().probe(),), workflow="new-feature")
    first = DoctorReport.to_json(report)
    second = DoctorReport.to_json(report)

    assert first == second
    payload = json.loads(first)
    assert payload["schema_version"] == "1.0"
    assert payload["status"] == "HEALTHY"
    assert payload["workflow"] == "new-feature"
    assert [stage["stage"] for stage in payload["components"][0]["stages"]] == [
        stage.value for stage in ProbeStage
    ]
