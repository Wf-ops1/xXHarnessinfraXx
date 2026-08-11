"""Resolve configured verification commands and all prerequisites before effects."""

from __future__ import annotations

import importlib.util
import os
import shutil
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict

from ai_engineering_harness.contracts.policies import VerificationGateId
from ai_engineering_harness.core.detector import (
    DetectedCommand,
    DetectedStack,
    StackDetectionError,
    StackDetector,
)
from ai_engineering_harness.verification.evaluator import VerificationEvaluator
from ai_engineering_harness.workspace import ProvisionedWorktree, WorktreeStatus


class VerificationConfigurationError(ValueError):
    """A requested suite is invalid before stack/tool resolution."""


class VerificationPrerequisiteError(VerificationConfigurationError):
    """A required configured gate cannot be executed in this runtime."""

    code = "ERROR_PREREQUISITE"

    def __init__(self, message: str, *, gate_id: str | None = None) -> None:
        super().__init__(message)
        self.gate_id = gate_id


class ResolvedGateCommand(BaseModel):
    """Immutable executable policy for one canonical gate."""

    model_config = ConfigDict(strict=True, frozen=True)

    gate_id: VerificationGateId
    argv: tuple[str, ...]
    cwd: Literal["."]
    executable_alias: str
    executable_path: Path
    tool: str
    source: str


class ResolvedVerificationSuite(BaseModel):
    """The complete effect-free resolution consumed by the deterministic runner."""

    model_config = ConfigDict(strict=True, frozen=True)

    stack: DetectedStack
    worktree_root: Path
    commands: tuple[ResolvedGateCommand, ...]


