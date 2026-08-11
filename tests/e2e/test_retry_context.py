"""End-to-end F2.6 retry context, durability, and exhaustion tests."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from ai_engineering_harness.compiler import GraphCompiler
from ai_engineering_harness.contracts.events import ExecutionEvent
from ai_engineering_harness.contracts.execution import ExecutionState
from ai_engineering_harness.persistence import (
    AtomicFileStateStorage,
    ExecutionLock,
    StateWriteError,
)
from ai_engineering_harness.runtime import (
    DeterministicNodeExecutor,
    ExecutionLifecycleService,
    GraphExecutionResult,
    NodeExecutionContext,
    NodeExecutionResult,
    NodeExecutorRegistry,
    RetryBudget,
    RetryContext,
    RetryEvidence,
    RetryExhaustedError,
)

_SECRET = "token=f2-six-e2e-secret"


def _evidence() -> RetryEvidence:
    return RetryEvidence(
        model_error="model produced a patch that failed verification",
        stdout=f"pytest output {_SECRET}",
        stderr=f"verification error {_SECRET}",
        failed_gates=("pytest",),
        current_diff=f"+ accidental {_SECRET}",
        remaining_budget=RetryBudget(
            remaining_tokens=800,
            remaining_cost_usd=4.0,
        ),
        correction_instruction="repair the failed test using the attached evidence",
    )


@dataclass
class _RetryBackend:
    trace: list[tuple[str, int, RetryContext | None]]
    fail_attempts: dict[str, set[int]]

    def execute(self, context: NodeExecutionContext) -> NodeExecutionResult:
        self.trace.append((context.node.id, context.attempt, context.retry_context))
        previous = context.input_payload.get("trace", [])
        assert isinstance(previous, list)
        output: dict[str, object] = {
            "trace": [*previous, f"{context.node.id}:{context.attempt}"]
        }
        if context.attempt in self.fail_attempts.get(context.node.id, set()):
            return NodeExecutionResult.failed(
                output,
                code="e2e_retryable_failure",
                message="verification failed",
                retryable=True,
                retry_evidence=_evidence(),
            )
        return NodeExecutionResult.completed(output)


class _InterruptBeforeRetryStartStorage(AtomicFileStateStorage):
    def __init__(self, project_root: Path) -> None:
        super().__init__(project_root)
        self.node_starts = 0
        self.interrupt = True

    def append_event(
        self,
        execution_id: str,
        event: ExecutionEvent,
        *,
        lock: ExecutionLock | None = None,
    ) -> ExecutionEvent:
        if event.event_type == "NODE_STARTED":
            self.node_starts += 1
            if self.interrupt and self.node_starts == 3:
                self.interrupt = False
                raise StateWriteError(
                    "simulated crash before correction retry start",
                    execution_id=execution_id,
                )
        return super().append_event(execution_id, event, lock=lock)


def _compiled_cycle(project_root: Path, *, workflow: str, self_loop: bool) -> Path:
    source = project_root / f"{workflow}.yaml"
    nodes = (
        """  - id: loop
    type: deterministic
    executor: deterministic_gate
    gate_name: loop
    on_success: completed
    on_failure: loop
    retry_policy:
      max_iterations: 2
      exit_condition: gate_passes
"""
        if self_loop
        else """  - id: code
    type: deterministic
    executor: deterministic_gate
    gate_name: code
    on_success: verify
    on_failure: code
    retry_policy:
      max_iterations: 2
      exit_condition: gates_pass
  - id: verify
    type: deterministic
    executor: deterministic_gate
    gate_name: verify
    on_success: completed
    on_failure: code
    retry_policy:
      max_iterations: 2
      exit_condition: gates_pass
"""
    )
    entrypoint = "loop" if self_loop else "code"
    source.write_text(
        f"""graph:
  name: {workflow}
  graph_schema_version: "1.0"
  definition_version: "1.0.0"
  entrypoint: {entrypoint}
  status: stable
