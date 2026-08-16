"""Composition root for the real ``harness doctor`` command."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

import httpx

from ai_engineering_harness.core import ConfigResolver
from ai_engineering_harness.doctor.components import (
    CommandRunner,
    GitProbe,
    ProviderProbe,
    PythonToolchainProbe,
    RequiredGatesProbe,
    SerenaAdapterFactory,
    StateStorageProbe,
    UnavailableProbe,
    WorktreePermissionsProbe,
    default_serena_factory,
    run_command,
    selected_mcp_probe,
)
from ai_engineering_harness.doctor.probes import (
    ComponentProbeResult,
    DoctorResult,
    HealthProbe,
)


class DoctorChecker:
    """Resolve canonical configuration and run deterministic read-only probes."""

    def __init__(
        self,
        config: Mapping[str, object] | None = None,
        *,
        project_root: Path | None = None,
        profile_name: str = "default",
        workflow: str | None = None,
        environment: Mapping[str, str] | None = None,
        runner: CommandRunner = run_command,
        provider_transport: httpx.BaseTransport | None = None,
        serena_adapter_factory: SerenaAdapterFactory = default_serena_factory,
        probes: tuple[HealthProbe, ...] | None = None,
    ) -> None:
        raw_root = Path.cwd() if project_root is None else Path(project_root)
        self.project_root = raw_root.resolve(strict=True)
        self.profile_name = profile_name
        self.workflow = workflow
        self.environment = dict(os.environ if environment is None else environment)
        self.runner = runner
        self.provider_transport = provider_transport
        self.serena_adapter_factory = serena_adapter_factory
        self._supplied_config = None if config is None else dict(config)
        self._probes = probes
        self._configuration_cache: dict[str, object] | None = None

    def _configuration(self) -> dict[str, object] | None:
        try:
            if self._supplied_config is None:
                return ConfigResolver(self.project_root).resolve(self.profile_name)
            return ConfigResolver.validate_and_redact(self._supplied_config)
        except (OSError, TypeError, ValueError):
            return None

    def _worktree_probe(self) -> HealthProbe:
        configuration = self._configuration_cache
        external_base: Path | None = None
        if configuration is not None:
            project = configuration.get("project", {})
            if isinstance(project, dict):
                worktree = project.get("worktree", {})
                if not isinstance(worktree, dict):
                    return UnavailableProbe(
                        "worktree-permissions",
                        "Worktree permissions",
                        code="WORKTREE_CONFIG_INVALID",
                        message="External worktree configuration is invalid.",
                    )
                configured_base = worktree.get("external_base_dir")
                if configured_base is not None:
                    if not isinstance(configured_base, str) or "\x00" in configured_base:
                        return UnavailableProbe(
                            "worktree-permissions",
                            "Worktree permissions",
                            code="WORKTREE_CONFIG_INVALID",
                            message="External worktree configuration is invalid.",
                        )
                    external_base = Path(configured_base)
                    if not external_base.is_absolute():
                        return UnavailableProbe(
                            "worktree-permissions",
                            "Worktree permissions",
                            code="WORKTREE_CONFIG_INVALID",
                            message="External worktree path must be absolute.",
                        )
        return WorktreePermissionsProbe(
            self.project_root,
            environment=self.environment,
            external_base=external_base,
            runner=self.runner,
        )

    def _default_probes(self) -> tuple[HealthProbe, ...]:
        configuration = self._configuration()
        self._configuration_cache = configuration
        if configuration is None:
            provider: HealthProbe = UnavailableProbe(
                "selected-provider",
                "Selected provider",
                code="EFFECTIVE_CONFIG_INVALID",
                message="Effective configuration could not be resolved.",
            )
            mcp: HealthProbe = UnavailableProbe(
                "selected-mcp",
                "Selected MCP",
                code="EFFECTIVE_CONFIG_INVALID",
                message="Effective configuration could not be resolved.",
                mandatory=False,
            )
        else:
            provider = ProviderProbe(
                configuration,
                environment=self.environment,
                transport=self.provider_transport,
            )
            mcp = selected_mcp_probe(
                self.project_root,
                configuration,
                environment=self.environment,
                serena_adapter_factory=self.serena_adapter_factory,
            )

        return (
            GitProbe(
                self.project_root,
                environment=self.environment,
                runner=self.runner,
            ),
            PythonToolchainProbe(
                self.project_root,
                environment=self.environment,
                runner=self.runner,
            ),
            provider,
            mcp,
            StateStorageProbe(self.project_root),
            self._worktree_probe(),
            RequiredGatesProbe(
                self.project_root,
                self.workflow,
                environment=self.environment,
            ),
        )

    def check(self) -> DoctorResult:
        probes = self._probes if self._probes is not None else self._default_probes()
        results = tuple(probe.probe() for probe in probes)
        return DoctorResult.build(results, workflow=self.workflow)

    def check_all(self) -> list[ComponentProbeResult]:
        """Compatibility projection for callers that only consume component results."""

        return list(self.check().components)


__all__ = ["DoctorChecker"]
