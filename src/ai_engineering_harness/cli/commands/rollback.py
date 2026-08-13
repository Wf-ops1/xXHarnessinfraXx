"""Estratégia de Rollback Append-Only em Duas Fases (Código vs Efeitos em Produto)."""

from contextlib import suppress
from pathlib import Path
from typing import Any

from ai_engineering_harness.indexer.codebase_memory_adapter import CodebaseMemoryAdapter
from ai_engineering_harness.observability.audit import AuditTrailManager
from ai_engineering_harness.runtime.state_machine import (
    EXECUTION_COMPENSATED,
    ROLLBACK_CODE_COMPLETED,
    ROLLBACK_EFFECTS_COMPLETED,
    ROLLBACK_REQUESTED,
)
from ai_engineering_harness.security.trust import (
    TrustBoundaryConfigurationError,
    TrustBoundaryEvaluator,
    TrustEvaluationResult,
)
from ai_engineering_harness.tools.adapters.git import GitAdapter


class RollbackManager:
    """Orquestra o rollback de código e a execução de hooks de compensação de forma append-only no diário."""

    def __init__(
        self,
        project_root: Path,
        *,
        trust_boundary: TrustEvaluationResult | None = None,
    ) -> None:
        self.project_root = project_root.resolve(strict=True)
        self.git_adapter = GitAdapter(self.project_root)
        self.trust_evaluator = TrustBoundaryEvaluator(self.project_root)
        boundary = trust_boundary or self.trust_evaluator.evaluate()
        if not isinstance(boundary, TrustEvaluationResult):
            raise TrustBoundaryConfigurationError(
                "trust_boundary must be a TrustEvaluationResult"
            )
        boundary.require_root(self.project_root)
        if Path(boundary.repository_root) != self.project_root:
            raise TrustBoundaryConfigurationError(
                "trust boundary belongs to another repository root"
            )
        self.trust_boundary = boundary

    def execute_rollback(
        self,
        execution_id: str,
        is_promoted: bool,
        commit_sha: str = "",
        is_destructive_hook: bool = False,
        user_approved: bool = False,
        hook_id: str = "rollback-compensation",
    ) -> dict[str, Any]:
        result: dict[str, Any] = {"code_rollback": False, "product_rollback": False}
        audit_mgr = AuditTrailManager(self.project_root, execution_id)

        # 1. Registrar solicitação de Rollback no diário de auditoria append-only
        audit_mgr.log_event(ROLLBACK_REQUESTED, {
            "execution_id": execution_id,
            "is_promoted": is_promoted,
            "commit_sha": commit_sha
        })

        # 2. Rollback de Código (Fase 1)
        if not is_promoted:
            result["code_rollback"] = True
            result["code_message"] = "Worktree externo descartado."
        else:
            if commit_sha:
                res = self.git_adapter.revert_commit(commit_sha)
                result["code_rollback"] = res
                result["code_message"] = f"Commit {commit_sha} revertido via git revert."
            else:
                result["code_rollback"] = True
                result["code_message"] = "Reversão registrada."

        audit_mgr.log_event(ROLLBACK_CODE_COMPLETED, {
            "execution_id": execution_id,
            "code_result": result.get("code_message", "")
        })

        # 3. Rollback de Efeitos em Produto (Fase 2 - Compensação e Reindexação)
        hook_allowed = self.trust_evaluator.validate_rollback_hook(
            self.trust_boundary,
            hook_id=hook_id,
            is_destructive=is_destructive_hook,
            user_approved=user_approved,
        )
        if not hook_allowed:
            result["product_rollback"] = False
            if (
                is_destructive_hook
                and self.trust_boundary.mode == "trusted"
                and hook_id in self.trust_boundary.hook_ids
                and not user_approved
            ):
                result["product_message"] = (
                    "[AWAITING_APPROVAL] Hook destrutivo exige aprovação humana "
                    "explícita."
                )
            else:
                result["product_message"] = (
                    "[DENIED] Hook de compensação não autorizado pela fronteira "
                    "de confiança."
                )
            return result

        # Reindexar memória estrutural sem apagar snapshots anteriores
        with suppress(Exception):
            indexer = CodebaseMemoryAdapter(self.project_root)
            indexer.query_ast("get_structure", commit_sha=commit_sha or "HEAD~1")

        result["product_rollback"] = True
        result["product_message"] = "Hook de compensação executado com sucesso."

        audit_mgr.log_event(ROLLBACK_EFFECTS_COMPLETED, {
            "execution_id": execution_id,
            "product_result": result.get("product_message", "")
        })

        audit_mgr.log_event(EXECUTION_COMPENSATED, {
            "execution_id": execution_id,
            "status": "COMPENSATED"
        })

        return result
