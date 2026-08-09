"""Real-process proofs for the F3.5 safe terminal adapter."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from ai_engineering_harness.security import PathGuard, PathOutsideRootError, PathTraversalError
from ai_engineering_harness.tools.adapters import (
    CommandRequest,
    CommandValidationError,
    EnvironmentNotAllowedError,
    ExecutableNotAllowedError,
    LegacyShellCommandError,
    TerminalAdapter,
)


def _controlled_environment(**extra: str) -> dict[str, str]:
    environment: dict[str, str] = {}
    for name in ("PATH", "SYSTEMROOT"):
        for current_name, value in os.environ.items():
            if current_name.casefold() == name.casefold():
                environment[current_name] = value
                break
    environment.update(extra)
    return environment


def _adapter(root: Path, **environment: str) -> TerminalAdapter:
    return TerminalAdapter(
        path_guard=PathGuard(root),
        executables={"python": Path(sys.executable).resolve(strict=True)},
        environment=_controlled_environment(**environment),
    )


def _base_environment_names(adapter_environment: dict[str, str]) -> tuple[str, ...]:
    return tuple(adapter_environment)


def test_request_is_normalized_immutable_and_rejects_ambiguous_values() -> None:
    request = CommandRequest(argv=["python", "-V"], cwd=Path("."), env_allowlist=["PATH"])

    assert request.argv == ("python", "-V")
    assert request.cwd == "."
    assert request.env_allowlist == ("PATH",)
    with pytest.raises(FrozenInstanceError):
        request.cwd = "elsewhere"  # type: ignore[misc]

    invalid_requests = (
        {"argv": [], "cwd": "."},
        {"argv": "python", "cwd": "."},
        {"argv": ["python", ""], "cwd": "."},
        {"argv": ["python", "bad\x00arg"], "cwd": "."},
        {"argv": ["python"], "cwd": ".", "timeout_seconds": float("inf")},
        {"argv": ["python"], "cwd": ".", "timeout_seconds": True},
        {"argv": ["python"], "cwd": ".", "env_allowlist": ["PATH", "path"]},
        {"argv": ["python"], "cwd": ".", "max_output_bytes": 0},
    )
    for kwargs in invalid_requests:
        with pytest.raises(CommandValidationError):
            CommandRequest(**kwargs)  # type: ignore[arg-type]


def test_real_argv_execution_never_interprets_shell_metacharacters(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment = _controlled_environment()
    adapter = TerminalAdapter(
        path_guard=PathGuard(tmp_path),
        executables={"python": Path(sys.executable).resolve(strict=True)},
        environment=environment,
    )
    marker = tmp_path / "shell-marker.txt"
    payload = f"literal > {marker.name} && echo unsafe"
    original_popen = subprocess.Popen
    observed_shell: list[bool] = []

    def observing_popen(*args: object, **kwargs: object) -> subprocess.Popen[bytes]:
        observed_shell.append(bool(kwargs.get("shell")))
        return original_popen(*args, **kwargs)  # type: ignore[call-overload,return-value]

    monkeypatch.setattr(subprocess, "Popen", observing_popen)
    result = adapter.execute(
        CommandRequest(
            argv=("python", "-c", "import sys; print(sys.argv[1])", payload),
            cwd=".",
            env_allowlist=_base_environment_names(environment),
        )
    )

    assert result.exit_code == 0
    assert result.stdout.strip() == payload
    assert result.argv[-1] == payload
    assert result.cwd_relative == "."
    assert observed_shell == [False]
    assert not marker.exists()


def test_executable_and_environment_policy_fail_before_effect(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path, HARNESS_ALLOWED="visible")
    marker = tmp_path / "must-not-exist.txt"
    code = f"from pathlib import Path; Path({str(marker)!r}).write_text('unsafe')"

    with pytest.raises(ExecutableNotAllowedError, match="not allowed"):
        adapter.execute(CommandRequest(argv=("other-python", "-c", code), cwd="."))
    with pytest.raises(EnvironmentNotAllowedError, match="not allowed"):
        adapter.execute(
            CommandRequest(
                argv=("python", "-c", code),
                cwd=".",
                env_allowlist=("HARNESS_FORBIDDEN",),
            )
        )
    assert not marker.exists()


def test_cwd_is_confined_and_must_be_an_existing_directory(tmp_path: Path) -> None:
    root = tmp_path / "worktree"
    outside = tmp_path / "outside"
    regular_file = root / "file.txt"
    root.mkdir()
    outside.mkdir()
    regular_file.write_text("x", encoding="utf-8")
    adapter = _adapter(root)

    with pytest.raises(PathTraversalError):
        adapter.execute(CommandRequest(argv=("python", "-V"), cwd="../outside"))
    with pytest.raises(PathOutsideRootError):
        adapter.execute(CommandRequest(argv=("python", "-V"), cwd=str(outside.resolve())))
    with pytest.raises(CommandValidationError, match="directory"):
        adapter.execute(CommandRequest(argv=("python", "-V"), cwd="file.txt"))


def test_environment_is_exactly_selected_and_dynamic_values_are_redacted(tmp_path: Path) -> None:
    secret = "terminal-secret-value-123456"
    environment = _controlled_environment(
        HARNESS_SECRET=secret,
        HARNESS_NOT_REQUESTED="must-not-be-inherited",
    )
    adapter = TerminalAdapter(
        path_guard=PathGuard(tmp_path),
        executables={"python": Path(sys.executable).resolve(strict=True)},
        environment=environment,
    )
    selected_names = tuple(
        name for name in environment if name.casefold() != "harness_not_requested"
    )
    code = (
        "import os; "
        "print(os.environ['HARNESS_SECRET']); "
        "print(os.environ.get('HARNESS_NOT_REQUESTED', 'missing'))"
    )

    result = adapter.execute(
        CommandRequest(
            argv=("python", "-c", code),
            cwd=".",
            env_allowlist=selected_names,
        )
    )

    assert result.exit_code == 0
    assert secret not in result.stdout
    assert "[REDACTED_HARNESS_SECRET]" in result.stdout
    assert result.stdout.rstrip().endswith("missing")


def test_stdout_and_stderr_are_independently_bounded_and_exit_code_is_preserved(
    tmp_path: Path,
) -> None:
    adapter = _adapter(tmp_path)
    code = (
        "import sys; "
        "sys.stdout.write('o' * 10000); "
        "sys.stderr.write('e' * 10000); "
        "sys.exit(7)"
    )

    result = adapter.execute(
        CommandRequest(
            argv=("python", "-c", code),
            cwd=".",
            max_output_bytes=64,
        )
    )

    assert result.exit_code == 7
    assert not result.timed_out
    assert result.stdout_truncated
    assert result.stderr_truncated
    assert len(result.stdout.encode("utf-8")) <= 64
    assert len(result.stderr.encode("utf-8")) <= 64


def test_timeout_kills_the_spawned_process_tree(tmp_path: Path) -> None:
    environment = _controlled_environment()
    adapter = TerminalAdapter(
        path_guard=PathGuard(tmp_path),
        executables={"python": Path(sys.executable).resolve(strict=True)},
        environment=environment,
    )
    marker = tmp_path / "child-survived.txt"
    child_code = (
        "import time; from pathlib import Path; "
        f"time.sleep(1.5); Path({str(marker)!r}).write_text('alive', encoding='utf-8')"
    )
    parent_code = (
        "import subprocess, sys, time; "
        "subprocess.Popen([sys.executable, '-c', sys.argv[1]]); "
        "time.sleep(30)"
    )

    result = adapter.execute(
        CommandRequest(
            argv=("python", "-c", parent_code, child_code),
            cwd=".",
            timeout_seconds=0.3,
            env_allowlist=_base_environment_names(environment),
        )
    )
    time.sleep(1.8)

    assert result.timed_out
    assert result.exit_code != 0
    assert not marker.exists()


def test_timeout_tree_remains_contained_under_repetition_and_multiple_children(
    tmp_path: Path,
) -> None:
    environment = _controlled_environment()
    adapter = TerminalAdapter(
        path_guard=PathGuard(tmp_path),
        executables={"python": Path(sys.executable).resolve(strict=True)},
        environment=environment,
    )
    child_code = (
        "import sys, time; from pathlib import Path; "
        "time.sleep(0.45); Path(sys.argv[1]).write_text('escaped', encoding='utf-8')"
    )
    parent_code = (
        "import subprocess, sys, time; child = sys.argv[1]; "
        "[subprocess.Popen([sys.executable, '-c', child, marker]) "
        "for marker in sys.argv[2:]]; time.sleep(30)"
    )

    for attempt in range(5):
        markers = tuple(
            tmp_path / f"attempt-{attempt}-child-{child_index}.txt"
            for child_index in range(4)
        )
        result = adapter.execute(
            CommandRequest(
                argv=(
                    "python",
                    "-c",
                    parent_code,
                    child_code,
                    *(str(marker) for marker in markers),
                ),
                cwd=".",
                timeout_seconds=0.15,
                env_allowlist=_base_environment_names(environment),
            )
        )
        time.sleep(0.55)

        assert result.timed_out
        assert result.exit_code != 0
        assert not any(marker.exists() for marker in markers)


def test_legacy_shell_string_api_fails_closed(tmp_path: Path) -> None:
    marker = tmp_path / "legacy-marker.txt"

    with pytest.raises(LegacyShellCommandError, match="shell-string execution is disabled"):
        TerminalAdapter.run_command(f"echo unsafe > {marker}", cwd=str(tmp_path))
    assert not marker.exists()
