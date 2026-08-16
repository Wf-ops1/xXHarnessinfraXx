"""Concrete read-only component probes used by ``harness doctor``."""

from __future__ import annotations

import importlib.util
import os
import shutil
import socket
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit

import httpx
import yaml

from ai_engineering_harness.contracts import GraphSpec, PolicyRegistry
from ai_engineering_harness.contracts.policies import RequiredGateSpec
from ai_engineering_harness.core.detector import StackDetector
from ai_engineering_harness.doctor.probes import HealthProbe, ProbeStage, ProbeStageResult
from ai_engineering_harness.models.registry import ProviderConfiguration
from ai_engineering_harness.models.router import ModelsConfiguration
from ai_engineering_harness.persistence import AtomicFileStateStorage
from ai_engineering_harness.security import (
    PathGuard,
    SecretGrant,
    TrustAuthorization,
    TrustBoundaryEvaluator,
)
from ai_engineering_harness.tools.adapters import (
    SerenaAdapter,
    SerenaCapabilities,
    SerenaMcpConfiguration,
    SerenaTransport,
)
from ai_engineering_harness.verification.evaluator import VerificationEvaluator


class CommandRunner(Protocol):
    def __call__(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        environment: Mapping[str, str],
        timeout_seconds: float,
    ) -> subprocess.CompletedProcess[str]: ...


class SerenaProbeAdapter(Protocol):
    def probe(self) -> SerenaCapabilities: ...


SerenaAdapterFactory = Callable[
    [PathGuard, SerenaMcpConfiguration, TrustAuthorization | None],
    SerenaProbeAdapter,
]


def run_command(
    argv: Sequence[str],
    *,
    cwd: Path,
    environment: Mapping[str, str],
    timeout_seconds: float,
) -> subprocess.CompletedProcess[str]:
    """Execute one bounded, non-shell, read-only diagnostic command."""

    return subprocess.run(
        list(argv),
        cwd=cwd,
        env=dict(environment),
        check=False,
        shell=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_seconds,
    )


def _environment_value(environment: Mapping[str, str], name: str) -> str | None:
    return next(
        (value for key, value in environment.items() if key.casefold() == name.casefold()),
        None,
    )


def _subprocess_environment(environment: Mapping[str, str]) -> dict[str, str]:
    allowed = {"path", "systemroot", "pythonpath", "virtual_env", "pathext"}
    return {
        name: value
        for name, value in environment.items()
        if name.casefold() in allowed and isinstance(value, str) and "\x00" not in value
    }


def _find_executable(alias: str, environment: Mapping[str, str]) -> Path | None:
    path_value = _environment_value(environment, "PATH")
    if path_value is None or not path_value.strip():
        return None
    found = shutil.which(alias, path=path_value)
    if found is None:
        return None
    try:
        resolved = Path(found).resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        return None
    if not resolved.is_file() or not os.access(resolved, os.X_OK):
        return None
    return resolved


class UnavailableProbe(HealthProbe):
    """Represent a configuration/composition failure without leaking its exception."""

    def __init__(
        self,
        component_id: str,
        component_name: str,
        *,
        code: str,
        message: str,
        mandatory: bool = True,
    ) -> None:
        self.component_id = component_id
        self.component_name = component_name
        self.mandatory = mandatory
        self._code = code
        self._message = message

    def configured(self) -> ProbeStageResult:
        return self.failed(ProbeStage.CONFIGURED, self._code, self._message)

    def installed(self) -> ProbeStageResult:
        return self.passed(ProbeStage.INSTALLED, "UNREACHABLE_STAGE", "Unreachable stage.")

    reachable = installed
    authenticated = installed
    capable = installed
    healthy = installed


