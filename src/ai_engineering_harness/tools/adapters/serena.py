"""Explicit Serena MCP client with worktree-root and effect verification."""

from __future__ import annotations

import asyncio
import json
import os
import re
from collections.abc import AsyncIterator, Coroutine, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import timedelta
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, TypeVar
from urllib.parse import urlsplit

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client
from mcp.types import CallToolResult

from ai_engineering_harness.security import (
    PathGuard,
    RedactionContext,
    Redactor,
    SecretManager,
    TrustBoundaryConfigurationError,
    TrustCapabilityDeniedError,
    TrustEvaluationResult,
)

from .local_editing import LocalEditingAdapter

_T = TypeVar("_T")


class SerenaAdapterError(RuntimeError):
    """Base error for explicit Serena MCP operations."""


class SerenaConfigurationError(SerenaAdapterError, ValueError):
    """The configured transport or worktree boundary is invalid."""


class SerenaConnectionError(SerenaAdapterError):
    """The configured MCP server could not be reached or initialized."""


class SerenaCapabilityError(SerenaAdapterError):
    """The connected server lacks a required capability or exact project root."""


class SerenaToolExecutionError(SerenaAdapterError):
    """A Serena edit failed or did not produce a verified effect."""


class SerenaTransport(str, Enum):
    """MCP transports supported by the F3.8 adapter."""

    STDIO = "stdio"
    STREAMABLE_HTTP = "streamable-http"


_ENVIRONMENT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SECRET_REFERENCE = re.compile(r"^[A-Z][A-Z0-9_]*$")
_SENSITIVE_HEADER_NAMES = frozenset(
    {
        "authorization",
        "proxy-authorization",
        "cookie",
        "set-cookie",
        "x-api-key",
        "api-key",
    }
)
_SENSITIVE_HEADER_NAME = re.compile(
    r"(?i)(?:^|-)(?:authorization|auth|cookie|token|secret|api-key)(?:$|-)"
)
_SENSITIVE_ENVIRONMENT_NAME = re.compile(
    r"(?i)(?:^|_)(?:password|passwd|secret|token|api_?key|private_?key)(?:$|_)"
)
_ALLOWED_EDIT_TOOLS = frozenset(
    {
        "insert_after_symbol",
        "insert_before_symbol",
        "replace_content",
        "replace_symbol_body",
    }
)


