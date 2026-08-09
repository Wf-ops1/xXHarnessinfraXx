"""F4.2 regressions for deterministic Python AST indexing of exact Git commits."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ai_engineering_harness.indexer import PythonAstIndexer, StructuralIndexBuildError


def _git(project_root: Path, *arguments: str, input_bytes: bytes | None = None) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=project_root,
        check=True,
        shell=False,
        capture_output=True,
        input=input_bytes,
    )
    return result.stdout.decode("utf-8", errors="strict").strip()


def _initialize_repository(project_root: Path) -> None:
    _git(project_root, "init", "--quiet")
    _git(project_root, "config", "user.name", "F4.2 Test")
    _git(project_root, "config", "user.email", "f4.2@example.invalid")


def _commit_all(project_root: Path, message: str = "fixture") -> str:
    _git(project_root, "add", "--all")
    _git(project_root, "commit", "--quiet", "-m", message)
    return _git(project_root, "rev-parse", "HEAD").lower()


def test_rebuild_indexes_real_modules_definitions_imports_and_lines(tmp_path: Path) -> None:
    _initialize_repository(tmp_path)
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "__init__.py").write_text(
        "from .service import Service as PublicService\n",
        encoding="utf-8",
    )
    (package / "service.py").write_text(
        """import os.path
from .helpers import item as helper_item

@decorator
class Service:
    @classmethod
    async def build(cls):
        return cls()

    def run(self):
        def nested():
            return 1
        return nested()

def top_level():
    return Service()
""",
        encoding="utf-8",
    )
    commit_sha = _commit_all(tmp_path)

    snapshot = PythonAstIndexer(tmp_path).rebuild()

    assert snapshot.commit_sha == commit_sha
    assert snapshot.status == "ready"
    by_identity = {
        (symbol.kind, symbol.qualified_name, symbol.name): symbol
        for symbol in snapshot.symbols
    }
    assert set(by_identity) == {
        ("module", "pkg", "pkg"),
        ("import", ".service.Service", "PublicService"),
        ("module", "pkg.service", "service"),
        ("import", "os.path", "os"),
        ("import", ".helpers.item", "helper_item"),
        ("class", "pkg.service.Service", "Service"),
        ("method", "pkg.service.Service.build", "build"),
        ("method", "pkg.service.Service.run", "run"),
        ("function", "pkg.service.Service.run.nested", "nested"),
        ("function", "pkg.service.top_level", "top_level"),
    }
    assert by_identity[("class", "pkg.service.Service", "Service")].line_start == 4
    assert by_identity[("method", "pkg.service.Service.build", "build")].line_start == 6
    assert by_identity[("method", "pkg.service.Service.build", "build")].line_end == 8
    assert by_identity[("module", "pkg.service", "service")].line_end == 16
    assert [symbol.model_dump(mode="json") for symbol in snapshot.symbols] == [
        symbol.model_dump(mode="json")
        for symbol in sorted(
            snapshot.symbols,
            key=lambda item: (
                item.path,
                item.line_start,
                item.line_end,
                item.kind,
                item.qualified_name,
                item.name,
            ),
        )
    ]


def test_rebuild_uses_only_commit_blobs_and_is_idempotent(tmp_path: Path) -> None:
    _initialize_repository(tmp_path)
    source = tmp_path / "app.py"
    source.write_text("def committed():\n    return True\n", encoding="utf-8")
    commit_sha = _commit_all(tmp_path)

    source.write_text("def dirty():\n    return False\n", encoding="utf-8")
    (tmp_path / "untracked.py").write_text("def untracked():\n    return None\n", encoding="utf-8")

    indexer = PythonAstIndexer(tmp_path)
    first = indexer.rebuild("HEAD")
    persisted = indexer.snapshot_manager.snapshot_path(commit_sha).read_bytes()
    second = indexer.rebuild(commit_sha)

    assert first == second
    assert indexer.snapshot_manager.snapshot_path(commit_sha).read_bytes() == persisted
    assert {symbol.name for symbol in first.symbols} == {"app", "committed"}
    assert not any(symbol.name in {"dirty", "untracked"} for symbol in first.symbols)


def test_rebuild_skips_committed_symlink_even_when_name_ends_in_python(tmp_path: Path) -> None:
    _initialize_repository(tmp_path)
    (tmp_path / "real.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(tmp_path, "add", "real.py")
    link_object = _git(tmp_path, "hash-object", "-w", "--stdin", input_bytes=b"real.py")
    _git(tmp_path, "update-index", "--add", "--cacheinfo", f"120000,{link_object},linked.py")
    _git(tmp_path, "commit", "--quiet", "-m", "fixture with symlink")

    snapshot = PythonAstIndexer(tmp_path).rebuild()

    assert {symbol.path for symbol in snapshot.symbols} == {"real.py"}
    assert {symbol.name for symbol in snapshot.symbols} == {"real"}


@pytest.mark.parametrize(
    ("path", "content", "message"),
    [
        ("z_broken.py", b"def broken(:\n", "could not be parsed: z_broken.py"),
        (
            "z_encoding.py",
            b"# coding: ascii\nvalue = '\xff'\n",
            "invalid encoding: z_encoding.py",
        ),
    ],
)
def test_source_failure_publishes_no_partial_snapshot(
    tmp_path: Path,
    path: str,
    content: bytes,
    message: str,
) -> None:
    _initialize_repository(tmp_path)
    (tmp_path / "valid.py").write_text("def valid():\n    return True\n", encoding="utf-8")
    (tmp_path / path).write_bytes(content)
    commit_sha = _commit_all(tmp_path)
    indexer = PythonAstIndexer(tmp_path)

    with pytest.raises(StructuralIndexBuildError, match=message):
        indexer.rebuild()

    assert not indexer.snapshot_manager.snapshot_path(commit_sha).exists()
    assert not indexer.snapshot_manager.index_dir.exists()


@pytest.mark.parametrize(
    "tree_record",
    [
        b"100644 blob not-an-object\tbad.py\x00",
        b"100644 blob " + b"a" * 40 + b"\t../bad.py\x00",
        b"malformed\x00",
    ],
)
def test_malformed_git_tree_fails_before_read_or_publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tree_record: bytes,
) -> None:
    _initialize_repository(tmp_path)
    (tmp_path / "valid.py").write_text("VALUE = 1\n", encoding="utf-8")
    commit_sha = _commit_all(tmp_path)
    indexer = PythonAstIndexer(tmp_path)

    monkeypatch.setattr(indexer, "_run_git", lambda operation, *arguments: tree_record)

    with pytest.raises(StructuralIndexBuildError):
        indexer.rebuild()

    assert not indexer.snapshot_manager.snapshot_path(commit_sha).exists()


def test_invalid_revision_and_configuration_fail_without_state(tmp_path: Path) -> None:
    _initialize_repository(tmp_path)
    (tmp_path / "valid.py").write_text("VALUE = 1\n", encoding="utf-8")
    _commit_all(tmp_path)

    with pytest.raises(StructuralIndexBuildError, match="could not be resolved"):
        PythonAstIndexer(tmp_path).rebuild("missing-ref")
    with pytest.raises(StructuralIndexBuildError, match="git_executable"):
        PythonAstIndexer(tmp_path, git_executable=" git ")
    with pytest.raises(StructuralIndexBuildError, match="positive finite"):
        PythonAstIndexer(tmp_path, timeout_seconds=float("inf"))

    assert not (tmp_path / ".harness").exists()