class GitProbe(HealthProbe):
    component_id = "git"
    component_name = "Git CLI"

    def __init__(
        self,
        project_root: Path,
        *,
        environment: Mapping[str, str],
        runner: CommandRunner = run_command,
        timeout_seconds: float = 5.0,
    ) -> None:
        self.project_root = project_root
        self.environment = dict(environment)
        self.runner = runner
        self.timeout_seconds = timeout_seconds
        self.executable: Path | None = None

    def configured(self) -> ProbeStageResult:
        if not self.project_root.is_dir():
            return self.failed(ProbeStage.CONFIGURED, "GIT_ROOT_INVALID", "Repository root is invalid.")
        return self.passed(ProbeStage.CONFIGURED, "GIT_ROOT_CONFIGURED", "Repository root is configured.")

    def installed(self) -> ProbeStageResult:
        self.executable = _find_executable("git", self.environment)
        if self.executable is None:
            return self.failed(ProbeStage.INSTALLED, "GIT_NOT_INSTALLED", "Git executable was not found.")
        return self.passed(ProbeStage.INSTALLED, "GIT_INSTALLED", "Git executable was found.")

    def _git(self, *arguments: str) -> subprocess.CompletedProcess[str] | None:
        if self.executable is None:
            return None
        try:
            return self.runner(
                (os.fspath(self.executable), *arguments),
                cwd=self.project_root,
                environment={
                    **_subprocess_environment(self.environment),
                    "GIT_TERMINAL_PROMPT": "0",
                },
                timeout_seconds=self.timeout_seconds,
            )
        except (OSError, subprocess.SubprocessError, ValueError):
            return None

    def reachable(self) -> ProbeStageResult:
        result = self._git("--version")
        if result is None or result.returncode != 0 or not result.stdout.startswith("git version "):
            return self.failed(ProbeStage.REACHABLE, "GIT_UNREACHABLE", "Git version probe failed.")
        return self.passed(ProbeStage.REACHABLE, "GIT_REACHABLE", "Git process responded to a version probe.")

    def authenticated(self) -> ProbeStageResult:
        return self.not_applicable(
            ProbeStage.AUTHENTICATED,
            "GIT_AUTH_NOT_APPLICABLE",
            "Local read-only Git inspection requires no credential.",
        )

    def capable(self) -> ProbeStageResult:
        result = self._git("rev-parse", "--is-inside-work-tree")
        if result is None or result.returncode != 0 or result.stdout.strip() != "true":
            return self.failed(ProbeStage.CAPABLE, "GIT_REPOSITORY_INVALID", "Root is not a Git worktree.")
        return self.passed(ProbeStage.CAPABLE, "GIT_REPOSITORY_CAPABLE", "Git recognized the repository worktree.")

    def healthy(self) -> ProbeStageResult:
        result = self._git("worktree", "list", "--porcelain")
        if result is None or result.returncode != 0 or not result.stdout.strip():
            return self.failed(ProbeStage.HEALTHY, "GIT_WORKTREE_SMOKE_FAILED", "Git worktree inspection failed.")
        return self.passed(ProbeStage.HEALTHY, "GIT_HEALTHY", "Read-only Git worktree smoke completed.")


class PythonToolchainProbe(HealthProbe):
    component_id = "python-toolchain"
    component_name = "Python/toolchain"

    def __init__(
        self,
        project_root: Path,
        *,
        environment: Mapping[str, str],
        runner: CommandRunner = run_command,
        executable: str | None = None,
        timeout_seconds: float = 5.0,
    ) -> None:
        self.project_root = project_root
        self.environment = dict(environment)
        self.runner = runner
        self.executable_input = sys.executable if executable is None else executable
        self.executable: Path | None = None
        self.timeout_seconds = timeout_seconds

    def configured(self) -> ProbeStageResult:
        if not self.executable_input or "\x00" in self.executable_input:
            return self.failed(ProbeStage.CONFIGURED, "PYTHON_NOT_CONFIGURED", "Python executable is not configured.")
        return self.passed(ProbeStage.CONFIGURED, "PYTHON_CONFIGURED", "Current Python executable is configured.")

    def installed(self) -> ProbeStageResult:
        try:
            self.executable = Path(self.executable_input).resolve(strict=True)
        except (OSError, RuntimeError, ValueError):
            self.executable = None
        if self.executable is None or not self.executable.is_file() or not os.access(self.executable, os.X_OK):
            return self.failed(ProbeStage.INSTALLED, "PYTHON_NOT_INSTALLED", "Python executable is unavailable.")
        return self.passed(ProbeStage.INSTALLED, "PYTHON_INSTALLED", "Python executable was found.")

    def _python(self, *arguments: str) -> subprocess.CompletedProcess[str] | None:
        if self.executable is None:
            return None
        try:
            return self.runner(
                (os.fspath(self.executable), *arguments),
                cwd=self.project_root,
                environment=_subprocess_environment(self.environment),
                timeout_seconds=self.timeout_seconds,
            )
        except (OSError, subprocess.SubprocessError, ValueError):
            return None

    def reachable(self) -> ProbeStageResult:
        result = self._python("--version")
        if result is None or result.returncode != 0 or "Python " not in (result.stdout + result.stderr):
            return self.failed(ProbeStage.REACHABLE, "PYTHON_UNREACHABLE", "Python version probe failed.")
        return self.passed(ProbeStage.REACHABLE, "PYTHON_REACHABLE", "Python process responded to a version probe.")

    def authenticated(self) -> ProbeStageResult:
        return self.not_applicable(
            ProbeStage.AUTHENTICATED,
            "PYTHON_AUTH_NOT_APPLICABLE",
            "Local Python inspection requires no credential.",
        )

    def capable(self) -> ProbeStageResult:
        version = sys.version_info
        if not ((3, 11) <= version[:2] < (3, 15)):
            return self.failed(ProbeStage.CAPABLE, "PYTHON_VERSION_UNSUPPORTED", "Python version is outside the supported range.")
        if importlib.util.find_spec("ai_engineering_harness") is None:
            return self.failed(ProbeStage.CAPABLE, "HARNESS_PACKAGE_MISSING", "Harness package cannot be imported.")
        return self.passed(ProbeStage.CAPABLE, "PYTHON_CAPABLE", "Python version and Harness package are supported.")

    def healthy(self) -> ProbeStageResult:
        result = self._python("-c", "import ai_engineering_harness")
        if result is None or result.returncode != 0:
            return self.failed(ProbeStage.HEALTHY, "PYTHON_IMPORT_SMOKE_FAILED", "Harness import smoke failed.")
        return self.passed(ProbeStage.HEALTHY, "PYTHON_HEALTHY", "Read-only Harness import smoke completed.")


