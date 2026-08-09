"""Módulo Indexer: Governança de Inteligência Estrutural com Codebase-Memory MCP."""

from .codebase_memory_adapter import CodebaseMemoryAdapter
from .lease_manager import LeaseManager
from .python_ast_indexer import PythonAstIndexer, StructuralIndexBuildError
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
    "PythonAstIndexer",
    "SnapshotConflictError",
    "SnapshotIntegrityError",
    "SnapshotManager",
    "SnapshotNotFoundError",
    "SnapshotWriteError",
    "StructuralIndexBuildError",
    "StructuralIndexError",
    "resolve_git_commit",
]