nodes:
{nodes}terminal_states:
  - id: completed
    outcome: success
  - id: failed
    outcome: failure
policies: []
contracts: []
""",
        encoding="utf-8",
    )
    return GraphCompiler(project_root).compile_graph(source, workflow)


def _service(
    root: Path,
    storage: AtomicFileStateStorage,
    backend: _RetryBackend,
) -> ExecutionLifecycleService:
    return ExecutionLifecycleService(
        root,
        storage,
        NodeExecutorRegistry(
            deterministic=DeterministicNodeExecutor(backend),
        ),
        git_identity_provider=lambda: ("a" * 40, "task/f2.6-retry-context"),
    )


def test_retry_context_survives_crash_and_corrects_on_second_attempt(
    tmp_path: Path,
) -> None:
    compiled = _compiled_cycle(
        tmp_path,
        workflow="retry-resume-e2e",
        self_loop=False,
    )
    storage = _InterruptBeforeRetryStartStorage(tmp_path)
    trace: list[tuple[str, int, RetryContext | None]] = []
    backend = _RetryBackend(trace, {"verify": {1}})
    service = _service(tmp_path, storage, backend)

    with pytest.raises(StateWriteError, match="before correction retry start"):
        service.start(
            compiled,
            execution_id="exec-retry-resume-e2e",
            initial_input={"trace": []},
            configuration={},
        )

    record_before = storage.load_execution("exec-retry-resume-e2e")
    assert record_before.current_node_id == "code"
    assert record_before.attempt_by_node == {"code": 1, "verify": 1}
    assert [(node, attempt) for node, attempt, _ in trace] == [
        ("code", 1),
        ("verify", 1),
    ]

    result = service.resume("exec-retry-resume-e2e")

    assert isinstance(result, GraphExecutionResult)
    assert result.outcome == "success"
    assert [(node, attempt) for node, attempt, _ in trace] == [
        ("code", 1),
        ("verify", 1),
        ("code", 2),
        ("verify", 2),
    ]
    assert trace[2][2] is not None
    assert trace[3][2] is not None
    assert trace[2][2].origin_node_id == "verify"
    assert trace[3][2].origin_node_id == "verify"
    assert _SECRET not in trace[2][2].model_dump_json()
    record = storage.load_execution("exec-retry-resume-e2e")
    assert record.current_state == ExecutionState.VERIFYING
    assert record.attempt_by_node == {"code": 2, "verify": 2}
    secret_bytes = _SECRET.encode("utf-8")
    assert all(
        secret_bytes not in path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    )


def test_retry_exhaustion_is_terminal_and_does_not_repeat_effect(
    tmp_path: Path,
) -> None:
    compiled = _compiled_cycle(
        tmp_path,
        workflow="retry-exhausted-e2e",
        self_loop=True,
    )
    storage = AtomicFileStateStorage(tmp_path)
    trace: list[tuple[str, int, RetryContext | None]] = []
    service = _service(
        tmp_path,
        storage,
        _RetryBackend(trace, {"loop": {1, 2, 3}}),
    )

    with pytest.raises(RetryExhaustedError):
        service.start(
            compiled,
            execution_id="exec-retry-exhausted-e2e",
            initial_input={"trace": []},
            configuration={},
        )

    record = storage.load_execution("exec-retry-exhausted-e2e")
    assert record.current_state == ExecutionState.FAILED_RETRY_EXHAUSTED
    assert record.attempt_by_node == {"loop": 2}
    journal_before = storage.load_events("exec-retry-exhausted-e2e")
    with pytest.raises(RetryExhaustedError):
        service.resume("exec-retry-exhausted-e2e")
    assert [(node, attempt) for node, attempt, _ in trace] == [
        ("loop", 1),
        ("loop", 2),
    ]
    assert storage.load_events("exec-retry-exhausted-e2e") == journal_before
