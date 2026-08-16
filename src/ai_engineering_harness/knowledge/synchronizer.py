"""Sincronizador de KIs do projeto."""

from pathlib import Path
from typing import Any

from ai_engineering_harness.knowledge.transaction import KnowledgeTransactionManager


class KnowledgeSynchronizer:
    """Orquestra a sincronização atômica de KIs."""

    def __init__(self, project_root: Path):
        self.tx_mgr = KnowledgeTransactionManager(project_root)

    def sync_ki(self, tx_id: str, ki_data: dict[str, Any]) -> str:
        commit_sha = self.tx_mgr.resolve_repository_head()
        return self.tx_mgr.execute_transaction(tx_id, ki_data, commit_sha=commit_sha)
