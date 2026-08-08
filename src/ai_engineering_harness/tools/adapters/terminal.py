"""Constrained argv-based subprocess execution for authorized worktrees."""

from __future__ import annotations

import os
import re
import signal
import subprocess
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, BinaryIO, cast

from ai_engineering_harness.security import PathGuard, Redactor


class TerminalAdapterError(RuntimeError):
    """Base error for safe terminal execution failures."""


class TerminalConfigurationError(TerminalAdapterError, ValueError):
    """Raised when executable or environment policy is invalid."""


class CommandValidationError(TerminalAdapterError, ValueError):
    """Raised when a command request violates the typed contract."""


class ExecutableNotAllowedError(CommandValidationError):
    """Raised when argv[0] is absent from the executable policy."""


class EnvironmentNotAllowedError(CommandValidationError):
    """Raised when a request asks for an environment variable outside policy."""


class CommandExecutionError(TerminalAdapterError):
    """Raised when the subprocess cannot be started or reaped safely."""


class LegacyShellCommandError(CommandValidationError):
    """Raised when a legacy shell-string caller attempts execution."""


_ENVIRONMENT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_READ_CHUNK_BYTES = 64 * 1024
_DRAIN_JOIN_SECONDS = 5.0
_REAP_SECONDS = 10.0


@dataclass(frozen=True, slots=True)
class CommandRequest:
    """Immutable, normalized request for one policy-controlled process."""

    argv: tuple[str, ...]
    cwd: str
    timeout_seconds: float = 30.0
    env_allowlist: tuple[str, ...] = ()
    max_output_bytes: int = 1_000_000

    def __init__(
        self,
        *,
        argv: Sequence[str],
        cwd: str | os.PathLike[str],
        timeout_seconds: float = 30.0,
        env_allowlist: Sequence[str] = (),
        max_output_bytes: int = 1_000_000,
    ) -> None:
        normalized_argv = _normalize_argv(argv)
        normalized_cwd = _normalize_cwd(cwd)
        normalized_timeout = _normalize_timeout(timeout_seconds)
        normalized_environment = _normalize_environment_names(env_allowlist)
        normalized_output_limit = _normalize_output_limit(max_output_bytes)

        object.__setattr__(self, "argv", normalized_argv)
        object.__setattr__(self, "cwd", normalized_cwd)
        object.__setattr__(self, "timeout_seconds", normalized_timeout)
        object.__setattr__(self, "env_allowlist", normalized_environment)
        object.__setattr__(self, "max_output_bytes", normalized_output_limit)


@dataclass(frozen=True, slots=True)
class CommandResult:
    """Bounded and redacted evidence from a completed subprocess."""

    argv: tuple[str, ...]
    cwd_relative: str
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool
    stdout_truncated: bool
    stderr_truncated: bool


@dataclass(slots=True)
class _BoundedBytes:
    limit: int
    content: bytearray
    truncated: bool = False

    @classmethod
    def create(cls, limit: int) -> _BoundedBytes:
        return cls(limit=limit, content=bytearray())

    def append(self, chunk: bytes) -> None:
        remaining = self.limit - len(self.content)
        if remaining > 0:
            self.content.extend(chunk[:remaining])
        if len(chunk) > remaining:
            self.truncated = True


