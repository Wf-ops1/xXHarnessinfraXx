"""Typed ``details`` payloads for canonical knowledge-sync events."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .execution_event import ExecutionEvent

SnapshotStatus = Literal["pending", "ready", "failed", "corrupted"]


class KnowledgeSyncDetails(BaseModel):
    """Details emitted with ``EventType.KNOWLEDGE_SYNC`` transaction events."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    tx_id: str = Field(description="ID da transação de conhecimento")
    status: str = Field(description="Status da transação (STAGING, PREPARED, COMMITTED)")
    synced_at: datetime = Field(description="Timestamp do sync")
    ki_count: int = Field(description="Quantidade de KIs sincronizadas")


class KnowledgeUpdateDetails(BaseModel):
    """Details for a commit-bound structural knowledge update."""

    event_id: str = Field(description="ID único do evento de atualização")
    execution_id: str = Field(description="ID de execução da funcionalidade/grafo")
    commit_sha: str = Field(description="Hash de 40 caracteres do commit do Git vinculado (identidade primária)")
    git_branch: str = Field(description="Branch do Git onde a mudança ocorreu (metadado de auditoria)")
    merkle_root: str = Field(description="Hash da raiz Merkle do índice estrutural")
    snapshot_status: SnapshotStatus = Field(default="pending", description="Estado do snapshot do índice")
    timestamp: str = Field(description="Carimbo de data/hora ISO 8601")
    changed_artifacts: list[str] = Field(description="Lista de artefatos alterados")


class KnowledgeSyncCompletedDetails(BaseModel):
    """Successful knowledge-sync result embedded in canonical event details."""

    sync_id: str = Field(description="ID da sincronização")
    execution_id: str = Field(description="ID da execução vinculada")
    commit_sha: str = Field(description="Hash do commit do Git sincronizado")
    merkle_root: str = Field(description="Hash da raiz Merkle do novo snapshot do índice")
    snapshot_status: SnapshotStatus = Field(default="ready", description="Estado final do snapshot publicado")
    status: Literal["COMPLETED", "COMPLETED_WITH_WARNINGS"] = Field(description="Resultado da sincronização")
    duration_ms: float = Field(description="Tempo total gasto na sincronização em milissegundos")


class KnowledgeSyncFailedDetails(BaseModel):
    """Failed knowledge-sync result embedded in canonical event details."""

    sync_id: str = Field(description="ID da sincronização")
    execution_id: str = Field(description="ID da execução vinculada")
    commit_sha: str | None = Field(default=None, description="Hash do commit do Git se gerado")
    snapshot_status: SnapshotStatus = Field(default="failed", description="Estado do snapshot marcado como falho")
    error_message: str = Field(description="Descrição detalhada da falha de sincronização")
    recovery_action_taken: str = Field(
        default="revert_and_fail", description="Ação de recuperação executada pelo SyncFailureHandler"
    )
    rollback_triggered: bool = Field(description="Indica se o SyncFailureHandler reverteu as alterações")


# Compatibility symbols resolve to the canonical envelope or explicitly named
# details models; none creates an independent operational event schema.
KnowledgeUpdateEvent = ExecutionEvent
KnowledgeSyncCompleted = KnowledgeSyncCompletedDetails
KnowledgeSyncFailed = KnowledgeSyncFailedDetails

__all__ = [
    "KnowledgeSyncCompleted",
    "KnowledgeSyncCompletedDetails",
    "KnowledgeSyncDetails",
    "KnowledgeSyncFailed",
    "KnowledgeSyncFailedDetails",
    "KnowledgeUpdateDetails",
    "KnowledgeUpdateEvent",
]
