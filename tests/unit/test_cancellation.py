"""Durable cancellation and real process-tree termination proofs for F5.7."""

from __future__ import annotations

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ai_engineering_harness.runtime import (
    CancellationController,
    CancellationRequestedError,
    CancellationStateIntegrityError,
)
from ai_engineering_harness.security import PathGuard
from ai_engineering_harness.tools.adapters import (
    CommandCancelledError,
    CommandRequest,
    TerminalAdapter,
)


def _execution_root(root: Path, execution_id: str) -> Path:
    path = root / ".harness" / "state" / "executions" / execution_id
    path.mkdir(parents=True)
    return path


def _environment() -> dict[str, str]:
    selected: dict[str, str] = {}
    for name in ("PATH", "SYSTEMROOT"):
        for current_name, value in os.environ.items():
            if current_name.casefold() == name.casefold():
                selected[current_name] = value
                break
    return selected


def test_request_is_durable_idempotent_and_waits_for_exact_command(tmp_path: Path) -> None:
    execution_id = "exec-cancellation-durable"
    execution_root = _execution_root(tmp_path, execution_id)
    controller = CancellationController(tmp_path, execution_id)
    observer = CancellationController(tmp_path, execution_id)
    command_id = controller.command_started(("python", "-V"))
    controller.command_spawned(command_id, pid=1234)
    requested_at = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)

    request = observer.request(
        decision_id="decision-cancel-1",
        requested_at=requested_at,
    )
    repeated = controller.request(
        decision_id="decision-cancel-1",
        requested_at=requested_at,
    )

    assert request == repeated
    assert request.active_command_id == command_id
    assert observer.is_cancelled
    policy_payload = json.loads(
        (execution_root / "cancellation-policy.json").read_text(encoding="utf-8")
    )
    request_payload = json.loads(
        (execution_root / "cancellation-request.json").read_text(encoding="utf-8")
    )
    assert policy_payload["decision_id"] == request_payload["decision_id"]
    assert policy_payload["requested_at"] == request_payload["requested_at"]
    with pytest.raises(CancellationRequestedError):
        observer.command_started(("python", "-V"))
    controller.command_finished(command_id, outcome="cancelled", exit_code=1)
    observation = observer.wait_for_quiescence(command_id, timeout_seconds=0.1)
    assert observation.quiescent
    assert observation.termination_observed
    assert observation.outcome == "cancelled"
    assert not (execution_root / "active-command.json").exists()

    with pytest.raises(CancellationStateIntegrityError, match="another"):
        observer.request(
            decision_id="decision-cancel-2",
            requested_at=requested_at,
        )


def test_malformed_request_fails_closed_without_starting_a_command(tmp_path: Path) -> None:
    execution_id = "exec-cancellation-malformed"
    execution_root = _execution_root(tmp_path, execution_id)
    (execution_root / "cancellation-request.json").write_text(
        '{"execution_id":"wrong"}\n',
        encoding="utf-8",
    )
    controller = CancellationController(tmp_path, execution_id)

    assert controller.is_cancelled
    with pytest.raises(CancellationRequestedError):
        controller.command_started(("python", "-V"))
    assert not (execution_root / "active-command.json").exists()


def test_terminal_cancellation_kills_tree_reaps_and_preserves_bounded_evidence(
    tmp_path: Path,
) -> None:
    execution_id = "exec-terminal-cancellation"
    execution_root = _execution_root(tmp_path, execution_id)
    controller = CancellationController(tmp_path, execution_id)
    requester = CancellationController(tmp_path, execution_id)
    environment = _environment()
    adapter = TerminalAdapter(
        path_guard=PathGuard(tmp_path),
        executables={"python": Path(sys.executable).resolve(strict=True)},
        environment=environment,
    )
    marker = tmp_path / "cancelled-child-survived.txt"
    child = (
        "import sys,time; from pathlib import Path; time.sleep(1.2); "
        "Path(sys.argv[1]).write_text('escaped', encoding='utf-8')"
    )
    parent = (
        "import subprocess,sys,time; print('started', flush=True); "
        "subprocess.Popen([sys.executable, '-c', sys.argv[1], sys.argv[2]]); "
        "time.sleep(30)"
    )
    request = CommandRequest(
        argv=("python", "-c", parent, child, str(marker)),
        cwd=".",
        timeout_seconds=10,
        env_allowlist=tuple(environment),
        max_output_bytes=64,
        cancellation=controller,
    )

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(adapter.execute, request)
        deadline = time.monotonic() + 5
        active_path = execution_root / "active-command.json"
        while True:
            if active_path.exists():
                try:
                    active = json.loads(active_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    active = {}
                if active.get("status") == "RUNNING":
                    break
            if time.monotonic() >= deadline:
                pytest.fail("terminal command did not publish its cancellation slot")
            time.sleep(0.02)
        time.sleep(0.2)
        cancellation_request = requester.request(
            decision_id="decision-terminal-cancel",
            requested_at=datetime.now(UTC),
        )
        with pytest.raises(CommandCancelledError) as raised:
            future.result(timeout=10)

    result = raised.value.result
    time.sleep(1.4)
    assert result.cancelled
    assert not result.timed_out
    assert result.exit_code != 0
    assert "started" in result.stdout
    assert len(result.stdout.encode("utf-8")) <= 64
    assert not marker.exists()
    observation = requester.wait_for_quiescence(
        cancellation_request.active_command_id,
        timeout_seconds=0,
    )
    assert observation.quiescent
    assert observation.termination_observed
    assert not (execution_root / "active-command.json").exists()