class TerminalAdapter:
    """Execute only explicitly authorized executables under one path guard."""

    __slots__ = ("_environment", "_environment_keys", "_executables", "_path_guard", "_taskkill")

    _environment: Mapping[str, str]
    _environment_keys: Mapping[str, str]
    _executables: Mapping[str, Path]
    _path_guard: PathGuard
    _taskkill: Path | None

    def __init__(
        self,
        *,
        path_guard: PathGuard,
        executables: Mapping[str, str | os.PathLike[str]],
        environment: Mapping[str, str],
    ) -> None:
        if not isinstance(path_guard, PathGuard):
            raise TerminalConfigurationError("path_guard must be an explicit PathGuard")
        object.__setattr__(self, "_path_guard", path_guard)

        normalized_executables = self._normalize_executables(executables)
        object.__setattr__(self, "_executables", MappingProxyType(normalized_executables))

        normalized_environment, environment_keys = self._normalize_environment(environment)
        object.__setattr__(self, "_environment", MappingProxyType(normalized_environment))
        object.__setattr__(self, "_environment_keys", MappingProxyType(environment_keys))
        taskkill = self._resolve_taskkill(normalized_environment)
        if os.name == "nt" and taskkill is None:
            raise TerminalConfigurationError(
                "Windows process-tree termination requires an authorized SYSTEMROOT"
            )
        object.__setattr__(self, "_taskkill", taskkill)

    def execute(self, request: CommandRequest) -> CommandResult:
        """Validate policy immediately before spawning one argv-based subprocess."""

        if not isinstance(request, CommandRequest):
            raise CommandValidationError("request must be a CommandRequest")

        executable = self._authorized_executable(request.argv[0])
        selected_environment = self._selected_environment(request.env_allowlist)
        guarded_cwd = self._path_guard.guard_read(request.cwd)
        if not guarded_cwd.absolute_path.is_dir():
            raise CommandValidationError("cwd must resolve to an existing directory")

        dynamic_secrets = {
            key: value for key, value in selected_environment.items() if value
        }
        secret_padding = max(
            (len(value.encode("utf-8", errors="replace")) for value in dynamic_secrets.values()),
            default=0,
        )
        capture_limit = request.max_output_bytes + secret_padding
        stdout_bytes = _BoundedBytes.create(capture_limit)
        stderr_bytes = _BoundedBytes.create(capture_limit)
        argv_for_process = [os.fspath(executable), *request.argv[1:]]

        process = self._spawn(
            argv=argv_for_process,
            cwd=guarded_cwd.absolute_path,
            environment=selected_environment,
        )
        assert process.stdout is not None
        assert process.stderr is not None

        drain_errors: list[BaseException] = []
        stdout_thread = self._start_drain(
            cast(BinaryIO, process.stdout), stdout_bytes, drain_errors, "stdout"
        )
        stderr_thread = self._start_drain(
            cast(BinaryIO, process.stderr), stderr_bytes, drain_errors, "stderr"
        )

        timed_out = False
        try:
            process.wait(timeout=request.timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            self._terminate_process_tree(process)
            try:
                process.wait(timeout=_REAP_SECONDS)
            except subprocess.TimeoutExpired as exc:
                raise CommandExecutionError("timed-out process could not be reaped safely") from exc
        finally:
            self._finish_drains(process, stdout_thread, stderr_thread)

        if drain_errors:
            raise CommandExecutionError("subprocess output could not be drained safely") from drain_errors[0]
        if process.returncode is None:
            raise CommandExecutionError("subprocess completed without an exit code")

        stdout, stdout_truncated = _safe_output(
            stdout_bytes,
            max_output_bytes=request.max_output_bytes,
            dynamic_secrets=dynamic_secrets,
        )
        stderr, stderr_truncated = _safe_output(
            stderr_bytes,
            max_output_bytes=request.max_output_bytes,
            dynamic_secrets=dynamic_secrets,
        )
        return CommandResult(
            argv=request.argv,
            cwd_relative=guarded_cwd.relative_path,
            exit_code=process.returncode,
            stdout=stdout,
            stderr=stderr,
            timed_out=timed_out,
            stdout_truncated=stdout_truncated,
            stderr_truncated=stderr_truncated,
        )

    @staticmethod
    def run_command(command: str, cwd: str, timeout: int = 30) -> dict[str, Any]:
        """Reject the shell-string API retained only for fail-closed compatibility."""

        del command, cwd, timeout
        raise LegacyShellCommandError(
            "shell-string execution is disabled; use CommandRequest and TerminalAdapter.execute"
        )

    @staticmethod
    def _normalize_executables(
        executables: Mapping[str, str | os.PathLike[str]],
    ) -> dict[str, Path]:
        if not isinstance(executables, Mapping) or not executables:
            raise TerminalConfigurationError("at least one executable policy entry is required")

        normalized: dict[str, Path] = {}
        for alias, configured_path in executables.items():
            if not isinstance(alias, str) or not alias or "\x00" in alias:
                raise TerminalConfigurationError("executable aliases must be non-empty text")
            if Path(alias).name != alias or "/" in alias or "\\" in alias:
                raise TerminalConfigurationError("executable aliases cannot contain paths")
            if alias in normalized:
                raise TerminalConfigurationError("executable aliases must be unique")
            try:
                raw_path = Path(configured_path)
            except (TypeError, ValueError) as exc:
                raise TerminalConfigurationError("executable path must be path-like text") from exc
            if not raw_path.is_absolute():
                raise TerminalConfigurationError("executable path must be absolute")
            try:
                resolved_path = raw_path.resolve(strict=True)
            except (OSError, RuntimeError, ValueError) as exc:
                raise TerminalConfigurationError("executable path must resolve to an existing file") from exc
            if not resolved_path.is_file() or not os.access(resolved_path, os.X_OK):
                raise TerminalConfigurationError("executable path must be an executable file")
            normalized[alias] = resolved_path
        return normalized

    @staticmethod
    def _normalize_environment(
        environment: Mapping[str, str],
    ) -> tuple[dict[str, str], dict[str, str]]:
        if not isinstance(environment, Mapping):
            raise TerminalConfigurationError("environment policy must be a mapping")
        normalized: dict[str, str] = {}
        lookup: dict[str, str] = {}
        for name, value in environment.items():
            if not isinstance(name, str) or _ENVIRONMENT_NAME.fullmatch(name) is None:
                raise TerminalConfigurationError("environment names must be portable identifiers")
            if not isinstance(value, str) or "\x00" in value:
                raise TerminalConfigurationError("environment values must be text without null bytes")
            folded = name.casefold()
            if folded in lookup:
                raise TerminalConfigurationError("environment names must be unique case-insensitively")
            lookup[folded] = name
            normalized[name] = value
        return normalized, lookup

    @staticmethod
    def _resolve_taskkill(environment: Mapping[str, str]) -> Path | None:
        if os.name != "nt":
            return None
        system_root = next(
            (value for key, value in environment.items() if key.casefold() == "systemroot"),
            None,
        )
        if not system_root:
            return None
        candidate = Path(system_root) / "System32" / "taskkill.exe"
        try:
            resolved = candidate.resolve(strict=True)
        except (OSError, RuntimeError, ValueError):
            return None
        return resolved if resolved.is_file() else None

    def _authorized_executable(self, alias: str) -> Path:
        executable = self._executables.get(alias)
        if executable is None:
            raise ExecutableNotAllowedError("argv[0] is not allowed by executable policy")
        try:
            current = executable.resolve(strict=True)
        except (OSError, RuntimeError, ValueError) as exc:
            raise TerminalConfigurationError("authorized executable is no longer available") from exc
        if current != executable or not current.is_file() or not os.access(current, os.X_OK):
            raise TerminalConfigurationError("authorized executable changed after policy creation")
        return executable

    def _selected_environment(self, requested_names: tuple[str, ...]) -> dict[str, str]:
        selected: dict[str, str] = {}
        for requested_name in requested_names:
            configured_name = self._environment_keys.get(requested_name.casefold())
            if configured_name is None:
                raise EnvironmentNotAllowedError(
                    "requested environment variable is not allowed by policy"
                )
            selected[configured_name] = self._environment[configured_name]
        return selected

    @staticmethod
    def _spawn(
        *,
        argv: list[str],
        cwd: Path,
        environment: Mapping[str, str],
    ) -> subprocess.Popen[bytes]:
        platform_options: dict[str, Any]
        if os.name == "nt":
            platform_options = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
        else:
            platform_options = {"start_new_session": True}
        try:
            return subprocess.Popen(
                argv,
                shell=False,
                cwd=cwd,
                env=dict(environment),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
                **platform_options,
            )
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            raise CommandExecutionError("authorized subprocess could not be started") from exc

    @staticmethod
    def _start_drain(
        stream: BinaryIO,
        destination: _BoundedBytes,
        errors: list[BaseException],
        label: str,
    ) -> threading.Thread:
        thread = threading.Thread(
            target=_drain_stream,
            args=(stream, destination, errors),
            name=f"terminal-{label}-drain",
            daemon=True,
        )
        thread.start()
        return thread

    @staticmethod
    def _finish_drains(
        process: subprocess.Popen[bytes],
        stdout_thread: threading.Thread,
        stderr_thread: threading.Thread,
    ) -> None:
        for thread in (stdout_thread, stderr_thread):
            thread.join(timeout=_DRAIN_JOIN_SECONDS)
        if stdout_thread.is_alive() or stderr_thread.is_alive():
            if process.stdout is not None:
                process.stdout.close()
            if process.stderr is not None:
                process.stderr.close()
            for thread in (stdout_thread, stderr_thread):
                thread.join(timeout=_DRAIN_JOIN_SECONDS)
        if stdout_thread.is_alive() or stderr_thread.is_alive():
            raise CommandExecutionError("subprocess output pipes did not close safely")

    def _terminate_process_tree(self, process: subprocess.Popen[bytes]) -> None:
        if os.name == "nt":
            terminated = False
            if self._taskkill is not None:
                try:
                    completed = subprocess.run(
                        [os.fspath(self._taskkill), "/PID", str(process.pid), "/T", "/F"],
                        shell=False,
                        env={
                            key: value
                            for key, value in self._environment.items()
                            if key.casefold() in {"path", "systemroot"}
                        },
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=False,
                        timeout=_DRAIN_JOIN_SECONDS,
                    )
                    terminated = completed.returncode == 0
                except (OSError, ValueError, subprocess.SubprocessError):
                    terminated = False
            if not terminated and process.poll() is None:
                process.kill()
            if not terminated:
                raise CommandExecutionError("timed-out Windows process tree could not be terminated")
            return

        kill_process_group = getattr(os, "killpg", None)
        kill_signal = getattr(signal, "SIGKILL", signal.SIGTERM)
        try:
            if kill_process_group is None:
                raise OSError("process-group termination is unavailable")
            kill_process_group(process.pid, kill_signal)
        except (ProcessLookupError, PermissionError, OSError):
            if process.poll() is None:
                process.kill()


def _normalize_argv(argv: Sequence[str]) -> tuple[str, ...]:
    if isinstance(argv, (str, bytes)):
        raise CommandValidationError("argv must be a sequence of argument strings")
    try:
        normalized = tuple(argv)
    except TypeError as exc:
        raise CommandValidationError("argv must be a sequence of argument strings") from exc
    if not normalized:
        raise CommandValidationError("argv cannot be empty")
    if any(not isinstance(argument, str) or not argument or "\x00" in argument for argument in normalized):
        raise CommandValidationError("argv entries must be non-empty text without null bytes")
    return normalized


def _normalize_cwd(cwd: str | os.PathLike[str]) -> str:
    try:
        normalized = os.fspath(cwd)
    except TypeError as exc:
        raise CommandValidationError("cwd must be path-like text") from exc
    if not isinstance(normalized, str) or "\x00" in normalized:
        raise CommandValidationError("cwd must be text without null bytes")
    return normalized


def _normalize_timeout(timeout_seconds: float) -> float:
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)):
        raise CommandValidationError("timeout_seconds must be a positive finite number")
    normalized = float(timeout_seconds)
    if normalized <= 0 or not (normalized < float("inf")):
        raise CommandValidationError("timeout_seconds must be a positive finite number")
    return normalized


