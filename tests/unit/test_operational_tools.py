"""Operational registry proofs for the eight opt-in F3.8 tools."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from ai_engineering_harness.security import PathGuard
from ai_engineering_harness.tools import (
    ToolPayloadValidationError,
    ToolUnauthorizedError,
    ToolUnavailableError,
    build_operational_tool_router,
)
from ai_engineering_harness.tools.adapters import (
    LocalEditingAdapter,
    SerenaAdapter,
    SerenaMcpConfiguration,
    SerenaTransport,
    TerminalAdapter,
)

ROOT = Path(__file__).resolve().parents[2]
SERVER = ROOT / "tests" / "fixtures" / "serena_mcp_server.py"
ALL_TOOLS = (
    "read_file",
    "list_files",
    "search_text",
    "apply_patch",
    "run_command",
    "git_status",
    "git_diff",
    "serena_edit",
)


def _controlled_environment() -> dict[str, str]:
    selected: dict[str, str] = {}
    for wanted in ("PATH", "SYSTEMROOT"):
        for name, value in os.environ.items():
            if name.casefold() == wanted.casefold():
                selected[name] = value
                break
    return selected


def _adapters(
    root: Path,
    *,
    include_git: bool = False,
) -> tuple[LocalEditingAdapter, TerminalAdapter, SerenaAdapter]:
    guard = PathGuard(root)
    executables: dict[str, Path] = {"python": Path(sys.executable).resolve(strict=True)}
    if include_git:
        git = shutil.which("git")
        if git is None:
            pytest.skip("Git executable is unavailable")
        executables["git"] = Path(git).resolve(strict=True)
    local = LocalEditingAdapter(path_guard=guard)
    terminal = TerminalAdapter(
        path_guard=guard,
        executables=executables,
        environment=_controlled_environment(),
    )
    serena = SerenaAdapter(
        path_guard=guard,
        configuration=SerenaMcpConfiguration(
            transport=SerenaTransport.STDIO,
            command=os.fspath(Path(sys.executable).resolve(strict=True)),
            args=(os.fspath(SERVER), os.fspath(root)),
            environment={},
            timeout_seconds=10,
        ),
    )
    return local, terminal, serena


def test_complete_factory_exposes_exact_strict_schemas(tmp_path: Path) -> None:
    local, terminal, serena = _adapters(tmp_path)
    router = build_operational_tool_router(
        list(ALL_TOOLS),
        local_adapter=local,
        terminal_adapter=terminal,
        serena_adapter=serena,
    )

    schemas = router.prepare(ALL_TOOLS)

    assert router.registered_tools == tuple(sorted(ALL_TOOLS))
    assert tuple(schema["name"] for schema in schemas) == ALL_TOOLS
    assert all(schema["parameters"]["additionalProperties"] is False for schema in schemas)
    assert json.loads(json.dumps(schemas)) == list(schemas)


def test_local_handlers_read_search_list_and_apply_a_real_patch(tmp_path: Path) -> None:
    target = tmp_path / "module.py"
    target.write_bytes(b"old value\n")
    local = LocalEditingAdapter(path_guard=PathGuard(tmp_path))
    router = build_operational_tool_router(
        ["read_file", "list_files", "search_text", "apply_patch"],
        local_adapter=local,
    )

    before = router.dispatch("read_file", {"path": "module.py"})
    assert isinstance(before, dict)
    assert before["content"] == "old value\n"
    listed = router.dispatch("list_files", {"max_depth": 1, "max_entries": 10})
    assert listed == [{"depth": 1, "kind": "file", "path": "module.py"}]
    searched = router.dispatch("search_text", {"query": "value", "path": "."})
    assert isinstance(searched, dict)
    assert searched["matches"] == [
        {"column": 5, "line": 1, "path": "module.py", "text": "old value"}
    ]

    patched = router.dispatch(
        "apply_patch",
        {
            "path": "module.py",
            "patch": "--- a/module.py\n+++ b/module.py\n@@ -1 +1 @@\n-old value\n+new value\n",
            "expected_sha256": before["sha256"],
        },
    )

    assert isinstance(patched, dict)
    assert patched["previous_sha256"] == before["sha256"]
    assert target.read_bytes() == b"new value\n"
    assert json.loads(json.dumps(patched)) == patched


def test_missing_backends_and_compiled_deny_policy_fail_closed(tmp_path: Path) -> None:
    local = LocalEditingAdapter(path_guard=PathGuard(tmp_path))
    router = build_operational_tool_router(
        ["read_file", "run_command", "serena_edit"],
        local_adapter=local,
    )

    with pytest.raises(ToolUnavailableError, match="run_command"):
        router.prepare(("run_command",))
    with pytest.raises(ToolUnavailableError, match="serena_edit"):
        router.dispatch(
            "serena_edit",
            {"tool_name": "replace_content", "relative_path": "x.py", "arguments": {}},
        )
    with pytest.raises(ToolUnauthorizedError, match="read_file"):
        router.prepare(("read_file",), effective_denied_tools=("read_file",))
    with pytest.raises(ToolPayloadValidationError, match="read_file"):
        router.dispatch("read_file", {"path": "x.py", "unexpected": True})


def test_run_command_keeps_metacharacters_literal_and_returns_json(tmp_path: Path) -> None:
    local, terminal, _ = _adapters(tmp_path)
    router = build_operational_tool_router(
        ["run_command"],
        local_adapter=local,
        terminal_adapter=terminal,
    )
    marker = tmp_path / "must-not-exist.txt"
    literal = f"literal > {marker.name} && echo unsafe"
    environment_names = list(_controlled_environment())

    result = router.dispatch(
        "run_command",
        {
            "argv": ["python", "-c", "import sys; print(sys.argv[1])", literal],
            "cwd": ".",
            "env_allowlist": environment_names,
            "timeout_seconds": 10,
            "max_output_bytes": 10_000,
        },
    )

    assert isinstance(result, dict)
    assert result["exit_code"] == 0
    assert str(result["stdout"]).strip() == literal
    assert not marker.exists()
    assert json.loads(json.dumps(result)) == result


def test_git_handlers_are_fixed_read_only_argv_over_the_confined_repo(tmp_path: Path) -> None:
    git = shutil.which("git")
    if git is None:
        pytest.skip("Git executable is unavailable")
    subprocess.run([git, "init", "-q", os.fspath(tmp_path)], check=True, shell=False)
    target = tmp_path / "tracked.txt"
    target.write_bytes(b"before\n")
    subprocess.run([git, "-C", os.fspath(tmp_path), "add", "tracked.txt"], check=True, shell=False)
    target.write_bytes(b"after\n")
    local, terminal, _ = _adapters(tmp_path, include_git=True)
    router = build_operational_tool_router(
        ["git_status", "git_diff"],
        local_adapter=local,
        terminal_adapter=terminal,
    )

    status = router.dispatch("git_status", {})
    diff = router.dispatch("git_diff", {"path": "tracked.txt"})

    assert isinstance(status, dict) and status["exit_code"] == 0
    assert "tracked.txt" in str(status["stdout"])
    assert status["argv"] == [
        "git",
        "--no-pager",
        "status",
        "--short",
        "--branch",
        "--untracked-files=all",
    ]
    assert isinstance(diff, dict) and diff["exit_code"] == 0
    assert "-before" in str(diff["stdout"])
    assert "+after" in str(diff["stdout"])
    assert diff["argv"][-2:] == ["--", "tracked.txt"]


def test_serena_registration_calls_real_mcp_and_verifies_the_effect(tmp_path: Path) -> None:
    target = tmp_path / "module.py"
    target.write_bytes(b"old\n")
    local, _, serena = _adapters(tmp_path)
    router = build_operational_tool_router(
        ["serena_edit"],
        local_adapter=local,
        serena_adapter=serena,
    )

    result = router.dispatch(
        "serena_edit",
        {
            "tool_name": "replace_content",
            "relative_path": "module.py",
            "arguments": {"needle": "old", "replacement": "new"},
        },
    )

    assert isinstance(result, dict)
    assert result["previous_sha256"] != result["sha256"]
    assert target.read_bytes() == b"new\n"
    assert json.loads(json.dumps(result)) == result


def test_factory_rejects_adapters_that_do_not_share_one_explicit_boundary(tmp_path: Path) -> None:
    local = LocalEditingAdapter(path_guard=PathGuard(tmp_path))
    terminal = TerminalAdapter(
        path_guard=PathGuard(tmp_path),
        executables={"python": Path(sys.executable).resolve(strict=True)},
        environment=_controlled_environment(),
    )

    with pytest.raises(ValueError, match="same PathGuard"):
        build_operational_tool_router(
            ["run_command"],
            local_adapter=local,
            terminal_adapter=terminal,
        )
