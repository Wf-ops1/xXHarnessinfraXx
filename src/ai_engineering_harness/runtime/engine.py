"""Fail-closed facade for loading and executing compiled graphs."""

from __future__ import annotations

from pathlib import Path

from ai_engineering_harness.contracts.execution import ExecutionRecord
from ai_engineering_harness.verification import VerificationSuiteResult

from .execution_lifecycle import (
    ExecutionInspection,
    ExecutionLifecycleService,
    ExecutionStatusView,
)
from .graph_executor import (
    GraphExecutionError,
    GraphExecutionPausedResult,
    GraphExecutionResult,
    GraphExecutor,
)
from .maf_adapter import MAFAdapter


class RuntimeGraphConfigurationError(GraphExecutionError):
    """The legacy runtime call lacks explicit F2.3 execution dependencies."""


class RuntimeEngine:
    """Load a canonical artifact and delegate traversal to ``GraphExecutor``.

    The legacy constructor arguments remain accepted so existing imports and callers fail
    explicitly at execution time instead of falling back to the removed synthetic workflow.
    Operational CLI wiring, execution creation, approval and resume belong to F2.4/F2.5.
    """

    def __init__(
        self,
        project_root: Path,
        execution_id: str,
        allowed_providers: list[str],
        *,
        graph_executor: GraphExecutor | None = None,
        lifecycle_service: ExecutionLifecycleService | None = None,
    ) -> None:
        self.project_root = project_root
        self.execution_id = execution_id
        self.allowed_providers = tuple(allowed_providers)
        self.graph_executor = graph_executor
        self.lifecycle_service = lifecycle_service

    def run_workflow(
        self,
        compiled_maf_path: Path,
        approval_required: bool = False,
        intent: str = "Execute workflow",
        *,
        initial_input: dict[str, object] | None = None,
    ) -> GraphExecutionResult:
        """Validate the artifact and delegate without legacy side effects."""
        if approval_required:
            raise RuntimeGraphConfigurationError(
                "approval execution belongs to F2.4/F2.5 and is not configured",
                execution_id=self.execution_id,
            )
        if self.graph_executor is None:
            raise RuntimeGraphConfigurationError(
                "GraphExecutor must be supplied explicitly",
                execution_id=self.execution_id,
            )
        if initial_input is None:
            raise RuntimeGraphConfigurationError(
                "initial_input must be supplied explicitly",
                execution_id=self.execution_id,
            )

        artifact = MAFAdapter.load_and_validate(compiled_maf_path)
        result = self.graph_executor.execute(
            artifact,
            self.execution_id,
            initial_input,
        )
        if isinstance(result, GraphExecutionPausedResult):
            raise RuntimeGraphConfigurationError(
                "approval pause requires ExecutionLifecycleService",
                execution_id=self.execution_id,
            )
        return result

    def start_execution(
        self,
        compiled_artifact_path: Path,
        *,
        initial_input: dict[str, object],
        configuration: dict[str, object] | None = None,
    ) -> GraphExecutionResult | GraphExecutionPausedResult:
        """Create and run through the canonical F2.5 lifecycle service."""
        service = self._require_lifecycle()
        return service.start(
            compiled_artifact_path,
            initial_input=initial_input,
            execution_id=self.execution_id,
            configuration=configuration,
        )

    def resume_execution(self) -> GraphExecutionResult | GraphExecutionPausedResult:
        """Resume the configured execution from its immutable bundle."""
        return self._require_lifecycle().resume(self.execution_id)

    def verify_execution(self) -> VerificationSuiteResult:
        """Run the policy-derived suite through the canonical lifecycle guard."""

        return self._require_lifecycle().verify(self.execution_id)

    def approve_execution(self, *, approver: str) -> ExecutionRecord:
        """Approve the configured canonical execution subject."""
        return self._require_lifecycle().approve(self.execution_id, approver=approver)

    def cancel_execution(self) -> ExecutionRecord:
        """Cancel the configured execution under its lifecycle lock."""
        return self._require_lifecycle().cancel(self.execution_id)

    def status_execution(self) -> ExecutionStatusView:
        """Return the canonical status view."""
        return self._require_lifecycle().status(self.execution_id)

    def inspect_execution(self) -> ExecutionInspection:
        """Return the canonical redaction-safe inspection view."""
        return self._require_lifecycle().inspect(self.execution_id)

    def _require_lifecycle(self) -> ExecutionLifecycleService:
        if self.lifecycle_service is None:
            raise RuntimeGraphConfigurationError(
                "ExecutionLifecycleService must be supplied explicitly",
                execution_id=self.execution_id,
            )
        return self.lifecycle_service


__all__ = ["RuntimeEngine", "RuntimeGraphConfigurationError"]