def _normalize_environment_names(names: Sequence[str]) -> tuple[str, ...]:
    if isinstance(names, (str, bytes)):
        raise CommandValidationError("env_allowlist must be a sequence of names")
    try:
        normalized = tuple(names)
    except TypeError as exc:
        raise CommandValidationError("env_allowlist must be a sequence of names") from exc
    seen: set[str] = set()
    for name in normalized:
        if not isinstance(name, str) or _ENVIRONMENT_NAME.fullmatch(name) is None:
            raise CommandValidationError("environment names must be portable identifiers")
        folded = name.casefold()
        if folded in seen:
            raise CommandValidationError("environment names must be unique case-insensitively")
        seen.add(folded)
    return normalized


def _normalize_output_limit(max_output_bytes: int) -> int:
    if type(max_output_bytes) is not int or max_output_bytes <= 0:
        raise CommandValidationError("max_output_bytes must be a positive integer")
    return max_output_bytes


def _drain_stream(
    stream: BinaryIO,
    destination: _BoundedBytes,
    errors: list[BaseException],
) -> None:
    try:
        while chunk := stream.read(_READ_CHUNK_BYTES):
            destination.append(chunk)
    except (OSError, ValueError) as exc:
        errors.append(exc)
    finally:
        try:
            stream.close()
        except OSError as exc:
            errors.append(exc)


def _safe_output(
    captured: _BoundedBytes,
    *,
    max_output_bytes: int,
    dynamic_secrets: Mapping[str, str],
) -> tuple[str, bool]:
    decoded = bytes(captured.content).decode("utf-8", errors="replace")
    redacted = Redactor.redact_text(decoded, dynamic_secrets=dict(dynamic_secrets))
    encoded = redacted.encode("utf-8")
    truncated = captured.truncated or len(encoded) > max_output_bytes
    if len(encoded) > max_output_bytes:
        redacted = encoded[:max_output_bytes].decode("utf-8", errors="ignore")
    return redacted, truncated


__all__ = [
    "CommandExecutionError",
    "CommandRequest",
    "CommandResult",
    "CommandValidationError",
    "EnvironmentNotAllowedError",
    "ExecutableNotAllowedError",
    "LegacyShellCommandError",
    "TerminalAdapter",
    "TerminalAdapterError",
    "TerminalConfigurationError",
]
