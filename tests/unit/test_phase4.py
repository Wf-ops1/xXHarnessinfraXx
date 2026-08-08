"""Testes unitários para a Fase 4 (Tools Router, Sandbox e Indexer Adapter)."""

from pathlib import Path

import pytest

from ai_engineering_harness.indexer.codebase_memory_adapter import CodebaseMemoryAdapter
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
    adapter = CodebaseMemoryAdapter(project_root=tmp_path)
    ast1 = adapter.query_ast("get classes", commit_sha="sha-111")
    assert ast1["commit_sha"] == "sha-111"
    
    # Segunda chamada recupera do snapshot salvo no disco
    ast2 = adapter.query_ast("get classes", commit_sha="sha-111")
    assert ast2 == ast1
