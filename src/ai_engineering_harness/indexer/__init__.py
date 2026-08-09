"""Módulo Indexer: Governança de Inteligência Estrutural com Codebase-Memory MCP."""

from .codebase_memory_adapter import CodebaseMemoryAdapter
from .lease_manager import LeaseManager
from .snapshot_manager import (
    GitCommitResolutionError,
    SnapshotConflictError,
    SnapshotIntegrityError,
    SnapshotManager,
    SnapshotNotFoundError,
    SnapshotWriteError,
    StructuralIndexError,
    resolve_git_commit,
)

__all__ = [
    "CodebaseMemoryAdapter",
    "GitCommitResolutionError",
    "LeaseManager",
    "SnapshotConflictError",
    "SnapshotIntegrityError",
    "SnapshotManager",
    "SnapshotNotFoundError",
    "SnapshotWriteError",
    "StructuralIndexError",
    "resolve_git_commit",
]