@dataclass(frozen=True, slots=True)
class SerenaMcpConfiguration:
    """One explicit Serena transport; no endpoint or fallback is assumed."""

    transport: SerenaTransport
    command: str | None = None
    args: tuple[str, ...] = ()
    endpoint: str | None = None
    environment: Mapping[str, str] = field(default_factory=dict, repr=False)
    headers: Mapping[str, str] = field(default_factory=dict, repr=False)
    secret_environment: Mapping[str, str] = field(default_factory=dict, repr=False)
    secret_headers: Mapping[str, str] = field(default_factory=dict, repr=False)
    timeout_seconds: float = 30.0
    _resolved_command: str | None = field(default=None, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.transport, SerenaTransport):
            raise SerenaConfigurationError("transport must be an explicit SerenaTransport")
        timeout = _positive_timeout(self.timeout_seconds)
        object.__setattr__(self, "timeout_seconds", timeout)
        args = _string_tuple("args", self.args)
        environment = _environment(self.environment)
        headers = _headers(self.headers)
        secret_environment = _secret_references(
            "secret_environment",
            self.secret_environment,
            target_validator=_environment_target,
        )
        secret_headers = _secret_references(
            "secret_headers",
            self.secret_headers,
            target_validator=_header_target,
        )
        object.__setattr__(self, "args", args)
        object.__setattr__(self, "environment", MappingProxyType(environment))
        object.__setattr__(self, "headers", MappingProxyType(headers))
        object.__setattr__(self, "secret_environment", MappingProxyType(secret_environment))
        object.__setattr__(self, "secret_headers", MappingProxyType(secret_headers))
        if _casefold_overlap(environment, secret_environment):
            raise SerenaConfigurationError(
                "public and secret environment targets must not overlap"
            )
        if _casefold_overlap(headers, secret_headers):
            raise SerenaConfigurationError(
                "public and secret HTTP header targets must not overlap"
            )

        if self.transport is SerenaTransport.STDIO:
            if self.endpoint is not None or headers or secret_headers:
                raise SerenaConfigurationError(
                    "stdio transport cannot define endpoint or HTTP headers"
                )
            if not isinstance(self.command, str) or not self.command or "\x00" in self.command:
                raise SerenaConfigurationError("stdio command must be an absolute executable path")
            command = Path(self.command)
            if not command.is_absolute():
                raise SerenaConfigurationError("stdio command must be absolute")
            configured = Path(os.path.abspath(os.fspath(command)))
            try:
                resolved = configured.resolve(strict=True)
            except (OSError, RuntimeError, ValueError) as exc:
                raise SerenaConfigurationError("stdio command must resolve to an existing executable") from exc
            if not configured.is_file() or not os.access(configured, os.X_OK):
                raise SerenaConfigurationError("stdio command must resolve to an executable file")
            object.__setattr__(self, "command", os.fspath(configured))
            object.__setattr__(self, "_resolved_command", os.fspath(resolved))
            return

        if self.command is not None or args or environment or secret_environment:
            raise SerenaConfigurationError(
                "Streamable HTTP cannot define a stdio command, args, or environment"
            )
        if not isinstance(self.endpoint, str) or "\x00" in self.endpoint:
            raise SerenaConfigurationError("Streamable HTTP requires an explicit endpoint")
        parsed = urlsplit(self.endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise SerenaConfigurationError("Streamable HTTP endpoint must be an absolute HTTP(S) URL")
        if parsed.username is not None or parsed.password is not None or parsed.fragment:
            raise SerenaConfigurationError("Streamable HTTP endpoint cannot contain credentials or a fragment")


@dataclass(frozen=True, slots=True)
class SerenaCapabilities:
    """Observed MCP identity and tool names for one initialized connection."""

    transport: str
    protocol_version: str
    server_name: str
    tools: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SerenaEditResult:
    """Evidence for a Serena call whose target digest really changed."""

    tool_name: str
    relative_path: str
    previous_sha256: str
    sha256: str
    size_bytes: int
    mcp_result: dict[str, Any]


class SerenaAdapter:
    """Call allowlisted Serena edit tools only after proving the active worktree."""

    __slots__ = (
        "_configuration",
        "_local",
        "_path_guard",
        "_redaction_context",
        "_secret_environment",
        "_secret_headers",
    )

    def __init__(
        self,
        *,
        path_guard: PathGuard,
        configuration: SerenaMcpConfiguration,
        trust_boundary: TrustEvaluationResult | None = None,
    ) -> None:
        if not isinstance(path_guard, PathGuard):
            raise SerenaConfigurationError("path_guard must be an explicit PathGuard")
        if not isinstance(configuration, SerenaMcpConfiguration):
            raise SerenaConfigurationError("configuration must be an explicit SerenaMcpConfiguration")
        self._path_guard = path_guard
        self._configuration = configuration
        self._local = LocalEditingAdapter(path_guard=path_guard)
        has_secret_references = bool(
            configuration.secret_environment or configuration.secret_headers
        )
        if has_secret_references and isinstance(trust_boundary, TrustEvaluationResult):
            try:
                trust_boundary.require_root(path_guard.authorized_root)
            except (TrustBoundaryConfigurationError, TrustCapabilityDeniedError) as exc:
                raise SerenaConfigurationError(
                    "Serena trust boundary must match the PathGuard root"
                ) from exc
        secret_environment, secret_headers, context = _resolve_configuration_secrets(
            configuration,
            trust_boundary=trust_boundary,
        )
        self._secret_environment = MappingProxyType(secret_environment)
        self._secret_headers = MappingProxyType(secret_headers)
        self._redaction_context = context

    @property
    def authorized_root(self) -> Path:
        """Return the exact worktree root that every session must prove."""

        return self._path_guard.authorized_root

    @property
    def redaction_context(self) -> RedactionContext:
        """Return the value-safe context for downstream public projections."""

        return self._redaction_context

    def probe(self) -> SerenaCapabilities:
        """Initialize a fresh MCP session and return only observed capabilities."""

        return self._run(self._probe())

    def edit(
        self,
        *,
        tool_name: str,
        relative_path: str | os.PathLike[str],
        arguments: Mapping[str, Any],
    ) -> SerenaEditResult:
        """Execute one allowlisted semantic edit and verify a real file change."""

        if tool_name not in _ALLOWED_EDIT_TOOLS:
            raise SerenaCapabilityError("Serena edit tool is not allowlisted")
        if not isinstance(arguments, Mapping):
            raise SerenaConfigurationError("Serena arguments must be a mapping")
        copied_arguments = dict(arguments)
        forbidden = {"relative_path", "project", "project_path"} & set(copied_arguments)
        if forbidden:
            raise SerenaConfigurationError("Serena arguments cannot override path or project ownership")
        _validate_json_arguments(copied_arguments)

        before = self._local.read_file(relative_path)
        mcp_result = self._run(
            self._edit(
                tool_name=tool_name,
                relative_path=before.relative_path,
                arguments=copied_arguments,
            )
        )
        after = self._local.read_file(before.relative_path)
        if after.relative_path != before.relative_path:
            raise SerenaToolExecutionError("Serena target identity changed after the call")
        if after.sha256 == before.sha256:
            raise SerenaToolExecutionError("Serena call returned without changing the target file")
        return SerenaEditResult(
            tool_name=tool_name,
            relative_path=after.relative_path,
            previous_sha256=before.sha256,
            sha256=after.sha256,
            size_bytes=after.size_bytes,
            mcp_result=mcp_result,
        )

    def edit_file_semantic(
        self,
        file_path: str | os.PathLike[str],
        changes: Mapping[str, Any],
    ) -> SerenaEditResult:
        """Compatibility wrapper with an explicit tool name and nested arguments."""

        if not isinstance(changes, Mapping):
            raise SerenaConfigurationError("changes must be a mapping")
        if set(changes) != {"tool_name", "arguments"}:
            raise SerenaConfigurationError("changes must contain exactly tool_name and arguments")
        tool_name = changes["tool_name"]
        arguments = changes["arguments"]
        if not isinstance(tool_name, str) or not isinstance(arguments, Mapping):
            raise SerenaConfigurationError("tool_name and arguments have invalid types")
        return self.edit(tool_name=tool_name, relative_path=file_path, arguments=arguments)

    def _run(self, operation: Coroutine[Any, Any, _T]) -> _T:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            try:
                return asyncio.run(self._run_with_timeout(operation))
            except TimeoutError:
                raise SerenaConnectionError(
                    "Serena MCP operation exceeded its configured timeout"
                ) from None
        operation.close()
        raise SerenaConfigurationError("synchronous SerenaAdapter cannot run inside an active event loop")

    async def _run_with_timeout(self, operation: Coroutine[Any, Any, _T]) -> _T:
        async with asyncio.timeout(self._configuration.timeout_seconds) as timeout_scope:
            try:
                return await operation
            except BaseException as exc:
                # MCP transports can translate cancellation into an ExceptionGroup
                # while unwinding. The timeout scope remains the source of truth.
                if timeout_scope.expired():
                    raise TimeoutError from exc
                raise

    async def _probe(self) -> SerenaCapabilities:
        async with self._session() as (session, initialized):
            tools = await self._list_tools(session)
            await self._require_active_root(session, tools)
            server_info = initialized.serverInfo
            return SerenaCapabilities(
                transport=self._configuration.transport.value,
                protocol_version=initialized.protocolVersion,
                server_name=server_info.name,
                tools=tuple(sorted(tools)),
            )

    async def _edit(
        self,
        *,
        tool_name: str,
        relative_path: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        async with self._session() as (session, _):
            tools = await self._list_tools(session)
            await self._require_active_root(session, tools)
            if tool_name not in tools:
                raise SerenaCapabilityError(f"configured Serena server does not expose {tool_name}")
            payload = {**arguments, "relative_path": relative_path}
            result = await session.call_tool(tool_name, arguments=payload)
            self._require_success(result, operation=tool_name)
            return _redacted_result(result, context=self._redaction_context)

    @asynccontextmanager
    async def _session(self) -> AsyncIterator[tuple[ClientSession, Any]]:
        timeout = timedelta(seconds=self._configuration.timeout_seconds)
        try:
            if self._configuration.transport is SerenaTransport.STDIO:
                command = self._validated_stdio_command()
                parameters = StdioServerParameters(
                    command=command,
                    args=list(self._configuration.args),
                    env={
                        **self._configuration.environment,
                        **self._secret_environment,
                    },
                    cwd=self.authorized_root,
                    encoding="utf-8",
                    encoding_error_handler="strict",
                )
                with open(os.devnull, "w", encoding="utf-8") as error_log:  # noqa: ASYNC230
                    async with stdio_client(parameters, errlog=error_log) as (read_stream, write_stream):
                        async with ClientSession(
                            read_stream,
                            write_stream,
                            read_timeout_seconds=timeout,
                        ) as session:
                            initialized = await session.initialize()
                            yield session, initialized
                return

            assert self._configuration.endpoint is not None
            async with httpx.AsyncClient(
                headers={
                    **self._configuration.headers,
                    **self._secret_headers,
                },
                timeout=self._configuration.timeout_seconds,
                follow_redirects=False,
            ) as http_client, streamable_http_client(
                self._configuration.endpoint,
                http_client=http_client,
            ) as (read_stream, write_stream, _), ClientSession(
                read_stream,
                write_stream,
                read_timeout_seconds=timeout,
            ) as session:
                initialized = await session.initialize()
                yield session, initialized
        except BaseExceptionGroup as exc:
            adapter_error = _find_adapter_error(exc)
            if adapter_error is not None:
                raise adapter_error
            if _contains_timeout(exc):
                raise SerenaConnectionError(
                    "Serena MCP operation exceeded its configured timeout"
                ) from None
            if _contains_cancellation(exc):
                raise asyncio.CancelledError from exc
            safe_type = Redactor.redact_text(type(exc).__name__)
            raise SerenaConnectionError(
                f"Serena MCP connection failed: {safe_type}"
            ) from None
        except SerenaAdapterError:
            raise
        except Exception as exc:  # noqa: BLE001 - external MCP transports are normalized here
            safe_type = Redactor.redact_text(type(exc).__name__)
            raise SerenaConnectionError(
                f"Serena MCP connection failed: {safe_type}"
            ) from None

    def _validated_stdio_command(self) -> str:
        command = self._configuration.command
        expected = self._configuration._resolved_command
        if command is None or expected is None:
            raise SerenaConfigurationError("stdio command identity is unavailable")
        configured = Path(command)
        try:
            current = configured.resolve(strict=True)
        except (OSError, RuntimeError, ValueError) as exc:
            raise SerenaConfigurationError("stdio command is no longer available") from exc
        if os.fspath(current) != expected or not configured.is_file() or not os.access(configured, os.X_OK):
            raise SerenaConfigurationError("stdio command changed after configuration")
        return command

    @staticmethod
    async def _list_tools(session: ClientSession) -> dict[str, Any]:
        tools: dict[str, Any] = {}
        cursor: str | None = None
        while True:
            result = await session.list_tools(cursor=cursor)
            for tool in result.tools:
                if tool.name in tools:
                    raise SerenaCapabilityError("Serena tools/list returned a duplicate capability")
                tools[tool.name] = tool
            cursor = result.nextCursor
            if cursor is None:
                return tools

    async def _require_active_root(self, session: ClientSession, tools: Mapping[str, Any]) -> None:
        root = os.fspath(self.authorized_root)
        if "activate_project" in tools:
            activated = await session.call_tool("activate_project", arguments={"project": root})
            self._require_success(activated, operation="activate_project")
        if "get_active_project" not in tools:
            raise SerenaCapabilityError("Serena server cannot prove its active project root")
        active = await session.call_tool("get_active_project", arguments={})
        self._require_success(active, operation="get_active_project")
        if not _result_contains_root(active, self.authorized_root):
            raise SerenaCapabilityError("Serena active project does not match the authorized worktree")

    @staticmethod
    def _require_success(result: CallToolResult, *, operation: str) -> None:
        if result.isError:
            raise SerenaToolExecutionError(f"Serena MCP tool reported an error: {operation}")


def _result_contains_root(result: CallToolResult, root: Path) -> bool:
    serialized = json.dumps(
        result.model_dump(mode="json", by_alias=True, exclude_none=True),
        ensure_ascii=False,
        sort_keys=True,
    )
    normalized = serialized.replace("\\\\", "/").replace("\\", "/").casefold()
    candidates = {
        os.fspath(root).replace("\\", "/").casefold(),
        root.as_posix().casefold(),
    }
    return any(candidate in normalized for candidate in candidates)


def _find_adapter_error(exc: BaseException) -> SerenaAdapterError | None:
    if isinstance(exc, SerenaAdapterError):
        return exc
    if isinstance(exc, BaseExceptionGroup):
        for nested in exc.exceptions:
            found = _find_adapter_error(nested)
            if found is not None:
                return found
    return None


def _contains_cancellation(exc: BaseException) -> bool:
    if isinstance(exc, asyncio.CancelledError):
        return True
    if isinstance(exc, BaseExceptionGroup):
        return any(_contains_cancellation(nested) for nested in exc.exceptions)
    return False


def _contains_timeout(exc: BaseException) -> bool:
    if isinstance(exc, TimeoutError) or "timed out" in str(exc).casefold():
        return True
    if isinstance(exc, BaseExceptionGroup):
        return any(_contains_timeout(nested) for nested in exc.exceptions)
    return False


def _redacted_result(
    result: CallToolResult,
    *,
    context: RedactionContext,
) -> dict[str, Any]:
    projected = Redactor.redact_json(
        result.model_dump(mode="json", by_alias=True, exclude_none=True),
        context=context,
    )
    if not isinstance(projected, dict):  # pragma: no cover - model_dump invariant
        raise SerenaToolExecutionError("Serena result was not a JSON object")
    return projected


def _validate_json_arguments(arguments: Mapping[str, Any]) -> None:
    try:
        json.dumps(arguments, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise SerenaConfigurationError("Serena arguments must be JSON-native") from exc


def _positive_timeout(value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SerenaConfigurationError("timeout_seconds must be a positive finite number")
    normalized = float(value)
    if normalized <= 0 or normalized >= float("inf"):
        raise SerenaConfigurationError("timeout_seconds must be a positive finite number")
    return normalized


def _string_tuple(label: str, values: object) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise SerenaConfigurationError(f"{label} must be a sequence of strings")
    try:
        normalized: tuple[Any, ...] = tuple(values)  # type: ignore[arg-type]
    except TypeError as exc:
        raise SerenaConfigurationError(f"{label} must be a sequence of strings") from exc
    if any(not isinstance(item, str) or not item or "\x00" in item for item in normalized):
        raise SerenaConfigurationError(f"{label} entries must be non-empty text without null bytes")
    return normalized


def _environment(values: Mapping[str, str]) -> dict[str, str]:
    if not isinstance(values, Mapping):
        raise SerenaConfigurationError("environment must be a mapping")
    result: dict[str, str] = {}
    for name, value in values.items():
        if not isinstance(name, str) or _ENVIRONMENT_NAME.fullmatch(name) is None:
            raise SerenaConfigurationError("environment names must be portable identifiers")
        if not isinstance(value, str) or "\x00" in value:
            raise SerenaConfigurationError("environment values must be text without null bytes")
        if _SENSITIVE_ENVIRONMENT_NAME.search(name) is not None:
            raise SerenaConfigurationError(
                "sensitive environment values must use secret_environment references"
            )
        if name.casefold() in {key.casefold() for key in result}:
            raise SerenaConfigurationError("environment names must be unique case-insensitively")
        result[name] = value
    return result


def _headers(values: Mapping[str, str]) -> dict[str, str]:
    if not isinstance(values, Mapping):
        raise SerenaConfigurationError("headers must be a mapping")
    result: dict[str, str] = {}
    for name, value in values.items():
        if not isinstance(name, str) or not name or any(character in name for character in "\r\n:\x00"):
            raise SerenaConfigurationError("HTTP header name is invalid")
        if not isinstance(value, str) or any(character in value for character in "\r\n\x00"):
            raise SerenaConfigurationError("HTTP header value is invalid")
        if _is_sensitive_header_name(name):
            raise SerenaConfigurationError(
                "sensitive HTTP headers must use secret_headers references"
            )
        if name.casefold() in {key.casefold() for key in result}:
            raise SerenaConfigurationError("HTTP headers must be unique case-insensitively")
        result[name] = value
    return result


def _secret_references(
    label: str,
    values: Mapping[str, str],
    *,
    target_validator: Any,
) -> dict[str, str]:
    if not isinstance(values, Mapping):
        raise SerenaConfigurationError(f"{label} must be a mapping")
    result: dict[str, str] = {}
    for target, secret_name in values.items():
        target_validator(target)
        if not isinstance(secret_name, str) or _SECRET_REFERENCE.fullmatch(secret_name) is None:
            raise SerenaConfigurationError(f"{label} values must be environment secret names")
        if target.casefold() in {name.casefold() for name in result}:
            raise SerenaConfigurationError(f"{label} targets must be unique case-insensitively")
        result[target] = secret_name
    return result


def _environment_target(name: object) -> None:
    if not isinstance(name, str) or _ENVIRONMENT_NAME.fullmatch(name) is None:
        raise SerenaConfigurationError("secret environment targets must be portable identifiers")


def _header_target(name: object) -> None:
    if not isinstance(name, str) or not _is_sensitive_header_name(name):
        raise SerenaConfigurationError("secret header targets must be supported sensitive headers")


def _is_sensitive_header_name(name: str) -> bool:
    return (
        name.casefold() in _SENSITIVE_HEADER_NAMES
        or _SENSITIVE_HEADER_NAME.search(name) is not None
    )


def _casefold_overlap(
    public: Mapping[str, str],
    secret: Mapping[str, str],
) -> bool:
    return bool(
        {name.casefold() for name in public}
        & {name.casefold() for name in secret}
    )


def _resolve_configuration_secrets(
    configuration: SerenaMcpConfiguration,
    *,
    trust_boundary: TrustEvaluationResult | None,
) -> tuple[dict[str, str], dict[str, str], RedactionContext]:
    references = {
        *configuration.secret_environment.values(),
        *configuration.secret_headers.values(),
    }
    if not references:
        return {}, {}, RedactionContext()
    if not isinstance(trust_boundary, TrustEvaluationResult):
        raise SerenaConfigurationError(
            "Serena secret references require an explicit trust boundary"
        )

    resolved: dict[str, str] = {}
    for secret_name in sorted(references):
        value = SecretManager.get_secret(
            secret_name,
            boundary=trust_boundary,
            consumer="tool:serena",
        )
        if not value:
            raise SerenaConfigurationError("configured Serena secret is unavailable")
        resolved[secret_name] = value

    environment = {
        target: resolved[secret_name]
        for target, secret_name in configuration.secret_environment.items()
    }
    headers = {
        target: (
            f"Bearer {resolved[secret_name]}"
            if target.casefold() in {"authorization", "proxy-authorization"}
            else resolved[secret_name]
        )
        for target, secret_name in configuration.secret_headers.items()
    }
    return environment, headers, RedactionContext(resolved)


__all__ = [
    "SerenaAdapter",
    "SerenaAdapterError",
    "SerenaCapabilities",
    "SerenaCapabilityError",
    "SerenaConfigurationError",
    "SerenaConnectionError",
    "SerenaEditResult",
    "SerenaMcpConfiguration",
    "SerenaToolExecutionError",
    "SerenaTransport",
]
