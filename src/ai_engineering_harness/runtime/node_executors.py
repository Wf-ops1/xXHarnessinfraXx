"""Typed, fail-closed node executor boundaries for compiled graphs."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Annotated, ClassVar, Protocol, runtime_checkable

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from ai_engineering_harness.contracts import (
    AgentNodeSpec,
    CompiledGraphArtifact,
    DeterministicNodeSpec,
    HumanApprovalNodeSpec,
    NodeSpec,
    TerminalStateSpec,
)
from ai_engineering_harness.contracts.execution import ExecutionId
from ai_engineering_harness.governance import BudgetBoundary, ToolPolicyDecision
from ai_engineering_harness.models.provider import LLMResponse

_NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
_DigestStr = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]


class NodeExecutorError(Exception):
    """Base class for public node executor failures."""


class NodeExecutorUnavailableError(NodeExecutorError):
    """The selected executor has no operational backend configured."""


class NodeExecutorResultError(NodeExecutorError):
    """A node backend returned a value outside the public result contract."""


class ToolEffectDurabilityError(NodeExecutorError):
    """A tool effect could not be bound to durable write-ahead evidence."""


class ToolEffectAmbiguousError(ToolEffectDurabilityError):
    """A durable tool call has no trustworthy outcome and requires intervention."""


class ToolEffectIntegrityError(ToolEffectDurabilityError):
    """Backend tool evidence diverges from the records written during dispatch."""


class UnsupportedNodeTypeError(NodeExecutorError):
    """No exact executor mapping exists for a node or terminal variant."""


class NodeBackendError(NodeExecutorError):
    """A configured backend failed in a form safe to route through ``on_failure``."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool,
        retry_evidence: RetryEvidence | None = None,
    ) -> None:
        super().__init__(message)
        if retryable and retry_evidence is None:
            raise ValueError("a retryable backend error requires retry evidence")
        if not retryable and retry_evidence is not None:
            raise ValueError("a non-retryable backend error cannot contain retry evidence")
        self.code = code
        self.message = message
        self.retryable = retryable
        self.retry_evidence = retry_evidence


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")


class FailedToolCall(_StrictFrozenModel):
    """Redaction-safe identity of one failed tool invocation."""

    tool_name: _NonEmptyStr
    call_id: _NonEmptyStr | None = None
    arguments_digest: _DigestStr | None = None
    error_code: _NonEmptyStr | None = None


class RetryBudget(_StrictFrozenModel):
    """Remaining retry budget supplied by the active backend policy boundary."""

    remaining_tokens: int = Field(ge=0)
    remaining_cost_usd: float = Field(ge=0)
    remaining_time_seconds: float | None = Field(default=None, ge=0)

    @field_validator("remaining_cost_usd", "remaining_time_seconds")
    @classmethod
    def require_finite_budget_value(cls, value: float | None) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError("remaining retry budget values must be finite")
        return value


