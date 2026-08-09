"""Read adapter for validated structural snapshots."""

from pathlib import Path
from typing import Any

from ai_engineering_harness.indexer.snapshot_manager import (
    SnapshotManager,
    resolve_git_commit,
)


class CodebaseMemoryAdapter:
    """Serve an existing structural snapshot bound to a real Git commit."""

    def __init__(self, project_root: Path, *, git_executable: str = "git"):
        self.project_root = Path(project_root)
        self.git_executable = git_executable
        self.snapshot_manager = SnapshotManager(project_root)

    def query_ast(self, query: str, commit_sha: str) -> dict[str, Any]:
        """Resolve a revision and return only its validated ready snapshot."""

        if type(query) is not str or not query.strip():
            raise ValueError("structural query must be non-empty text")
        resolved_sha = resolve_git_commit(
            self.project_root,
            commit_sha,
            git_executable=self.git_executable,
        )
        snapshot = self.snapshot_manager.require_snapshot(resolved_sha)
        return snapshot.model_dump(mode="json")
