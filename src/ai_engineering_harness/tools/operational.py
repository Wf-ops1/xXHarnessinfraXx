"""Opt-in registrations for confined, operational worktree tools."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

from pydantic import JsonValue

from ai_engineering_harness.security import (
    RedactionContext,
    TrustBoundaryEvaluator,
    TrustCapabilityDeniedError,
    TrustEvaluationResult,
)
from ai_engineering_harness.tools.adapters.local_editing import LocalEditingAdapter
from ai_engineering_harness.tools.adapters.serena import SerenaAdapter
from ai_engineering_harness.tools.adapters.terminal import (
    CommandCancellation,
    CommandRequest,
    CommandResult,
    TerminalAdapter,
)
from ai_engineering_harness.tools.router import ToolDefinition, ToolRegistration, ToolRouter

_SERENA_EDIT_TOOLS = (
    "insert_after_symbol",
    "insert_before_symbol",
    "replace_content",
    "replace_symbol_body",
)


def build_operational_tool_router(
    allowed_tools: list[str] | tuple[str, ...],
    *,
    local_adapter: LocalEditingAdapter,
    terminal_adapter: TerminalAdapter | None = None,
    serena_adapter: SerenaAdapter | None = None,
    trust_boundary: TrustEvaluationResult | None = None,
    cancellation: CommandCancellation | None = None,
) -> ToolRouter:
    """Build an explicit registry; missing optional backends remain unavailable."""

    if not isinstance(local_adapter, LocalEditingAdapter):
        raise TypeError("local_adapter must be an explicit LocalEditingAdapter")
    boundary = trust_boundary
    if boundary is None and terminal_adapter is not None:
        boundary = terminal_adapter.trust_boundary
    if boundary is None:
        boundary = TrustBoundaryEvaluator(local_adapter.path_guard.authorized_root).evaluate(
            force_untrusted=True
        )
    if not isinstance(boundary, TrustEvaluationResult):
        raise TypeError("trust_boundary must be a TrustEvaluationResult or None")
    try:
        boundary.require_root(local_adapter.path_guard.authorized_root)
    except TrustCapabilityDeniedError as exc:
        raise ValueError("local adapter root must match trust boundary") from exc
    registrations = _local_registrations(local_adapter)

    if terminal_adapter is not None:
        if not isinstance(terminal_adapter, TerminalAdapter):
            raise TypeError("terminal_adapter must be a TerminalAdapter or None")
        terminal_guard = getattr(terminal_adapter, "_path_guard", None)
        if terminal_guard is not local_adapter.path_guard:
            raise ValueError("terminal and local adapters must share the same PathGuard instance")
        if terminal_adapter.trust_boundary != boundary:
            raise ValueError("terminal and tool router must share the same trust boundary")
        registrations.update(
            _terminal_registrations(
                terminal_adapter,
                local_adapter,
                cancellation=cancellation,
            )
        )

    if serena_adapter is not None:
        if not isinstance(serena_adapter, SerenaAdapter):
            raise TypeError("serena_adapter must be a SerenaAdapter or None")
        if serena_adapter.authorized_root != local_adapter.path_guard.authorized_root:
            raise ValueError("Serena and local adapters must authorize the same worktree root")
        registrations["serena_edit"] = _registration(
            "serena_edit",
            "Apply one allowlisted semantic edit through an explicitly configured Serena MCP server.",
            {
                "type": "object",
                "properties": {
                    "tool_name": {"type": "string", "enum": list(_SERENA_EDIT_TOOLS)},
                    "relative_path": _path_schema(),
                    "arguments": {"type": "object"},
                },
                "required": ["tool_name", "relative_path", "arguments"],
                "additionalProperties": False,
            },
            lambda payload: _serena_edit(serena_adapter, payload),
            operation="write",
            path_argument="relative_path",
            redaction_context=serena_adapter.redaction_context,
        )

    return ToolRouter(
        allowed_tools,
        registrations=registrations,
        trust_boundary=boundary,
    )


def _local_registrations(adapter: LocalEditingAdapter) -> dict[str, ToolRegistration]:
    return {
        "read_file": _registration(
            "read_file",
            "Read one confined strict UTF-8 file with its real SHA-256 digest.",
            _object_schema({"path": _path_schema()}, required=("path",)),
            lambda payload: _read_file(adapter, payload),
            operation="read",
            path_argument="path",
        ),
        "list_files": _registration(
            "list_files",
            "List a bounded confined directory tree without following directory links.",
            _object_schema(
                {
                    "path": _path_schema(),
                    "max_depth": {"type": "integer", "minimum": 1, "maximum": 32},
                    "max_entries": {"type": "integer", "minimum": 1, "maximum": 10_000},
                }
            ),
            lambda payload: _list_files(adapter, payload),
            operation="list",
            path_argument="path",
            default_path=".",
        ),
        "search_text": _registration(
            "search_text",
            "Search literal text in bounded confined strict UTF-8 files.",
            _object_schema(
                {
                    "query": {"type": "string", "minLength": 1},
                    "path": _path_schema(),
                    "case_sensitive": {"type": "boolean"},
                    "max_results": {"type": "integer", "minimum": 1, "maximum": 10_000},
                    "max_files": {"type": "integer", "minimum": 1, "maximum": 50_000},
                },
                required=("query",),
            ),
            lambda payload: _search_text(adapter, payload),
            operation="search",
            path_argument="path",
            default_path=".",
        ),
        "apply_patch": _registration(
            "apply_patch",
            "Atomically apply one strict single-file unified diff under a digest precondition.",
            _object_schema(
                {
                    "path": _path_schema(),
                    "patch": {"type": "string", "minLength": 1},
                    "expected_sha256": {
                        "type": ["string", "null"],
                        "pattern": "^[0-9a-f]{64}$",
                    },
                },
                required=("path", "patch", "expected_sha256"),
            ),
            lambda payload: _apply_patch(adapter, payload),
            operation="write",
            path_argument="path",
        ),
    }


def _terminal_registrations(
    terminal: TerminalAdapter,
    local: LocalEditingAdapter,
    *,
    cancellation: CommandCancellation | None,
) -> dict[str, ToolRegistration]:
    return {
        "run_command": _registration(
            "run_command",
            "Run one argv command through the injected safe terminal policy.",
            _object_schema(
                {
                    "argv": {
                        "type": "array",
                        "items": {"type": "string", "minLength": 1},
                        "minItems": 1,
                    },
                    "cwd": _path_schema(),
                    "timeout_seconds": {"type": "number", "exclusiveMinimum": 0},
                    "env_allowlist": {
                        "type": "array",
                        "items": {"type": "string", "pattern": "^[A-Za-z_][A-Za-z0-9_]*$"},
                        "uniqueItems": True,
                    },
                    "max_output_bytes": {"type": "integer", "minimum": 1},
                },
                required=("argv", "cwd"),
            ),
            lambda payload: _run_command(terminal, payload, cancellation),
            operation="execute",
            path_argument="cwd",
        ),
        "git_status": _registration(
            "git_status",
            "Inspect the confined worktree status through a fixed read-only Git argv.",
            _object_schema({}),
            lambda payload: _git_status(terminal, payload, cancellation),
            operation="status",
            path_argument="cwd",
            default_path=".",
        ),
        "git_diff": _registration(
            "git_diff",
            "Inspect a confined worktree diff through a fixed read-only Git argv.",
            _object_schema({"path": _path_schema()}),
            lambda payload: _git_diff(terminal, local, payload, cancellation),
            operation="diff",
            path_argument="path",
            default_path=".",
        ),
    }


def _read_file(adapter: LocalEditingAdapter, payload: dict[str, JsonValue]) -> JsonValue:
    snapshot = adapter.read_file(cast(str, payload["path"]))
    return {
        "relative_path": snapshot.relative_path,
        "content": snapshot.content,
        "sha256": snapshot.sha256,
        "size_bytes": snapshot.size_bytes,
    }


def _list_files(adapter: LocalEditingAdapter, payload: dict[str, JsonValue]) -> JsonValue:
    entries = adapter.list_files(
        cast(str, payload.get("path", ".")),
        max_depth=cast(int, payload.get("max_depth", 4)),
        max_entries=cast(int, payload.get("max_entries", 1_000)),
    )
    return cast(JsonValue, list(entries))


def _search_text(adapter: LocalEditingAdapter, payload: dict[str, JsonValue]) -> JsonValue:
    result = adapter.search_text(
        cast(str, payload["query"]),
        cast(str, payload.get("path", ".")),
        case_sensitive=cast(bool, payload.get("case_sensitive", True)),
        max_results=cast(int, payload.get("max_results", 200)),
        max_files=cast(int, payload.get("max_files", 2_000)),
    )
    return cast(JsonValue, result)


def _apply_patch(adapter: LocalEditingAdapter, payload: dict[str, JsonValue]) -> JsonValue:
    result = adapter.apply_patch(
        cast(str, payload["path"]),
        cast(str, payload["patch"]),
        expected_sha256=cast(str | None, payload["expected_sha256"]),
    )
    return {
        "relative_path": result.relative_path,
        "previous_sha256": result.previous_sha256,
        "sha256": result.sha256,
        "size_bytes": result.size_bytes,
        "created": result.created,
    }


def _run_command(
    terminal: TerminalAdapter,
    payload: dict[str, JsonValue],
    cancellation: CommandCancellation | None,
) -> JsonValue:
    request = CommandRequest(
        argv=cast(list[str], payload["argv"]),
        cwd=cast(str, payload["cwd"]),
        timeout_seconds=cast(float, payload.get("timeout_seconds", 30.0)),
        env_allowlist=cast(list[str], payload.get("env_allowlist", [])),
        max_output_bytes=cast(int, payload.get("max_output_bytes", 1_000_000)),
        cancellation=cancellation,
    )
    return _command_result(terminal.execute(request))


def _git_status(
    terminal: TerminalAdapter,
    payload: dict[str, JsonValue],
    cancellation: CommandCancellation | None,
) -> JsonValue:
    del payload
    request = CommandRequest(
        argv=("git", "--no-pager", "status", "--short", "--branch", "--untracked-files=all"),
        cwd=".",
        cancellation=cancellation,
    )
    return _command_result(terminal.execute(request))


def _git_diff(
    terminal: TerminalAdapter,
    local: LocalEditingAdapter,
    payload: dict[str, JsonValue],
    cancellation: CommandCancellation | None,
) -> JsonValue:
    argv = ["git", "--no-pager", "diff", "--no-ext-diff", "--no-color", "--"]
    if "path" in payload:
        guarded = local.path_guard.guard_read(cast(str, payload["path"]))
        argv.append(guarded.relative_path)
    return _command_result(
        terminal.execute(CommandRequest(argv=argv, cwd=".", cancellation=cancellation))
    )


def _serena_edit(adapter: SerenaAdapter, payload: dict[str, JsonValue]) -> JsonValue:
    result = adapter.edit(
        tool_name=cast(str, payload["tool_name"]),
        relative_path=cast(str, payload["relative_path"]),
        arguments=cast(dict[str, Any], payload["arguments"]),
    )
    return {
        "tool_name": result.tool_name,
        "relative_path": result.relative_path,
        "previous_sha256": result.previous_sha256,
        "sha256": result.sha256,
        "size_bytes": result.size_bytes,
        "mcp_result": result.mcp_result,
    }


def _command_result(result: CommandResult) -> JsonValue:
    return {
        "argv": list(result.argv),
        "cwd_relative": result.cwd_relative,
        "exit_code": result.exit_code,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "timed_out": result.timed_out,
        "cancelled": result.cancelled,
        "stdout_truncated": result.stdout_truncated,
        "stderr_truncated": result.stderr_truncated,
    }


def _registration(
    name: str,
    description: str,
    parameters: dict[str, Any],
    handler: Callable[[dict[str, JsonValue]], JsonValue],
    *,
    operation: str,
    path_argument: str | None = None,
    default_path: str | None = None,
    redaction_context: RedactionContext | None = None,
) -> ToolRegistration:
    return ToolRegistration(
        definition=ToolDefinition(
            name=name,
            description=description,
            parameters=cast(dict[str, JsonValue], parameters),
        ),
        handler=handler,
        operation=operation,
        path_argument=path_argument,
        default_path=default_path,
        redaction_context=redaction_context or RedactionContext(),
    )


def _object_schema(
    properties: dict[str, Any],
    *,
    required: tuple[str, ...] = (),
) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        schema["required"] = list(required)
    return schema


def _path_schema() -> dict[str, Any]:
    return {"type": "string", "minLength": 1}


__all__ = ["build_operational_tool_router"]