class ProviderProbe(HealthProbe):
    component_id = "selected-provider"
    component_name = "Selected provider"

    def __init__(
        self,
        configuration: Mapping[str, object],
        *,
        environment: Mapping[str, str],
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.configuration = configuration
        self.environment = dict(environment)
        self.transport = transport
        self.provider_id: str | None = None
        self.spec: ProviderConfiguration | None = None
        self.response: httpx.Response | None = None
        self.secret_available = False
        self.observed_models: tuple[str, ...] = ()

    def configured(self) -> ProbeStageResult:
        try:
            raw_models = self.configuration.get("models")
            models = ModelsConfiguration.model_validate(raw_models)
            self.provider_id = models.routing.primary_provider
            self.spec = models.providers[self.provider_id]
        except (KeyError, TypeError, ValueError):
            return self.failed(ProbeStage.CONFIGURED, "PROVIDER_CONFIG_INVALID", "Selected provider configuration is invalid.")
        return self.passed(ProbeStage.CONFIGURED, "PROVIDER_CONFIGURED", "Selected provider configuration is valid.")

    def installed(self) -> ProbeStageResult:
        if self.spec is None:
            return self.failed(ProbeStage.INSTALLED, "PROVIDER_SPEC_MISSING", "Provider specification is unavailable.")
        if self.spec.adapter == "anthropic":
            return self.failed(ProbeStage.INSTALLED, "PROVIDER_ADAPTER_UNSUPPORTED", "Selected provider adapter is not operational.")
        return self.passed(ProbeStage.INSTALLED, "PROVIDER_ADAPTER_INSTALLED", "Selected HTTP provider adapter is installed.")

    def _base_url(self) -> str | None:
        if self.spec is None:
            return None
        if self.spec.base_url is not None:
            return self.spec.base_url.rstrip("/")
        if self.spec.adapter == "openai":
            return "https://api.openai.com/v1"
        if self.spec.adapter == "local":
            return "http://127.0.0.1:11434/v1"
        return None

    def reachable(self) -> ProbeStageResult:
        if self.spec is None:
            return self.failed(ProbeStage.REACHABLE, "PROVIDER_SPEC_MISSING", "Provider specification is unavailable.")
        base_url = self._base_url()
        if base_url is None:
            return self.failed(ProbeStage.REACHABLE, "PROVIDER_ENDPOINT_INVALID", "Provider endpoint is unavailable.")
        headers: dict[str, str] = {}
        if self.spec.api_key_env is not None:
            secret = _environment_value(self.environment, self.spec.api_key_env)
            self.secret_available = bool(secret)
            if secret:
                headers["Authorization"] = f"Bearer {secret}"
        try:
            with httpx.Client(
                transport=self.transport,
                timeout=min(self.spec.timeout_seconds, 10.0),
                follow_redirects=False,
                trust_env=False,
            ) as client:
                self.response = client.get(f"{base_url}/models", headers=headers)
        except (httpx.HTTPError, OSError, ValueError):
            return self.failed(ProbeStage.REACHABLE, "PROVIDER_UNREACHABLE", "Provider discovery endpoint is unreachable.")
        return self.passed(ProbeStage.REACHABLE, "PROVIDER_REACHABLE", "Provider discovery endpoint responded.")

    def authenticated(self) -> ProbeStageResult:
        if self.spec is None or self.response is None:
            return self.failed(ProbeStage.AUTHENTICATED, "PROVIDER_RESPONSE_MISSING", "Provider response is unavailable.")
        if self.spec.api_key_env is not None and not self.secret_available:
            return self.failed(ProbeStage.AUTHENTICATED, "PROVIDER_CREDENTIAL_MISSING", "Configured provider credential is unavailable.")
        if self.response.status_code in {401, 403}:
            return self.failed(ProbeStage.AUTHENTICATED, "PROVIDER_AUTH_REJECTED", "Provider rejected authentication.")
        if self.spec.api_key_env is None:
            return self.not_applicable(
                ProbeStage.AUTHENTICATED,
                "PROVIDER_AUTH_NOT_REQUIRED",
                "Selected provider declares no credential requirement.",
            )
        if not self.response.is_success:
            return self.failed(ProbeStage.AUTHENTICATED, "PROVIDER_AUTH_UNVERIFIED", "Provider authentication could not be validated.")
        return self.passed(ProbeStage.AUTHENTICATED, "PROVIDER_AUTHENTICATED", "Provider accepted the configured credential.")

    def capable(self) -> ProbeStageResult:
        if self.spec is None or self.response is None or not self.response.is_success:
            return self.failed(ProbeStage.CAPABLE, "PROVIDER_DISCOVERY_FAILED", "Provider model discovery did not succeed.")
        try:
            payload = self.response.json()
            data = payload["data"] if isinstance(payload, dict) else None
            if not isinstance(data, list):
                raise TypeError
            models = tuple(
                item["id"]
                for item in data
                if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"]
            )
        except (KeyError, TypeError, ValueError):
            return self.failed(ProbeStage.CAPABLE, "PROVIDER_DISCOVERY_INVALID", "Provider discovery response is invalid.")
        self.observed_models = models
        if self.spec.model not in models:
            return self.failed(ProbeStage.CAPABLE, "PROVIDER_MODEL_MISSING", "Configured model was not advertised by the provider.")
        return self.passed(ProbeStage.CAPABLE, "PROVIDER_CAPABLE", "Configured model capability was observed.")

    def healthy(self) -> ProbeStageResult:
        if not self.observed_models:
            return self.failed(ProbeStage.HEALTHY, "PROVIDER_SMOKE_FAILED", "Provider read-only smoke did not complete.")
        return self.passed(ProbeStage.HEALTHY, "PROVIDER_HEALTHY", "Read-only provider discovery smoke completed.")


class DisabledMcpProbe(HealthProbe):
    component_id = "selected-mcp"
    component_name = "Selected MCP"
    mandatory = False

    def configured(self) -> ProbeStageResult:
        return self.not_applicable(
            ProbeStage.CONFIGURED,
            "MCP_NOT_ENABLED",
            "No MCP is enabled in the effective project configuration.",
        )

    def installed(self) -> ProbeStageResult:
        return self.not_applicable(ProbeStage.INSTALLED, "MCP_NOT_ENABLED", "No MCP is enabled.")

    reachable = installed
    authenticated = installed
    capable = installed
    healthy = installed


class UnsupportedMcpProbe(UnavailableProbe):
    def __init__(self, mcp_id: str) -> None:
        super().__init__(
            "selected-mcp",
            "Selected MCP",
            code="MCP_ADAPTER_UNSUPPORTED",
            message=f"Enabled MCP {mcp_id!r} has no operational adapter.",
        )


def default_serena_factory(
    path_guard: PathGuard,
    configuration: SerenaMcpConfiguration,
    authorization: TrustAuthorization | None,
) -> SerenaProbeAdapter:
    boundary = (
        None
        if authorization is None
        else TrustBoundaryEvaluator(
            path_guard.authorized_root,
            authorization=authorization,
        ).evaluate()
    )
    return SerenaAdapter(
        path_guard=path_guard,
        configuration=configuration,
        trust_boundary=boundary,
    )


class SerenaMcpProbe(HealthProbe):
    component_id = "selected-mcp"
    component_name = "Serena MCP"

    def __init__(
        self,
        project_root: Path,
        specification: Mapping[str, object],
        *,
        environment: Mapping[str, str],
        adapter_factory: SerenaAdapterFactory = default_serena_factory,
    ) -> None:
        self.project_root = project_root
        self.specification = specification
        self.environment = dict(environment)
        self.adapter_factory = adapter_factory
        self.transport: SerenaTransport | None = None
        self.command: Path | None = None
        self.endpoint: str | None = None
        self.args: tuple[str, ...] = ()
        self.api_key_env: str | None = None
        self.capabilities: SerenaCapabilities | None = None

    def configured(self) -> ProbeStageResult:
        raw_transport = self.specification.get("transport")
        try:
            self.transport = SerenaTransport(raw_transport)
        except (TypeError, ValueError):
            return self.failed(ProbeStage.CONFIGURED, "SERENA_CONFIG_INVALID", "Serena transport configuration is invalid.")
        raw_args = self.specification.get("args", [])
        if not isinstance(raw_args, list) or not all(isinstance(item, str) and "\x00" not in item for item in raw_args):
            return self.failed(ProbeStage.CONFIGURED, "SERENA_CONFIG_INVALID", "Serena arguments are invalid.")
        self.args = tuple(raw_args)
        raw_api_key_env = self.specification.get("api_key_env")
        if raw_api_key_env is not None and (not isinstance(raw_api_key_env, str) or not raw_api_key_env):
            return self.failed(ProbeStage.CONFIGURED, "SERENA_CONFIG_INVALID", "Serena credential reference is invalid.")
        self.api_key_env = raw_api_key_env
        if self.transport is SerenaTransport.STDIO:
            command = self.specification.get("command")
            if not isinstance(command, str) or not command or "\x00" in command:
                return self.failed(ProbeStage.CONFIGURED, "SERENA_CONFIG_INVALID", "Serena stdio command is invalid.")
        else:
            endpoint = self.specification.get("endpoint")
            if not isinstance(endpoint, str):
                return self.failed(ProbeStage.CONFIGURED, "SERENA_CONFIG_INVALID", "Serena HTTP endpoint is invalid.")
            parsed = urlsplit(endpoint)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
                return self.failed(ProbeStage.CONFIGURED, "SERENA_CONFIG_INVALID", "Serena HTTP endpoint is invalid.")
            self.endpoint = endpoint
        return self.passed(ProbeStage.CONFIGURED, "SERENA_CONFIGURED", "Serena MCP configuration is valid.")

    def installed(self) -> ProbeStageResult:
        if self.transport is SerenaTransport.STDIO:
            command = self.specification.get("command")
            assert isinstance(command, str)
            candidate = Path(command) if Path(command).is_absolute() else _find_executable(command, self.environment)
            try:
                self.command = candidate.resolve(strict=True) if candidate is not None else None
            except (OSError, RuntimeError, ValueError):
                self.command = None
            if self.command is None or not self.command.is_file() or not os.access(self.command, os.X_OK):
                return self.failed(ProbeStage.INSTALLED, "SERENA_NOT_INSTALLED", "Serena stdio executable was not found.")
        return self.passed(ProbeStage.INSTALLED, "SERENA_INSTALLED", "Serena adapter prerequisites are installed.")

    def reachable(self) -> ProbeStageResult:
        if self.transport is SerenaTransport.STDIO:
            return self.passed(ProbeStage.REACHABLE, "SERENA_PROCESS_REACHABLE", "Serena stdio executable is reachable.")
        if self.endpoint is None:
            return self.failed(ProbeStage.REACHABLE, "SERENA_ENDPOINT_MISSING", "Serena endpoint is unavailable.")
        parsed = urlsplit(self.endpoint)
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        try:
            with socket.create_connection((parsed.hostname or "", port), timeout=3.0):
                pass
        except OSError:
            return self.failed(ProbeStage.REACHABLE, "SERENA_UNREACHABLE", "Serena transport is unreachable.")
        return self.passed(ProbeStage.REACHABLE, "SERENA_REACHABLE", "Serena transport accepted a connection.")

    def authenticated(self) -> ProbeStageResult:
        if self.api_key_env is not None and not _environment_value(self.environment, self.api_key_env):
            return self.failed(ProbeStage.AUTHENTICATED, "SERENA_CREDENTIAL_MISSING", "Configured Serena credential is unavailable.")
        transport = self.transport
        if transport is None:
            return self.failed(ProbeStage.AUTHENTICATED, "SERENA_CONFIG_INVALID", "Serena transport is unavailable.")
        try:
            path_guard = PathGuard(self.project_root)
            authorization = None
            secret_headers: dict[str, str] = {}
            if self.api_key_env is not None:
                secret_headers["Authorization"] = self.api_key_env
                authorization = TrustAuthorization(
                    repository_root=os.fspath(self.project_root),
                    secret_grants=(SecretGrant(name=self.api_key_env, consumers=("tool:serena",)),),
                )
            configuration = SerenaMcpConfiguration(
                transport=transport,
                command=None if self.command is None else os.fspath(self.command),
                args=self.args,
                endpoint=self.endpoint,
                secret_headers=secret_headers,
                timeout_seconds=10.0,
            )
            self.capabilities = self.adapter_factory(path_guard, configuration, authorization).probe()
        except (OSError, RuntimeError, TypeError, ValueError):
            return self.failed(ProbeStage.AUTHENTICATED, "SERENA_SESSION_REJECTED", "Serena session could not be authenticated and initialized.")
        if self.api_key_env is None:
            return self.not_applicable(
                ProbeStage.AUTHENTICATED,
                "SERENA_AUTH_NOT_REQUIRED",
                "Selected Serena transport declares no credential requirement.",
            )
        return self.passed(ProbeStage.AUTHENTICATED, "SERENA_AUTHENTICATED", "Serena accepted the configured credential.")

    def capable(self) -> ProbeStageResult:
        if self.capabilities is None or not self.capabilities.tools:
            return self.failed(ProbeStage.CAPABLE, "SERENA_CAPABILITY_MISSING", "Serena advertised no tools.")
        return self.passed(ProbeStage.CAPABLE, "SERENA_CAPABLE", "Serena tools and active project root were observed.")

    def healthy(self) -> ProbeStageResult:
        if self.capabilities is None:
            return self.failed(ProbeStage.HEALTHY, "SERENA_SMOKE_FAILED", "Serena read-only smoke did not complete.")
        return self.passed(ProbeStage.HEALTHY, "SERENA_HEALTHY", "Read-only Serena session smoke completed.")


class StateStorageProbe(HealthProbe):
    component_id = "state-storage"
    component_name = "State storage"

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        self.storage_root = project_root / ".harness" / "state" / "executions"

    def configured(self) -> ProbeStageResult:
        if not self.storage_root.is_relative_to(self.project_root):
            return self.failed(ProbeStage.CONFIGURED, "STATE_PATH_INVALID", "State storage path escapes the project root.")
        return self.passed(ProbeStage.CONFIGURED, "STATE_CONFIGURED", "Canonical state storage path is configured.")

    def installed(self) -> ProbeStageResult:
        if AtomicFileStateStorage is None:  # pragma: no cover - imported symbol is always present
            return self.failed(ProbeStage.INSTALLED, "STATE_BACKEND_MISSING", "State storage backend is unavailable.")
        return self.passed(ProbeStage.INSTALLED, "STATE_BACKEND_INSTALLED", "Atomic state storage backend is installed.")

    def reachable(self) -> ProbeStageResult:
        if self.storage_root.is_symlink() or not self.storage_root.is_dir():
            return self.failed(ProbeStage.REACHABLE, "STATE_ROOT_MISSING", "Canonical state storage directory is missing.")
        return self.passed(ProbeStage.REACHABLE, "STATE_ROOT_REACHABLE", "Canonical state storage directory is reachable.")

    def authenticated(self) -> ProbeStageResult:
        return self.not_applicable(
            ProbeStage.AUTHENTICATED,
            "STATE_AUTH_NOT_APPLICABLE",
            "Local confined state storage requires no credential.",
        )

    def capable(self) -> ProbeStageResult:
        required = os.R_OK | os.W_OK | os.X_OK
        if not os.access(self.storage_root, required):
            return self.failed(ProbeStage.CAPABLE, "STATE_PERMISSION_DENIED", "State storage permissions are insufficient.")
        return self.passed(ProbeStage.CAPABLE, "STATE_CAPABLE", "State storage permissions permit the runtime contract.")

    def healthy(self) -> ProbeStageResult:
        try:
            tuple(self.storage_root.iterdir())
        except OSError:
            return self.failed(ProbeStage.HEALTHY, "STATE_SMOKE_FAILED", "Read-only state storage smoke failed.")
        return self.passed(ProbeStage.HEALTHY, "STATE_HEALTHY", "Read-only state storage smoke completed.")


def _default_worktree_base(environment: Mapping[str, str], project_id: str) -> Path:
    home = Path.home()
    if sys.platform == "win32":
        root = Path(_environment_value(environment, "LOCALAPPDATA") or home / "AppData" / "Local")
        return root / "ai-engineering-harness" / "worktrees" / project_id
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / "ai-engineering-harness" / "worktrees" / project_id
    return home / ".local" / "share" / "ai-engineering-harness" / "worktrees" / project_id


class WorktreePermissionsProbe(GitProbe):
    component_id = "worktree-permissions"
    component_name = "Worktree permissions"

    def __init__(
        self,
        project_root: Path,
        *,
        environment: Mapping[str, str],
        external_base: Path | None = None,
        runner: CommandRunner = run_command,
    ) -> None:
        super().__init__(project_root, environment=environment, runner=runner)
        self.external_base = external_base or _default_worktree_base(environment, "default-proj")

    def configured(self) -> ProbeStageResult:
        try:
            proposed = self.external_base.resolve(strict=False)
        except (OSError, RuntimeError, ValueError):
            return self.failed(ProbeStage.CONFIGURED, "WORKTREE_PATH_INVALID", "External worktree path is invalid.")
        if proposed.is_relative_to(self.project_root):
            return self.failed(ProbeStage.CONFIGURED, "WORKTREE_PATH_UNSAFE", "External worktree path is inside the repository.")
        self.external_base = proposed
        return self.passed(ProbeStage.CONFIGURED, "WORKTREE_CONFIGURED", "External worktree path is configured outside the repository.")

    def installed(self) -> ProbeStageResult:
        result = super().installed()
        if result.status.value == "FAIL":
            return self.failed(ProbeStage.INSTALLED, "WORKTREE_GIT_MISSING", "Git required for worktrees was not found.")
        return self.passed(ProbeStage.INSTALLED, "WORKTREE_GIT_INSTALLED", "Git worktree prerequisite is installed.")

    def reachable(self) -> ProbeStageResult:
        result = self._git("rev-parse", "--show-toplevel")
        if result is None or result.returncode != 0:
            return self.failed(ProbeStage.REACHABLE, "WORKTREE_REPOSITORY_UNREACHABLE", "Repository worktree cannot be inspected.")
        try:
            observed = Path(result.stdout.strip()).resolve(strict=True)
        except (OSError, RuntimeError, ValueError):
            return self.failed(ProbeStage.REACHABLE, "WORKTREE_REPOSITORY_INVALID", "Repository root returned by Git is invalid.")
        if observed != self.project_root:
            return self.failed(ProbeStage.REACHABLE, "WORKTREE_ROOT_MISMATCH", "Git root does not match the project root.")
        return self.passed(ProbeStage.REACHABLE, "WORKTREE_REPOSITORY_REACHABLE", "Repository worktree is reachable.")

    def authenticated(self) -> ProbeStageResult:
        return self.not_applicable(
            ProbeStage.AUTHENTICATED,
            "WORKTREE_AUTH_NOT_APPLICABLE",
            "Local worktree inspection requires no remote credential.",
        )

    def capable(self) -> ProbeStageResult:
        result = self._git("worktree", "list", "--porcelain")
        if result is None or result.returncode != 0 or not result.stdout.strip():
            return self.failed(ProbeStage.CAPABLE, "WORKTREE_CAPABILITY_MISSING", "Git worktree capability is unavailable.")
        return self.passed(ProbeStage.CAPABLE, "WORKTREE_CAPABLE", "Git worktree capability was observed.")

    def healthy(self) -> ProbeStageResult:
        candidate = self.external_base
        while not candidate.exists() and candidate.parent != candidate:
            candidate = candidate.parent
        if not candidate.is_dir() or not os.access(candidate, os.R_OK | os.W_OK | os.X_OK):
            return self.failed(ProbeStage.HEALTHY, "WORKTREE_PERMISSION_DENIED", "External worktree parent permissions are insufficient.")
        return self.passed(ProbeStage.HEALTHY, "WORKTREE_HEALTHY", "External worktree parent permissions were inspected read-only.")


class RequiredGatesProbe(HealthProbe):
    component_id = "required-gates"
    component_name = "Required gates"

    def __init__(
        self,
        project_root: Path,
        workflow: str | None,
        *,
        environment: Mapping[str, str],
    ) -> None:
        self.project_root = project_root
        self.workflow = workflow
        self.environment = dict(environment)
        self.mandatory = workflow is not None
        self.spec_path: Path | None = None
        self.raw_graph: dict[str, Any] | None = None
        self.requirements: tuple[RequiredGateSpec, ...] = ()

    def configured(self) -> ProbeStageResult:
        if self.workflow is None:
            return self.not_applicable(
                ProbeStage.CONFIGURED,
                "WORKFLOW_NOT_SELECTED",
                "No workflow was selected for gate inspection.",
            )
        if not self.workflow or any(token in self.workflow for token in ("/", "\\", "..", ":")):
            return self.failed(ProbeStage.CONFIGURED, "WORKFLOW_NAME_INVALID", "Workflow name is invalid.")
        path = self.project_root / ".harness" / "graphs" / "specs" / f"{self.workflow}.yaml"
        if path.is_symlink() or not path.is_file():
            return self.failed(ProbeStage.CONFIGURED, "WORKFLOW_SPEC_MISSING", "Workflow specification is missing.")
        self.spec_path = path
        return self.passed(ProbeStage.CONFIGURED, "WORKFLOW_CONFIGURED", "Workflow specification is configured.")

    def installed(self) -> ProbeStageResult:
        if importlib.util.find_spec("yaml") is None:
            return self.failed(ProbeStage.INSTALLED, "GATE_RESOLVER_MISSING", "Gate resolver prerequisite is unavailable.")
        return self.passed(ProbeStage.INSTALLED, "GATE_RESOLVER_INSTALLED", "Canonical gate resolver prerequisites are installed.")

    def reachable(self) -> ProbeStageResult:
        if self.spec_path is None:
            return self.failed(ProbeStage.REACHABLE, "WORKFLOW_SPEC_MISSING", "Workflow specification is unavailable.")
        try:
            loaded = yaml.safe_load(self.spec_path.read_text(encoding="utf-8", errors="strict"))
        except (OSError, UnicodeError, yaml.YAMLError):
            return self.failed(ProbeStage.REACHABLE, "WORKFLOW_SPEC_INVALID", "Workflow specification cannot be read safely.")
        if not isinstance(loaded, dict):
            return self.failed(ProbeStage.REACHABLE, "WORKFLOW_SPEC_INVALID", "Workflow specification is not a mapping.")
        self.raw_graph = loaded
        return self.passed(ProbeStage.REACHABLE, "WORKFLOW_SPEC_REACHABLE", "Workflow specification was read safely.")

    def authenticated(self) -> ProbeStageResult:
        return self.not_applicable(
            ProbeStage.AUTHENTICATED,
            "GATE_AUTH_NOT_APPLICABLE",
            "Local policy and gate resolution requires no credential.",
        )

    def capable(self) -> ProbeStageResult:
        if self.raw_graph is None or self.workflow is None:
            return self.failed(ProbeStage.CAPABLE, "WORKFLOW_GRAPH_MISSING", "Workflow graph is unavailable.")
        try:
            graph = GraphSpec.model_validate(self.raw_graph)
            if graph.graph.name != self.workflow:
                raise ValueError
            overrides: dict[str, Mapping[str, Any]] = {}
            for reference in graph.policies:
                candidate = self.project_root / ".harness" / reference
                if candidate.is_file() and not candidate.is_symlink():
                    document = yaml.safe_load(candidate.read_text(encoding="utf-8", errors="strict"))
                    if not isinstance(document, dict):
                        raise ValueError
                    overrides[reference] = document
            policies = PolicyRegistry(policy_documents=overrides or None).resolve_graph(graph)
            verification = next(
                policy
                for policy in policies
                if policy.requested_reference == "policies/verification_policy.yaml"
            )
            applies_to = verification.effective_policy.get("applies_to")
            if not isinstance(applies_to, list) or self.workflow not in applies_to:
                raise ValueError
            raw_requirements = verification.effective_policy.get("required_gates")
            if not isinstance(raw_requirements, list):
                raise TypeError
            self.requirements = tuple(RequiredGateSpec.model_validate(item) for item in raw_requirements)
            if not any(requirement.blocking for requirement in self.requirements):
                raise ValueError
        except (StopIteration, OSError, UnicodeError, TypeError, ValueError, yaml.YAMLError):
            return self.failed(ProbeStage.CAPABLE, "WORKFLOW_GATES_INVALID", "Workflow gates could not be composed canonically.")
        return self.passed(ProbeStage.CAPABLE, "WORKFLOW_GATES_CAPABLE", "Required workflow gates were composed canonically.")

    def healthy(self) -> ProbeStageResult:
        try:
            stack = StackDetector(self.project_root).detect()
            for requirement in self.requirements:
                if not requirement.blocking:
                    continue
                configured = VerificationEvaluator.configured_command(stack, requirement.id)
                if configured is None:
                    raise ValueError
                if configured.invocation == "python_module":
                    if importlib.util.find_spec(configured.tool) is None:
                        raise ValueError
                elif _find_executable(configured.tool, self.environment) is None:
                    raise ValueError
        except (ImportError, OSError, TypeError, ValueError):
            return self.failed(ProbeStage.HEALTHY, "GATE_PREREQUISITE_MISSING", "At least one required gate prerequisite is unavailable.")
        return self.passed(ProbeStage.HEALTHY, "GATES_HEALTHY", "Required gate commands resolved without execution.")


def selected_mcp_probe(
    project_root: Path,
    configuration: Mapping[str, object],
    *,
    environment: Mapping[str, str],
    serena_adapter_factory: SerenaAdapterFactory = default_serena_factory,
) -> HealthProbe:
    project = configuration.get("project", {})
    if not isinstance(project, dict):
        return UnavailableProbe(
            "selected-mcp",
            "Selected MCP",
            code="MCP_CONFIG_INVALID",
            message="Effective project configuration is invalid.",
        )
    raw_mcp = project.get("mcp", {})
    if raw_mcp in ({}, None):
        return DisabledMcpProbe()
    if not isinstance(raw_mcp, dict):
        return UnavailableProbe(
            "selected-mcp",
            "Selected MCP",
            code="MCP_CONFIG_INVALID",
            message="MCP configuration is invalid.",
        )
    if any(
        not isinstance(mcp_id, str)
        or not mcp_id
        or not isinstance(spec, dict)
        or type(spec.get("enabled", False)) is not bool
        for mcp_id, spec in raw_mcp.items()
    ):
        return UnavailableProbe(
            "selected-mcp",
            "Selected MCP",
            code="MCP_CONFIG_INVALID",
            message="MCP configuration is invalid.",
        )
    enabled = tuple(
        (mcp_id, spec)
        for mcp_id, spec in raw_mcp.items()
        if isinstance(mcp_id, str) and isinstance(spec, dict) and spec.get("enabled") is True
    )
    if not enabled:
        return DisabledMcpProbe()
    if len(enabled) != 1:
        return UnavailableProbe(
            "selected-mcp",
            "Selected MCP",
            code="MCP_SELECTION_AMBIGUOUS",
            message="Exactly one MCP may be enabled for this diagnostic.",
        )
    mcp_id, raw_spec = enabled[0]
    spec = dict(raw_spec)
    spec.pop("enabled", None)
    if mcp_id != "serena":
        return UnsupportedMcpProbe(mcp_id)
    return SerenaMcpProbe(
        project_root,
        spec,
        environment=environment,
        adapter_factory=serena_adapter_factory,
    )


__all__ = [
    "CommandRunner",
    "DisabledMcpProbe",
    "GitProbe",
    "ProviderProbe",
    "PythonToolchainProbe",
    "RequiredGatesProbe",
    "SerenaAdapterFactory",
    "SerenaMcpProbe",
    "StateStorageProbe",
    "UnavailableProbe",
    "UnsupportedMcpProbe",
    "WorktreePermissionsProbe",
    "default_serena_factory",
    "run_command",
    "selected_mcp_probe",
]