class RetryEvidence(_StrictFrozenModel):
    """Raw failure evidence accepted only at the injected backend boundary."""

    model_error: _NonEmptyStr | None = None
    failed_tool_call: FailedToolCall | None = None
    stdout: str = ""
    stderr: str = ""
    failed_gates: tuple[_NonEmptyStr, ...] = ()
    current_diff: str = ""
    remaining_budget: RetryBudget
    correction_instruction: _NonEmptyStr

    @field_validator("failed_gates", mode="before")
    @classmethod
    def freeze_failed_gates(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @field_validator("failed_gates")
    @classmethod
    def require_unique_failed_gates(
        cls,
        value: tuple[str, ...],
    ) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("failed gates must be unique")
        return value

    @model_validator(mode="after")
    def require_actionable_failure_evidence(self) -> RetryEvidence:
        if not any(
            (
                self.model_error,
                self.failed_tool_call,
                self.stdout.strip(),
                self.stderr.strip(),
                self.failed_gates,
                self.current_diff.strip(),
            )
        ):
            raise ValueError("retry evidence must contain an actionable failure signal")
        return self


class RetryContext(_StrictFrozenModel):
    """Redacted evidence delivered to one concrete retry invocation."""

    origin_node_id: _NonEmptyStr
    current_attempt: int = Field(ge=1)
    failed_commit_sha: str | None = Field(default=None, pattern=r"^[0-9a-f]{40}$")
    model_error: _NonEmptyStr | None = None
    failed_tool_call: FailedToolCall | None = None
    redacted_stdout: str
    redacted_stderr: str
    failed_gates: tuple[_NonEmptyStr, ...]
    current_diff: str
    remaining_budget: RetryBudget
    correction_instruction: _NonEmptyStr

    @field_validator("failed_gates", mode="before")
    @classmethod
    def freeze_failed_gates(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @field_validator("failed_gates")
    @classmethod
    def require_unique_failed_gates(
        cls,
        value: tuple[str, ...],
    ) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("failed gates must be unique")
        return value

    @model_validator(mode="after")
    def require_actionable_failure_evidence(self) -> RetryContext:
        if not any(
            (
                self.model_error,
                self.failed_tool_call,
                self.redacted_stdout.strip(),
                self.redacted_stderr.strip(),
                self.failed_gates,
                self.current_diff.strip(),
            )
        ):
            raise ValueError("retry context must contain an actionable failure signal")
        return self


class NodeExecutionFailure(_StrictFrozenModel):
    """Redaction-safe failure returned by a node backend."""

    code: _NonEmptyStr
    message: _NonEmptyStr
    retryable: bool
    retry_evidence: RetryEvidence | None = None

    @model_validator(mode="after")
    def require_matching_retry_evidence(self) -> NodeExecutionFailure:
        if self.retryable and self.retry_evidence is None:
            raise ValueError("a retryable failure requires retry evidence")
        if not self.retryable and self.retry_evidence is not None:
            raise ValueError("a non-retryable failure cannot contain retry evidence")
        return self


class ModelCallMetadata(_StrictFrozenModel):
    """Redaction-safe identity and usage of one completed model call."""

    provider_id: _NonEmptyStr
    model_name: _NonEmptyStr
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    request_id: _NonEmptyStr | None = None
    response_id: _NonEmptyStr

    @model_validator(mode="after")
    def require_consistent_usage(self) -> ModelCallMetadata:
        if self.total_tokens != self.prompt_tokens + self.completion_tokens:
            raise ValueError(
                "total_tokens must equal prompt_tokens + completion_tokens"
            )
        return self

    @classmethod
    def from_response(cls, response: LLMResponse) -> ModelCallMetadata:
        return cls(
            provider_id=response.provider,
            model_name=response.model_name,
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
            total_tokens=response.total_tokens,
            request_id=response.request_id,
            response_id=response.response_id,
        )


class ToolCallIntent(_StrictFrozenModel):
    """Redaction-safe write-ahead identity for one not-yet-dispatched tool call."""

    step: int = Field(ge=1)
    call_id: _NonEmptyStr
    tool_name: _NonEmptyStr
    arguments_digest: _DigestStr
    policy_decision: ToolPolicyDecision


class ToolExecutionRecord(_StrictFrozenModel):
    """Redaction-safe durable evidence for one dispatched tool call."""

    step: int = Field(ge=1)
    call_id: _NonEmptyStr
    tool_name: _NonEmptyStr
    arguments_digest: _DigestStr
    succeeded: bool
    result_digest: _DigestStr
    redacted_result: str = Field(max_length=2_000)
    error_code: _NonEmptyStr | None = None
    policy_decision_digest: _DigestStr
    duration_ms: int = Field(default=0, ge=0)
    estimated_cost_usd: str | None = Field(
        default=None,
        pattern=r"^(0|[1-9][0-9]*)(\.[0-9]+)?$",
    )

    @model_validator(mode="after")
    def require_matching_error(self) -> ToolExecutionRecord:
        if self.succeeded and self.error_code is not None:
            raise ValueError("a successful tool record cannot contain an error code")
        if not self.succeeded and self.error_code is None:
            raise ValueError("a failed tool record requires an error code")
        return self


@runtime_checkable
class ToolEffectRecorder(Protocol):
    """Durable boundary invoked immediately before and after one tool effect."""

    def record_call(self, intent: ToolCallIntent) -> None:
        """Persist a write-ahead call before the operational handler is entered."""

    def record_outcome(self, record: ToolExecutionRecord) -> None:
        """Persist the redacted outcome only after the operational handler returns."""


class NodeExecutionContext(_StrictFrozenModel):
    """Immutable context supplied to exactly one node backend invocation."""

    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="forbid",
        arbitrary_types_allowed=True,
    )

    execution_id: ExecutionId
    artifact: CompiledGraphArtifact
    node: AgentNodeSpec | DeterministicNodeSpec | HumanApprovalNodeSpec | TerminalStateSpec
    attempt: int = Field(ge=0)
    input_payload: dict[str, object]
    fencing_token: int = Field(gt=0)
    retry_context: RetryContext | None = None
    tool_effect_recorder: ToolEffectRecorder | None = Field(
        default=None,
        exclude=True,
        repr=False,
    )
    budget_boundary: BudgetBoundary | None = Field(
        default=None,
        exclude=True,
        repr=False,
    )

    @field_validator("artifact", mode="before")
    @classmethod
    def detach_artifact(cls, value: object) -> CompiledGraphArtifact:
        if not isinstance(value, CompiledGraphArtifact):
            raise TypeError("artifact must be a CompiledGraphArtifact")
        return CompiledGraphArtifact.model_validate_json(value.canonical_json())

    @field_validator("input_payload", mode="before")
    @classmethod
    def detach_input_payload(cls, value: object) -> dict[str, object]:
        return _copy_json_object(value, path="input_payload")

    @field_validator("tool_effect_recorder")
    @classmethod
    def require_durable_recorder(
        cls,
        value: ToolEffectRecorder | None,
    ) -> ToolEffectRecorder | None:
        if value is not None and not isinstance(value, ToolEffectRecorder):
            raise TypeError("tool_effect_recorder must implement ToolEffectRecorder")
        return value

    @field_validator("budget_boundary")
    @classmethod
    def require_budget_boundary(
        cls,
        value: BudgetBoundary | None,
    ) -> BudgetBoundary | None:
        if value is not None and not isinstance(value, BudgetBoundary):
            raise TypeError("budget_boundary must implement BudgetBoundary")
        return value


class NodeExecutionResult(_StrictFrozenModel):
    """One backend outcome and the JSON object forwarded to the selected edge."""

    succeeded: bool
    output: dict[str, object]
    failure: NodeExecutionFailure | None = None
    model_calls: tuple[ModelCallMetadata, ...] = ()
    tool_executions: tuple[ToolExecutionRecord, ...] = ()

    @field_validator("model_calls", "tool_executions", mode="before")
    @classmethod
    def freeze_records(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @field_validator("output", mode="before")
    @classmethod
    def detach_output(cls, value: object) -> dict[str, object]:
        return _copy_json_object(value, path="output")

    @model_validator(mode="after")
    def require_matching_failure(self) -> NodeExecutionResult:
        if self.succeeded and self.failure is not None:
            raise ValueError("a successful node result cannot contain failure details")
        if not self.succeeded and self.failure is None:
            raise ValueError("a failed node result requires failure details")
        expected_steps = tuple(range(1, len(self.tool_executions) + 1))
        if tuple(record.step for record in self.tool_executions) != expected_steps:
            raise ValueError("tool execution steps must be contiguous and start at one")
        call_ids = tuple(record.call_id for record in self.tool_executions)
        if len(set(call_ids)) != len(call_ids):
            raise ValueError("tool execution call IDs must be unique")
        if self.succeeded and any(not record.succeeded for record in self.tool_executions):
            raise ValueError("a successful node result cannot contain a failed tool record")
        response_ids = tuple(record.response_id for record in self.model_calls)
        if len(set(response_ids)) != len(response_ids):
            raise ValueError("model call response IDs must be unique")
        return self

    @property
    def model_call(self) -> ModelCallMetadata | None:
        """Compatibility accessor for the last completed model call."""
        return self.model_calls[-1] if self.model_calls else None

    @classmethod
    def completed(
        cls,
        output: dict[str, object],
        *,
        model_call: ModelCallMetadata | None = None,
        model_calls: tuple[ModelCallMetadata, ...] = (),
        tool_executions: tuple[ToolExecutionRecord, ...] = (),
    ) -> NodeExecutionResult:
        normalised_model_calls = _normalise_model_calls(model_call, model_calls)
        return cls(
            succeeded=True,
            output=output,
            model_calls=normalised_model_calls,
            tool_executions=tool_executions,
        )

    @classmethod
    def failed(
        cls,
        output: dict[str, object],
        *,
        code: str,
        message: str,
        retryable: bool,
        retry_evidence: RetryEvidence | None = None,
        model_call: ModelCallMetadata | None = None,
        model_calls: tuple[ModelCallMetadata, ...] = (),
        tool_executions: tuple[ToolExecutionRecord, ...] = (),
    ) -> NodeExecutionResult:
        normalised_model_calls = _normalise_model_calls(model_call, model_calls)
        return cls(
            succeeded=False,
            output=output,
            failure=NodeExecutionFailure(
                code=code,
                message=message,
                retryable=retryable,
                retry_evidence=retry_evidence,
            ),
            model_calls=normalised_model_calls,
            tool_executions=tool_executions,
        )


@runtime_checkable
class NodeExecutor(Protocol):
    """Stable executor boundary used by ``GraphExecutor``."""

    def ensure_available(self) -> None:
        """Fail before ``NODE_STARTED`` when the operational backend is unavailable."""

    def execute(self, context: NodeExecutionContext) -> NodeExecutionResult:
        """Execute exactly once and return a typed JSON-native outcome."""


@runtime_checkable
class NodeExecutionBackend(Protocol):
    """Operational backend injected into one effectful node executor."""

    def execute(self, context: NodeExecutionContext) -> NodeExecutionResult:
        """Perform the node-specific effect."""


@dataclass(frozen=True, slots=True)
class _BackendNodeExecutor:
    backend: NodeExecutionBackend | None = None
    executor_name: ClassVar[str] = "node"

    def ensure_available(self) -> None:
        if self.backend is None:
            raise NodeExecutorUnavailableError(
                f"{self.executor_name} node executor backend is unavailable"
            )

    def execute(self, context: NodeExecutionContext) -> NodeExecutionResult:
        self.ensure_available()
        assert self.backend is not None
        try:
            result = self.backend.execute(context)
        except NodeBackendError:
            raise
        except NodeExecutorError:
            raise
        except Exception as exc:
            raise NodeBackendError(
                "node_backend_error",
                f"{self.executor_name} node backend failed",
                retryable=False,
            ) from exc
        if not isinstance(result, NodeExecutionResult):
            raise NodeExecutorResultError(
                f"{self.executor_name} node backend returned an invalid result"
            )
        return result


class AgentNodeExecutor(_BackendNodeExecutor):
    """Adapter for an explicitly supplied agent backend."""

    executor_name = "agent"


class DeterministicNodeExecutor(_BackendNodeExecutor):
    """Adapter for an explicitly supplied deterministic backend."""

    executor_name = "deterministic"


class HumanApprovalNodeExecutor(_BackendNodeExecutor):
    """Adapter boundary for human approval without implementing pause/resume."""

    executor_name = "human approval"


class KnowledgeSyncNodeExecutor(_BackendNodeExecutor):
    """Adapter for the existing ``knowledge_updater`` agent role."""

    executor_name = "knowledge sync"


@dataclass(frozen=True, slots=True)
class TerminalNodeExecutor:
    """Resolve an explicit terminal without performing an external effect."""

    def ensure_available(self) -> None:
        return None

    def execute(self, context: NodeExecutionContext) -> NodeExecutionResult:
        if not isinstance(context.node, TerminalStateSpec):
            raise NodeExecutorResultError(
                "terminal node executor requires a TerminalStateSpec"
            )
        if context.node.outcome == "success":
            return NodeExecutionResult.completed(context.input_payload)
        return NodeExecutionResult.failed(
            context.input_payload,
            code="terminal_failure",
            message="graph reached an explicit failure terminal",
            retryable=False,
        )


@dataclass(frozen=True, slots=True)
class NodeExecutorRegistry:
    """Immutable, exhaustive mapping from graph variants to executors."""

    agent: AgentNodeExecutor = field(default_factory=AgentNodeExecutor)
    deterministic: DeterministicNodeExecutor = field(
        default_factory=DeterministicNodeExecutor
    )
    human_approval: HumanApprovalNodeExecutor = field(
        default_factory=HumanApprovalNodeExecutor
    )
    knowledge_sync: KnowledgeSyncNodeExecutor = field(
        default_factory=KnowledgeSyncNodeExecutor
    )
    terminal: TerminalNodeExecutor = field(default_factory=TerminalNodeExecutor)

    def select(self, node: NodeSpec | TerminalStateSpec) -> NodeExecutor:
        if isinstance(node, AgentNodeSpec):
            if node.role == "knowledge_updater":
                return self.knowledge_sync
            return self.agent
        if isinstance(node, DeterministicNodeSpec):
            return self.deterministic
        if isinstance(node, HumanApprovalNodeSpec):
            return self.human_approval
        if isinstance(node, TerminalStateSpec):
            return self.terminal
        raise UnsupportedNodeTypeError(
            f"unsupported node contract: {type(node).__name__}"
        )


def _copy_json_object(value: object, *, path: str) -> dict[str, object]:
    copied = _copy_json_value(value, path=path)
    if not isinstance(copied, dict):
        raise TypeError(f"{path} must be a JSON object")
    return copied


def _normalise_model_calls(
    model_call: ModelCallMetadata | None,
    model_calls: tuple[ModelCallMetadata, ...],
) -> tuple[ModelCallMetadata, ...]:
    if model_call is not None and model_calls:
        raise ValueError("model_call and model_calls cannot be supplied together")
    return (model_call,) if model_call is not None else model_calls


def _copy_json_value(value: object, *, path: str) -> object:
    if value is None or type(value) in {bool, int, str}:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError(f"{path} contains a non-finite number")
        return value
    if type(value) is list:
        return [
            _copy_json_value(item, path=f"{path}[{index}]")
            for index, item in enumerate(value)
        ]
    if type(value) is dict:
        copied: dict[str, object] = {}
        for key, item in value.items():
            if type(key) is not str:
                raise ValueError(f"{path} contains a non-string object key")
            copied[key] = _copy_json_value(item, path=f"{path}.{key}")
        return copied
    raise ValueError(f"{path} contains non-JSON-native value {type(value).__name__}")


__all__ = [
    "AgentNodeExecutor",
    "DeterministicNodeExecutor",
    "FailedToolCall",
    "HumanApprovalNodeExecutor",
    "KnowledgeSyncNodeExecutor",
    "ModelCallMetadata",
    "NodeBackendError",
    "NodeExecutionBackend",
    "NodeExecutionContext",
    "NodeExecutionFailure",
    "NodeExecutionResult",
    "NodeExecutor",
    "NodeExecutorError",
    "NodeExecutorRegistry",
    "NodeExecutorResultError",
    "NodeExecutorUnavailableError",
    "RetryBudget",
    "RetryContext",
    "RetryEvidence",
    "TerminalNodeExecutor",
    "ToolCallIntent",
    "ToolEffectAmbiguousError",
    "ToolEffectDurabilityError",
    "ToolEffectIntegrityError",
    "ToolEffectRecorder",
    "ToolExecutionRecord",
    "UnsupportedNodeTypeError",
]
