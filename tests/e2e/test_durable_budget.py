from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ai_engineering_harness.contracts import (
    CompiledGraphArtifact,
    GraphSpec,
    SourceManifestEntry,
)
from ai_engineering_harness.contracts.execution import (
    ApprovalStatus,
    ExecutionRecord,
    ExecutionState,
)
from ai_engineering_harness.core.config import ConfigResolver
from ai_engineering_harness.governance import BudgetLedger, BudgetLimits
from ai_engineering_harness.models.provider import LLMResponse
from ai_engineering_harness.persistence import (
    AtomicFileStateStorage,
    ExecutionBundle,
    canonical_json_digest,
    canonical_json_object,
)
from ai_engineering_harness.runtime import (
    DeterministicNodeExecutor,
    GraphBudgetExceededError,
    GraphExecutor,
    ModelCallMetadata,
    NodeExecutionContext,
    NodeExecutionResult,
    NodeExecutorRegistry,
)

_BASE_TIME = datetime(2026, 8, 13, 20, 0, tzinfo=UTC)
_ZERO_DIGEST = f"sha256:{'0' * 64}"


class _Clock:
    def __init__(self) -> None:
        self._value = _BASE_TIME

    def __call__(self) -> datetime:
        self._value += timedelta(microseconds=1)
        return self._value


class _Ticks:
    def __init__(self) -> None:
        self._value = 10.0

    def __call__(self) -> float:
        self._value += 0.001
        return self._value


class _Ids:
    def __init__(self) -> None:
        self._value = 0

    def __call__(self) -> str:
        self._value += 1
        return f"e2e-event-{self._value}"


class _BudgetedBackend:
    def __init__(self, effects: list[str], *, response_tokens: tuple[int, int]) -> None:
        self.effects = effects
        self.response_tokens = response_tokens

    def execute(self, context: NodeExecutionContext) -> NodeExecutionResult:
        boundary = context.budget_boundary
        assert boundary is not None
        model_handle = boundary.reserve_model("local", "llama3", "abc")
        self.effects.append("model")
        prompt_tokens, completion_tokens = self.response_tokens
        response = LLMResponse(
            content="done",
            provider="local",
            model_name="llama3",
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            response_id=f"response-{len(self.effects)}",
        )
        boundary.commit_model(model_handle, response)

        tool_handle = boundary.reserve_tool("read_file")
        self.effects.append("tool")
        boundary.commit_tool(tool_handle, succeeded=True)
        return NodeExecutionResult.completed(
            {"done": True},
            model_call=ModelCallMetadata.from_response(response),
        )


class _EstimateDeniedBackend:
    def __init__(self, effects: list[str]) -> None:
        self.effects = effects

    def execute(self, context: NodeExecutionContext) -> NodeExecutionResult:
        boundary = context.budget_boundary
        assert boundary is not None
        boundary.reserve_model("local", "llama3", "abc")
        self.effects.append("transport")
        return NodeExecutionResult.completed({"done": True})


def _artifact() -> CompiledGraphArtifact:
    graph = GraphSpec.model_validate(
        {
            "graph": {
                "name": "durable-budget",
                "graph_schema_version": "1.0",
                "definition_version": "1.0.0",
                "entrypoint": "worker",
                "status": "stable",
            },
            "nodes": [
                {
                    "id": "worker",
                    "type": "deterministic",
                    "executor": "deterministic_gate",
                    "gate_name": "worker",
                    "on_success": "completed",
                    "on_failure": "failed",
                }
            ],
            "terminal_states": [
                {"id": "completed", "outcome": "success"},
                {"id": "failed", "outcome": "failure"},
            ],
            "policies": [],
            "contracts": [],
        }
    )
    return CompiledGraphArtifact.build(
        graph=graph,
        resolved_contracts=(),
        resolved_policies=(),
        source_manifest=(
            SourceManifestEntry(
                source_kind="graph",
                source_id="project://durable-budget.yaml",
                content_digest=_ZERO_DIGEST,
            ),
        ),
    )


def _create_execution(
    root: Path,
    *,
    execution_id: str,
    max_tokens: int,
) -> tuple[AtomicFileStateStorage, CompiledGraphArtifact, dict[str, object]]:
    artifact = _artifact()
    configuration = ConfigResolver(root).resolve(
        cli_overrides={
            "budget": {
                "max_tokens": max_tokens,
                "max_prompt_tokens": max_tokens,
                "max_completion_tokens": max_tokens,
                "max_tool_calls": 3,
                "max_duration_ms": 1_000,
                "max_attempts": 2,
                "max_completion_tokens_per_call": 5,
                "model_prices": {
                    "local:llama3": {
                        "prompt_per_million_usd": "1",
                        "completion_per_million_usd": "2",
                    }
                },
                "tool_prices_usd": {"read_file": "0.01"},
            }
        }
    )
    artifact_json = artifact.canonical_json()
    configuration_json = canonical_json_object(configuration)
    initial_input = {"start": True}
    initial_json = canonical_json_object(initial_input)
    bundle = ExecutionBundle(
        bundle_schema_version="1.0",
        execution_id=execution_id,
        artifact_digest=canonical_json_digest(artifact_json),
        configuration_digest=canonical_json_digest(configuration_json),
        initial_input_digest=canonical_json_digest(initial_json),
        artifact_json=artifact_json,
        configuration_json=configuration_json,
    )
    record = ExecutionRecord(
        record_schema_version="1.0",
        revision=0,
        execution_id=execution_id,
        workflow_name=artifact.graph.graph.name,
        artifact_digest=bundle.artifact_digest,
        base_commit_sha="a" * 40,
        original_branch="test",
        worktree_path=None,
        current_node_id="worker",
        current_state=ExecutionState.INITIATED,
        attempt_by_node={},
        created_at=_BASE_TIME,
        updated_at=_BASE_TIME,
        configuration_digest=bundle.configuration_digest,
        approval_status=ApprovalStatus.NOT_REQUIRED,
        candidate_commit_sha=None,
        promotion_commit_sha=None,
        failure=None,
    )
    storage = AtomicFileStateStorage(root)
    storage.create_execution_bundle(bundle, initial_input=initial_input)
    storage.create_execution(record)
    return storage, artifact, configuration


