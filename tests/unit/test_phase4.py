"""Testes unitários para a Fase 4 (Tools Router, Sandbox e Indexer Adapter)."""

import subprocess
from pathlib import Path

import pytest

from ai_engineering_harness.indexer import CodebaseMemoryAdapter, PythonAstIndexer
from ai_engineering_harness.tools.router import ToolRouter
from ai_engineering_harness.workspace.sandbox import SandboxProvider


def test_tool_router_permission():
    router = ToolRouter(allowed_tools=["serena_edit"])
    assert router.permissions.is_allowed("serena_edit") is True
    assert router.permissions.is_allowed("terminal_run") is False

    with pytest.raises(PermissionError):
        router.dispatch("terminal_run", {"command": "dir", "cwd": "."})

def test_sandbox_provider_by_platform():
    path = SandboxProvider.get_external_worktree_base_dir("proj-123")
    assert "proj-123" in str(path)
    assert path.is_dir()

def test_codebase_memory_adapter_snapshots(tmp_path: Path):
    subprocess.run(["git", "init", "--quiet"], cwd=tmp_path, check=True, shell=False)
    subprocess.run(["git", "config", "user.name", "Phase 4 Test"], cwd=tmp_path, check=True, shell=False)
    subprocess.run(
        ["git", "config", "user.email", "phase4@example.invalid"], cwd=tmp_path, check=True, shell=False
    )
    (tmp_path / "tracked.py").write_text("def tracked():\n    return True\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.py"], cwd=tmp_path, check=True, shell=False)
    subprocess.run(["git", "commit", "--quiet", "-m", "fixture"], cwd=tmp_path, check=True, shell=False)
    commit_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_path,
        check=True,
        shell=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip().lower()
    snapshot = PythonAstIndexer(tmp_path).rebuild()
    adapter = CodebaseMemoryAdapter(project_root=tmp_path)
    ast1 = adapter.query_ast("get classes", commit_sha="HEAD")
    assert ast1["commit_sha"] == commit_sha
    assert ast1 == snapshot.model_dump(mode="json")
    assert {(symbol["kind"], symbol["qualified_name"]) for symbol in ast1["symbols"]} == {
        ("module", "tracked"),
        ("function", "tracked.tracked"),
    }
    
    # Segunda chamada recupera o mesmo snapshot validado, sem reindexar por efeito colateral.
    ast2 = adapter.query_ast("get classes", commit_sha="HEAD")
    assert ast2 == ast1
