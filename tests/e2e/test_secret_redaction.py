"""End-to-end F5.5 secret injection and persisted-evidence sentinels."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

import pytest

from ai_engineering_harness.security import (
    PathGuard,
    SecretGrant,
    TrustAuthorization,
    TrustBoundaryEvaluator,
)
from ai_engineering_harness.tools.adapters import (
    CommandRequest,
    EnvironmentNotAllowedError,
    TerminalAdapter,
)
from ai_engineering_harness.tools.adapters.serena import (
    SerenaAdapter,
    SerenaMcpConfiguration,
    SerenaTransport,
)

_SECRET_NAME = "HARNESS_E2E_SECRET"
_SECRET = "opaqueSecretValue987654321"
_ROOT = Path(__file__).resolve().parents[2]
_SERENA_SERVER = _ROOT / "tests" / "fixtures" / "serena_mcp_server.py"


def _controlled_environment(**extra: str) -> dict[str, str]:
    environment: dict[str, str] = {}
    for expected in ("PATH", "SYSTEMROOT"):
        for name, value in os.environ.items():
            if name.casefold() == expected.casefold():
                environment[name] = value
                break
    environment.update(extra)
    return environment


def test_real_subprocess_receives_secret_but_public_snapshot_is_clean(
    tmp_path: Path,
) -> None:
    environment = _controlled_environment(**{_SECRET_NAME: _SECRET})
    adapter = TerminalAdapter(
        path_guard=PathGuard(tmp_path),
        executables={"python": Path(sys.executable).resolve(strict=True)},
        environment=environment,
    )
    result = adapter.execute(
        CommandRequest(
            argv=(
                "python",
                "-c",
                (
                    "import os; value=os.environ['HARNESS_E2E_SECRET']; "
                    "print('prefix-' + value[:12]); print(value[12:])"
                ),
            ),
            cwd=".",
            env_allowlist=(_SECRET_NAME,),
            max_output_bytes=32,
        )
    )

    snapshot = tmp_path / "public-evidence.json"
    snapshot.write_text(
        json.dumps(asdict(result), ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    persisted = snapshot.read_bytes()

    assert result.exit_code == 0
    assert result.stdout_truncated is True
    assert _SECRET not in result.stdout
    assert "opaqueSecret" not in result.stdout
    assert "Value987654321" not in result.stdout
    assert _SECRET.encode() not in persisted
    assert b"opaqueSecret" not in persisted
    assert b"Value987654321" not in persisted
    assert _SECRET.encode() not in result.stderr.encode()
    assert all(_SECRET.encode() not in path.read_bytes() for path in tmp_path.rglob("*") if path.is_file())


def test_mismatched_terminal_consumer_prevents_process_effect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization = TrustAuthorization(
        repository_root=str(tmp_path.resolve()),
        executable_aliases=("python",),
        secret_grants=(
            SecretGrant(
                name=_SECRET_NAME,
                consumers=("provider:openai",),
            ),
        ),
    )
    boundary = TrustBoundaryEvaluator(
        tmp_path,
        authorization=authorization,
    ).evaluate()
    adapter = TerminalAdapter(
        path_guard=PathGuard(tmp_path),
        executables={"python": Path(sys.executable).resolve(strict=True)},
        environment=_controlled_environment(**{_SECRET_NAME: _SECRET}),
        trust_boundary=boundary,
    )

    def fail_if_spawned(*_args: object, **_kwargs: object) -> subprocess.Popen[bytes]:
        raise AssertionError("process spawned before exact secret-consumer authorization")

    monkeypatch.setattr(subprocess, "Popen", fail_if_spawned)
    with pytest.raises(EnvironmentNotAllowedError, match="consumer"):
        adapter.execute(
            CommandRequest(
                argv=("python", "-c", "print('must-not-run')"),
                cwd=".",
                env_allowlist=(_SECRET_NAME,),
            )
        )


def test_real_serena_process_receives_secret_and_redacts_mcp_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "module.py"
    target.write_text("before\n", encoding="utf-8")
    monkeypatch.setenv("SERENA_MCP_TOKEN", _SECRET)
    boundary = TrustBoundaryEvaluator(
        tmp_path,
        authorization=TrustAuthorization(
            repository_root=str(tmp_path.resolve()),
            secret_grants=(
                SecretGrant(
                    name="SERENA_MCP_TOKEN",
                    consumers=("tool:serena",),
                ),
            ),
        ),
    ).evaluate()
    configuration = SerenaMcpConfiguration(
        transport=SerenaTransport.STDIO,
        command=os.path.abspath(sys.executable),
        args=(os.fspath(_SERENA_SERVER), os.fspath(tmp_path)),
        secret_environment={"SERENA_TOKEN": "SERENA_MCP_TOKEN"},
        timeout_seconds=10,
    )
    adapter = SerenaAdapter(
        path_guard=PathGuard(tmp_path),
        configuration=configuration,
        trust_boundary=boundary,
    )

    result = adapter.edit(
        tool_name="replace_content",
        relative_path="module.py",
        arguments={
            "needle": "before",
            "replacement": "after",
            "echo_environment": "SERENA_TOKEN",
        },
    )
    serialized = json.dumps(result.mcp_result, ensure_ascii=False, sort_keys=True)

    assert target.read_text(encoding="utf-8") == "after\n"
    assert _SECRET not in serialized
    assert "opaqueSecret" not in serialized
    assert "REDACTED_SERENA_MCP_TOKEN" in serialized
