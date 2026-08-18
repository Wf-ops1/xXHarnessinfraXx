"""Adaptador para comandos Git seguros."""

from pathlib import Path
from typing import cast

from ai_engineering_harness.tools.adapters.terminal import TerminalAdapter


class GitAdapter:
    """Executa comandos Git com validação prévia de segurança."""

    def __init__(self, repo_path: Path):
        self.repo_path = repo_path

    def get_current_sha(self) -> str:
        res = TerminalAdapter.run_command("git rev-parse HEAD", cwd=str(self.repo_path))
        if res["exit_code"] == 0:
            return cast(str, res["stdout"]).strip()
        return "uncommitted"

    def revert_commit(self, commit_sha: str) -> bool:
        res = TerminalAdapter.run_command(f"git revert --no-edit {commit_sha}", cwd=str(self.repo_path))
        return cast(int, res["exit_code"]) == 0
