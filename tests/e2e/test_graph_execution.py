"""End-to-end F2.3 traversal from YAML compilation to durable terminal state."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import yaml

from ai_engineering_harness.compiler import GraphCompiler
from ai_engineering_harness.contracts import CompiledGraphArtifact
from ai_engineering_harness.contracts.execution import (
    ApprovalStatus,
    ExecutionRecord,
    ExecutionState,
)
from ai_engineering_harness.persistence import AtomicFileStateStorage
from ai_engineering_harness.runtime import (
    DeterministicNodeExecutor,
    GraphExecutor,
    NodeExecutionContext,
    NodeExecutionResult,
    NodeExecutorRegistry,
    RuntimeEngine,
)
from ai_engineering_harness.runtime.maf_adapter import MAFAdapter

_CREATED_AT = datetime(2020, 1, 1, tzinfo=UTC)
_CONFIGURATION_DIGEST = f"sha256:{'0' * 64}"


@dataclass
class _GraphBackend:
    trace: list[str]
    fail_node: str | None = None

    def execute(self, context: NodeExecutionContext) -> NodeExecutionResult:
        node_id = context.node.id
        self.trace.append(node_id)
        previous = context.input_payload.get("trace", [])
        assert isinstance(previous, list)
        output = {"trace": [*previous, node_id]}
        if node_id == self.fail_node:
            return NodeExecutionResult.failed(
                output,
                code="e2e_failure",
                message="controlled E2E failure",
                retryable=False,
            )
        return NodeExecutionResult.completed(output)


def _node(node_id: str, on_success: str, on_failure: str = "failed") -> dict[str, str]:
    return {
        "id": node_id,
        "type": "deterministic",
        "executor": "deterministic_gate",
        "gate_name": node_id,
        "on_success": on_success,
        "on_failure": on_failure,
    }


def _compile(
    project_root: Path,
    name: str,
    nodes: list[dict[str, str]],
) -> tuple[Path, CompiledGraphArtifact]:
    specs = project_root / ".harness" / "graphs" / "specs"
    specs.mkdir(parents=True, exist_ok=True)
    source = specs / f"{name}.yaml"
    source.write_text(
        yaml.safe_dump(
            {
                "graph": {
                    "name": name,
                    "graph_schema_version": "1.0",
                    "definition_version": "1.0.0",
                    "entrypoint": nodes[0]["id"],
                    "status": "stable",
                },
                "nodes": nodes,
                "terminal_states": [
                    {"id": "completed", "outcome": "success"},
                    {"id": "failed", "outcome": "failure"},
                ],
                "policies": [],
                "contracts": [],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    compiled = GraphCompiler(project_root).compile_graph(source, name)
    return compiled, MAFAdapter.load_and_validate(compiled)


def _create_record(
    storage: AtomicFileStateStorage,
    artifact: CompiledGraphArtifact,
    execution_id: str,
) -> None:
    artifact_digest = "sha256:" + hashlib.sha256(
        artifact.canonical_json().encode("utf-8")
    ).hexdigest()
    storage.create_execution(
        ExecutionRecord(
            record_schema_version="1.0",
            revision=0,
            execution_id=execution_id,
            workflow_name=artifact.graph.graph.name,
            artifact_digest=artifact_digest,
            base_commit_sha="a" * 40,
            original_branch="test",
            worktree_path=None,
            current_node_id=artifact.graph.graph.entrypoint,
            current_state=ExecutionState.INITIATED,
            attempt_by_node={},
            created_at=_CREATED_AT,
            updated_at=_CREATED_AT,
            configuration_digest=_CONFIGURATION_DIGEST,
            approval_status=ApprovalStatus.NOT_REQUIRED,
            candidate_commit_sha=None,
            promotion_commit_sha=None,
            failure=None,
        )
    )


def _runtime(
    project_root: Path,
    execution_id: str,
    storage: AtomicFileStateStorage,
    backend: _GraphBackend,
) -> RuntimeEngine:
    graph_executor = GraphExecutor(
        storage,
        NodeExecutorRegistry(
            deterministic=DeterministicNodeExecutor(backend),
        ),
        lock_timeout_seconds=5,
    )
    return RuntimeEngine(
        project_root,
        execution_id,
        allowed_providers=[],
        graph_executor=graph_executor,
    )


def _journal(project_root: Path, execution_id: str) -> list[dict[str, object]]:
    path = (
        project_root
        / ".harness"
        / "state"
        / "executions"
        / execution_id
        / "event-journal.jsonl"
    )
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_linear_three_node_graph_uses_compiled_edges(tmp_path: Path) -> None:
    compiled, artifact = _compile(
        tmp_path,
        "linear-three",
        [
            _node("collect", "build"),
            _node("build", "verify"),
            _node("verify", "completed"),
        ],
    )
    execution_id = "exec-e2e-linear"
    storage = AtomicFileStateStorage(tmp_path)
    _create_record(storage, artifact, execution_id)
    trace: list[str] = []

    result = _runtime(
        tmp_path,
        execution_id,
        storage,
        _GraphBackend(trace),
    ).run_workflow(compiled, initial_input={"trace": []})

    assert trace == ["collect", "build", "verify"]
    assert result.executed_node_ids == ("collect", "build", "verify")
    assert result.outcome == "success"
    assert result.output == {"trace": ["collect", "build", "verify"]}
    record = storage.load_execution(execution_id)
    assert record.current_node_id == "completed"
    assert record.revision == 5
    assert record.current_state == ExecutionState.COMPLETED
    events = _journal(tmp_path, execution_id)
    assert [
        event["details"].get("next_id")
        for event in events
        if event["event_type"] == "NODE_COMPLETED"
    ] == [
        "build",
        "verify",
        "completed",
    ]
    assert [event["event_type"] for event in events] == [
        "STATE_TRANSITIONED",
        "NODE_STARTED",
        "NODE_COMPLETED",
        "NODE_STARTED",
        "NODE_COMPLETED",
        "NODE_STARTED",
        "NODE_COMPLETED",
        "STATE_TRANSITIONED",
    ]


def test_failure_branch_reaches_only_explicit_failure_terminal(tmp_path: Path) -> None:
    compiled, artifact = _compile(
        tmp_path,
        "failure-branch",
        [
            _node("prepare", "quality"),
            _node("quality", "publish"),
            _node("publish", "completed"),
        ],
    )
    execution_id = "exec-e2e-failure"
    storage = AtomicFileStateStorage(tmp_path)
    _create_record(storage, artifact, execution_id)
    trace: list[str] = []

    result = _runtime(
        tmp_path,
        execution_id,
        storage,
        _GraphBackend(trace, fail_node="quality"),
    ).run_workflow(compiled, initial_input={"trace": []})

    assert trace == ["prepare", "quality"]
    assert result.executed_node_ids == ("prepare", "quality")
    assert result.terminal_id == "failed"
    assert result.outcome == "failure"
    assert result.failure is not None
    assert result.failure.code == "e2e_failure"
    record = storage.load_execution(execution_id)
    assert record.current_node_id == "failed"
    assert record.revision == 4
    assert record.current_state == ExecutionState.FAILED
    events = _journal(tmp_path, execution_id)
    assert events[-2]["event_type"] == "NODE_FAILED"
    assert events[-2]["details"]["next_id"] == "failed"
    assert events[-1]["event_type"] == "STATE_TRANSITIONED"
    assert events[-1]["details"]["to_state"] == "FAILED"
