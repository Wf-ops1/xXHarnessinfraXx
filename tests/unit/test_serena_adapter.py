"""Real MCP transport and fail-closed Serena adapter proofs for F3.8."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from ai_engineering_harness.security import PathGuard, PathTraversalError
from ai_engineering_harness.tools.adapters.serena import (
    SerenaAdapter,
    SerenaCapabilityError,
    SerenaConfigurationError,
    SerenaConnectionError,
    SerenaMcpConfiguration,
    SerenaToolExecutionError,
    SerenaTransport,
)

ROOT = Path(__file__).resolve().parents[2]
SERVER = ROOT / "tests" / "fixtures" / "serena_mcp_server.py"


def _stdio_configuration(root: Path, *extra: str, timeout: float = 10.0) -> SerenaMcpConfiguration:
    return SerenaMcpConfiguration(
        transport=SerenaTransport.STDIO,
        command=os.path.abspath(sys.executable),
        args=(os.fspath(SERVER), os.fspath(root), *extra),
        environment={},
        timeout_seconds=timeout,
    )


def _adapter(root: Path, configuration: SerenaMcpConfiguration) -> SerenaAdapter:
    return SerenaAdapter(path_guard=PathGuard(root), configuration=configuration)


@contextmanager
def _http_configuration(root: Path) -> Iterator[SerenaMcpConfiguration]:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    process = subprocess.Popen(
        [
            os.path.abspath(sys.executable),
            os.fspath(SERVER),
            os.fspath(root),
            "--transport",
            "streamable-http",
            "--port",
            str(port),
        ],
        cwd=root,
        env=dict(os.environ),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        shell=False,
    )
    try:
        deadline = time.monotonic() + 10
        while True:
            if process.poll() is not None:
                raise AssertionError("test MCP HTTP server exited before accepting connections")
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                    break
            except OSError:
                if time.monotonic() >= deadline:
                    raise AssertionError("test MCP HTTP server did not start") from None
                time.sleep(0.05)
        yield SerenaMcpConfiguration(
            transport=SerenaTransport.STREAMABLE_HTTP,
            endpoint=f"http://127.0.0.1:{port}/mcp",
            headers={"X-Harness-Test": "f3.8"},
            timeout_seconds=10,
        )
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def test_configuration_requires_one_explicit_safe_transport(tmp_path: Path) -> None:
    executable = os.path.abspath(sys.executable)
    with pytest.raises(SerenaConfigurationError, match="absolute"):
        SerenaMcpConfiguration(transport=SerenaTransport.STDIO, command="python")
    with pytest.raises(SerenaConfigurationError, match="endpoint"):
        SerenaMcpConfiguration(transport=SerenaTransport.STREAMABLE_HTTP)
    with pytest.raises(SerenaConfigurationError, match="credentials"):
        SerenaMcpConfiguration(
            transport=SerenaTransport.STREAMABLE_HTTP,
            endpoint="https://user:secret@example.invalid/mcp",
        )
    with pytest.raises(SerenaConfigurationError, match="finite"):
        SerenaMcpConfiguration(
            transport=SerenaTransport.STDIO,
            command=executable,
            timeout_seconds=float("inf"),
        )
    with pytest.raises(SerenaConfigurationError, match="HTTP header"):
        SerenaMcpConfiguration(
            transport=SerenaTransport.STREAMABLE_HTTP,
            endpoint="http://127.0.0.1:1/mcp",
            headers={"Authorization\nInjected": "value"},
        )
    configured = SerenaMcpConfiguration(
        transport=SerenaTransport.STDIO,
        command=executable,
    )
    assert configured.command == executable


def test_stdio_probe_performs_real_initialize_discovery_and_root_proof(tmp_path: Path) -> None:
    capabilities = _adapter(tmp_path, _stdio_configuration(tmp_path)).probe()

    assert capabilities.transport == "stdio"
    assert capabilities.server_name == "serena-f3.8-test"
    assert capabilities.protocol_version
    assert {"activate_project", "get_active_project", "replace_content"} <= set(capabilities.tools)


def test_stdio_semantic_edit_changes_the_real_target_and_returns_digest_evidence(tmp_path: Path) -> None:
    target = tmp_path / "module.py"
    target.write_bytes(b"VALUE = 'old'\n")
    adapter = _adapter(tmp_path, _stdio_configuration(tmp_path))

    result = adapter.edit(
        tool_name="replace_content",
        relative_path="module.py",
        arguments={"needle": "old", "replacement": "new"},
    )

    assert target.read_bytes() == b"VALUE = 'new'\n"
    assert result.relative_path == "module.py"
    assert result.previous_sha256 != result.sha256
    assert result.size_bytes == len(target.read_bytes())
    assert result.mcp_result["isError"] is False


def test_streamable_http_performs_real_initialize_discovery_root_and_edit(tmp_path: Path) -> None:
    target = tmp_path / "module.py"
    target.write_bytes(b"before\n")
    with _http_configuration(tmp_path) as configuration:
        adapter = _adapter(tmp_path, configuration)
        capabilities = adapter.probe()
        result = adapter.edit(
            tool_name="replace_content",
            relative_path="module.py",
            arguments={"needle": "before", "replacement": "after"},
        )

    assert capabilities.transport == "streamable-http"
    assert capabilities.server_name == "serena-f3.8-test"
    assert target.read_bytes() == b"after\n"
    assert result.previous_sha256 != result.sha256


@pytest.mark.parametrize(
    ("server_option", "message"),
    [
        ("--omit-root", "cannot prove"),
        ("--wrong-root", "does not match"),
        ("--omit-edit", "does not expose"),
    ],
)
def test_missing_capability_and_wrong_active_root_fail_closed(
    tmp_path: Path,
    server_option: str,
    message: str,
) -> None:
    target = tmp_path / "module.py"
    target.write_bytes(b"old\n")
    adapter = _adapter(tmp_path, _stdio_configuration(tmp_path, server_option))

    with pytest.raises(SerenaCapabilityError, match=message):
        adapter.edit(
            tool_name="replace_content",
            relative_path="module.py",
            arguments={"needle": "old", "replacement": "new"},
        )
    assert target.read_bytes() == b"old\n"


def test_server_error_and_unchanged_effect_never_return_success(tmp_path: Path) -> None:
    target = tmp_path / "module.py"
    target.write_bytes(b"old\n")
    adapter = _adapter(tmp_path, _stdio_configuration(tmp_path))

    with pytest.raises(SerenaToolExecutionError, match="reported an error"):
        adapter.edit(
            tool_name="replace_content",
            relative_path="module.py",
            arguments={"needle": "old", "replacement": "new", "fail": True},
        )
    assert target.read_bytes() == b"old\n"

    with pytest.raises(SerenaToolExecutionError, match="without changing"):
        adapter.edit(
            tool_name="replace_content",
            relative_path="module.py",
            arguments={"needle": "missing", "replacement": "new"},
        )
    assert target.read_bytes() == b"old\n"


def test_timeout_path_override_traversal_and_unknown_tool_fail_before_success(tmp_path: Path) -> None:
    target = tmp_path / "module.py"
    target.write_bytes(b"old\n")

    timed = _adapter(tmp_path, _stdio_configuration(tmp_path, timeout=0.25))
    with pytest.raises(SerenaConnectionError, match="timeout"):
        timed.edit(
            tool_name="replace_content",
            relative_path="module.py",
            arguments={"needle": "old", "replacement": "new", "delay_seconds": 2.0},
        )

    adapter = _adapter(tmp_path, _stdio_configuration(tmp_path))
    with pytest.raises(SerenaConfigurationError, match="cannot override"):
        adapter.edit(
            tool_name="replace_content",
            relative_path="module.py",
            arguments={"relative_path": "other.py"},
        )
    with pytest.raises(PathTraversalError):
        adapter.edit(
            tool_name="replace_content",
            relative_path="../module.py",
            arguments={"needle": "old", "replacement": "new"},
        )
    with pytest.raises(SerenaCapabilityError, match="not allowlisted"):
        adapter.edit(
            tool_name="execute_shell_command",
            relative_path="module.py",
            arguments={"command": "whoami"},
        )
    assert target.read_bytes() == b"old\n"


def test_compatibility_wrapper_requires_explicit_tool_and_arguments(tmp_path: Path) -> None:
    target = tmp_path / "module.py"
    target.write_bytes(b"old\n")
    adapter = _adapter(tmp_path, _stdio_configuration(tmp_path))
    result = adapter.edit_file_semantic(
        "module.py",
        {
            "tool_name": "replace_content",
            "arguments": {"needle": "old", "replacement": "new"},
        },
    )
    assert result.sha256 != result.previous_sha256


def test_live_serena_is_opt_in(tmp_path: Path) -> None:
    live_command = os.environ.get("SERENA_MCP_COMMAND")
    if live_command is None:
        pytest.skip("live Serena is opt-in via SERENA_MCP_COMMAND")
    live_args = json.loads(os.environ.get("SERENA_MCP_ARGS", "[]"))
    assert isinstance(live_args, list) and all(isinstance(item, str) for item in live_args)
    live = _adapter(
        tmp_path,
        SerenaMcpConfiguration(
            transport=SerenaTransport.STDIO,
            command=live_command,
            args=tuple(live_args),
            timeout_seconds=30,
        ),
    )
    assert live.probe().tools