class VerificationCommandResolver:
    """Detect stack/configuration and resolve every required tool before any gate."""

    _SAFE_ENVIRONMENT_NAMES = ("PATH", "SYSTEMROOT")

    def __init__(
        self,
        worktree: ProvisionedWorktree,
        *,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        self.worktree = self._validate_worktree(worktree)
        self.worktree_root = self.worktree.worktree_path.resolve(strict=True)
        self.environment = self._capture_environment(environment)
        self._detector = StackDetector(self.worktree_root)

    def resolve(self, active_gates: list[str]) -> ResolvedVerificationSuite:
        """Resolve the entire suite atomically with respect to terminal effects."""

        gates = self._validated_gates(active_gates)
        try:
            stack = self._detector.detect()
        except StackDetectionError as exc:
            raise VerificationPrerequisiteError(
                "verification stack/configuration could not be resolved"
            ) from exc

        resolved: list[ResolvedGateCommand] = []
        for gate in gates:
            try:
                configured = VerificationEvaluator.configured_command(stack, gate)
            except ValueError as exc:
                raise VerificationPrerequisiteError(
                    "verification configuration contains duplicate gate commands",
                    gate_id=gate,
                ) from exc
            if configured is None:
                raise VerificationPrerequisiteError(
                    f"required verification gate {gate!r} has no configured command",
                    gate_id=gate,
                )
            resolved.append(self._resolve_command(gate, configured))

        self._validate_aliases(tuple(resolved))
        return ResolvedVerificationSuite(
            stack=stack,
            worktree_root=self.worktree_root,
            commands=tuple(resolved),
        )

    @staticmethod
    def _validated_gates(active_gates: list[str]) -> tuple[VerificationGateId, ...]:
        gates = tuple(active_gates)
        if not gates:
            raise VerificationConfigurationError(
                "verification suite must contain at least one canonical gate"
            )
        if any(type(gate) is not str for gate in gates):
            raise VerificationConfigurationError(
                "verification gate ids must be exact canonical strings"
            )
        if len(set(gates)) != len(gates):
            raise VerificationConfigurationError("verification gate ids must be unique")
        unknown = tuple(
            gate for gate in gates if not VerificationEvaluator.is_canonical_gate_id(gate)
        )
        if unknown:
            rendered = ", ".join(repr(gate) for gate in unknown)
            raise VerificationConfigurationError(
                f"unknown verification gate id(s): {rendered}"
            )
        return cast(tuple[VerificationGateId, ...], gates)

    def _resolve_command(
        self,
        gate: VerificationGateId,
        configured: DetectedCommand,
    ) -> ResolvedGateCommand:
        if configured.invocation == "python_module":
            executable_path = self._python_executable()
            if not self._python_module_available(configured.tool):
                raise VerificationPrerequisiteError(
                    f"required Python tool {configured.tool!r} is not available",
                    gate_id=gate,
                )
            alias = "python"
        else:
            found_executable = self._find_executable(configured.tool)
            if found_executable is None:
                raise VerificationPrerequisiteError(
                    f"required executable {configured.tool!r} is not available",
                    gate_id=gate,
                )
            executable_path = found_executable
            alias = configured.tool

        return ResolvedGateCommand(
            gate_id=gate,
            argv=(alias, *configured.argv_tail),
            cwd=".",
            executable_alias=alias,
            executable_path=executable_path,
            tool=configured.tool,
            source=configured.source,
        )

    @staticmethod
    def _python_executable() -> Path:
        try:
            executable = Path(sys.executable).resolve(strict=True)
        except (OSError, RuntimeError, ValueError) as exc:
            raise VerificationPrerequisiteError(
                "current Python executable could not be resolved"
            ) from exc
        if not executable.is_file() or not os.access(executable, os.X_OK):
            raise VerificationPrerequisiteError(
                "current Python executable is not an executable file"
            )
        return executable

    @staticmethod
    def _python_module_available(module: str) -> bool:
        try:
            return importlib.util.find_spec(module) is not None
        except (ImportError, AttributeError, ValueError):
            return False

    def _find_executable(self, alias: str) -> Path | None:
        path_value = next(
            (
                value
                for name, value in self.environment.items()
                if name.casefold() == "path"
            ),
            None,
        )
        resolved = shutil.which(alias, path=path_value)
        if resolved is None:
            return None
        try:
            path = Path(resolved).resolve(strict=True)
        except (OSError, RuntimeError, ValueError):
            return None
        if not path.is_file() or not os.access(path, os.X_OK):
            return None
        return path

    @classmethod
    def _capture_environment(
        cls, supplied: Mapping[str, str] | None
    ) -> dict[str, str]:
        source = os.environ if supplied is None else supplied
        if not isinstance(source, Mapping):
            raise VerificationConfigurationError("environment must be a mapping")
        current = {name.casefold(): (name, value) for name, value in source.items()}
        captured: dict[str, str] = {}
        for allowed_name in cls._SAFE_ENVIRONMENT_NAMES:
            entry = current.get(allowed_name.casefold())
            if entry is None:
                continue
            name, value = entry
            if type(name) is not str or type(value) is not str or "\x00" in value:
                raise VerificationConfigurationError(
                    "environment values must be text without null bytes"
                )
            captured[name] = value
        return captured

    @staticmethod
    def _validate_worktree(worktree: ProvisionedWorktree) -> ProvisionedWorktree:
        if not isinstance(worktree, ProvisionedWorktree):
            raise VerificationConfigurationError(
                "verification requires a ProvisionedWorktree"
            )
        if worktree.reference.status is not WorktreeStatus.ACTIVE:
            raise VerificationConfigurationError(
                "verification requires an ACTIVE worktree reference"
            )
        try:
            worktree_root = worktree.worktree_path.resolve(strict=True)
            guarded_root = worktree.path_guard.authorized_root.resolve(strict=True)
        except (OSError, RuntimeError, ValueError) as exc:
            raise VerificationConfigurationError(
                "verification worktree roots could not be resolved"
            ) from exc
        if worktree_root != guarded_root or not worktree_root.is_dir():
            raise VerificationConfigurationError(
                "worktree path and canonical PathGuard root must match"
            )
        if worktree.reference.worktree_head_sha is None:
            raise VerificationConfigurationError(
                "verification worktree reference is missing its validated HEAD"
            )
        return worktree

    @staticmethod
    def _validate_aliases(commands: tuple[ResolvedGateCommand, ...]) -> None:
        aliases: dict[str, Path] = {}
        for command in commands:
            previous = aliases.setdefault(
                command.executable_alias, command.executable_path
            )
            if previous != command.executable_path:
                raise VerificationPrerequisiteError(
                    "resolved suite maps one executable alias to multiple paths",
                    gate_id=command.gate_id,
                )


__all__ = [
    "ResolvedGateCommand",
    "ResolvedVerificationSuite",
    "VerificationCommandResolver",
    "VerificationConfigurationError",
    "VerificationPrerequisiteError",
]