def _executor(
    storage: AtomicFileStateStorage,
    backend: object,
    *,
    clock: _Clock,
    ticks: _Ticks,
) -> GraphExecutor:
    return GraphExecutor(
        storage,
        NodeExecutorRegistry(
            deterministic=DeterministicNodeExecutor(backend),  # type: ignore[arg-type]
        ),
        resume_enabled=True,
        clock=clock,
        monotonic=ticks,
        event_id_factory=_Ids(),
        owner_id_factory=lambda: "durable-budget-e2e",
    )


def test_restart_reconstructs_identical_execution_and_node_balance(tmp_path: Path) -> None:
    storage, artifact, configuration = _create_execution(
        tmp_path,
        execution_id="exec-durable-budget",
        max_tokens=100,
    )
    effects: list[str] = []
    clock = _Clock()
    ticks = _Ticks()
    first = _executor(
        storage,
        _BudgetedBackend(effects, response_tokens=(2, 3)),
        clock=clock,
        ticks=ticks,
    )
    result = first.execute(artifact, "exec-durable-budget", {"start": True})
    assert result.outcome == "success"
    assert effects == ["model", "tool"]

    limits = BudgetLimits.from_effective_config(configuration)
    before = BudgetLedger.replay(
        "exec-durable-budget",
        limits,
        storage.load_events("exec-durable-budget"),
    ).snapshot()
    assert before.usage.total_tokens == 5
    assert before.usage.tool_calls == 1
    assert before.usage.attempts == 1
    assert before.nodes["worker"].usage == before.usage

    restarted = _executor(
        AtomicFileStateStorage(tmp_path),
        _BudgetedBackend(effects, response_tokens=(2, 3)),
        clock=clock,
        ticks=ticks,
    )
    resumed = restarted.resume(artifact, "exec-durable-budget")
    assert resumed.outcome == "success"
    assert effects == ["model", "tool"]
    after = BudgetLedger.replay(
        "exec-durable-budget",
        limits,
        AtomicFileStateStorage(tmp_path).load_events("exec-durable-budget"),
    ).snapshot()
    assert after == before


def test_actual_overage_is_terminal_and_resume_has_no_second_effect(tmp_path: Path) -> None:
    storage, artifact, configuration = _create_execution(
        tmp_path,
        execution_id="exec-budget-overage",
        max_tokens=10,
    )
    effects: list[str] = []
    clock = _Clock()
    ticks = _Ticks()
    executor = _executor(
        storage,
        _BudgetedBackend(effects, response_tokens=(7, 6)),
        clock=clock,
        ticks=ticks,
    )
    with pytest.raises(GraphBudgetExceededError):
        executor.execute(artifact, "exec-budget-overage", {"start": True})
    assert effects == ["model"]
    assert storage.load_execution("exec-budget-overage").current_state == (
        ExecutionState.FAILED_BUDGET_EXCEEDED
    )
    snapshot = BudgetLedger.replay(
        "exec-budget-overage",
        BudgetLimits.from_effective_config(configuration),
        storage.load_events("exec-budget-overage"),
    ).snapshot()
    assert snapshot.usage.total_tokens == 13
    assert snapshot.is_exceeded

    restarted = _executor(
        AtomicFileStateStorage(tmp_path),
        _BudgetedBackend(effects, response_tokens=(1, 1)),
        clock=clock,
        ticks=ticks,
    )
    with pytest.raises(GraphBudgetExceededError):
        restarted.resume(artifact, "exec-budget-overage")
    assert effects == ["model"]


def test_conservative_estimate_denies_without_entering_backend_transport(tmp_path: Path) -> None:
    storage, artifact, _ = _create_execution(
        tmp_path,
        execution_id="exec-budget-preflight",
        max_tokens=5,
    )
    effects: list[str] = []
    executor = _executor(
        storage,
        _EstimateDeniedBackend(effects),
        clock=_Clock(),
        ticks=_Ticks(),
    )
    with pytest.raises(GraphBudgetExceededError):
        executor.execute(artifact, "exec-budget-preflight", {"start": True})
    assert effects == []
    assert storage.load_execution("exec-budget-preflight").current_state == (
        ExecutionState.FAILED_BUDGET_EXCEEDED
    )
