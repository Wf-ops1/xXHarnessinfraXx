"""F4.1 regressions for canonical, commit-bound structural snapshots."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from ai_engineering_harness.contracts.structural_index import StructuralSnapshot, StructuralSymbol
from ai_engineering_harness.indexer import (
    CodebaseMemoryAdapter,
    GitCommitResolutionError,
    SnapshotConflictError,
    SnapshotIntegrityError,
    SnapshotManager,
    SnapshotNotFoundError,
    SnapshotWriteError,
    resolve_git_commit,
)
from ai_engineering_harness.persistence.base import canonical_json_digest, canonical_json_object

_SHA_A = "a" * 40
_SHA_B = "b" * 40


def _symbol(name: str = "run") -> dict[str, object]:
    return {
        "kind": "function",
        "name": name,
        "qualified_name": f"sample.{name}",
        "path": "src/sample.py",
        "line_start": 3,
        "line_end": 7,
    }


def _git(project_root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=project_root,
        check=True,
        shell=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout.strip()


def _initialize_git_repository(project_root: Path) -> str:
    _git(project_root, "init", "--quiet")
    _git(project_root, "config", "user.name", "F4.1 Test")
    _git(project_root, "config", "user.email", "f4.1@example.invalid")
    (project_root / "tracked.py").write_text("def tracked():\n    return True\n", encoding="utf-8")
    _git(project_root, "add", "tracked.py")
    _git(project_root, "commit", "--quiet", "-m", "fixture")
    return _git(project_root, "rev-parse", "HEAD").lower()


def test_snapshot_round_trip_uses_one_canonical_sha_path(tmp_path: Path) -> None:
    manager = SnapshotManager(tmp_path)

    path = manager.save_snapshot(_SHA_A, [_symbol()])
    snapshot = manager.require_snapshot(_SHA_A)

    assert path == (
        tmp_path / ".harness" / "state" / "structural-index" / "snapshots" / f"{_SHA_A}.json"
    )
    assert path.read_text(encoding="utf-8") == snapshot.canonical_json()
    assert snapshot.commit_sha == _SHA_A
    assert snapshot.status == "ready"
    assert snapshot.symbols == (StructuralSymbol.model_validate(_symbol()),)
    assert not (path.parent.parent / "snapshot_HEAD.json").exists()
    assert not (path.parent.parent / "HEAD.json").exists()


def test_snapshot_identity_and_symbol_schema_are_strict(tmp_path: Path) -> None:
    manager = SnapshotManager(tmp_path)

    with pytest.raises(SnapshotIntegrityError, match="commit_sha"):
        manager.save_snapshot("HEAD", [_symbol()])
    with pytest.raises(SnapshotIntegrityError, match="commit_sha"):
        manager.save_snapshot("ABC123", [_symbol()])
    with pytest.raises(SnapshotIntegrityError, match="symbols"):
        manager.save_snapshot(_SHA_A, ["run"])
    with pytest.raises(SnapshotIntegrityError, match="line_start"):
        manager.save_snapshot(_SHA_A, [{**_symbol(), "line_start": "3"}])
    with pytest.raises(SnapshotIntegrityError, match="relative POSIX"):
        manager.save_snapshot(_SHA_A, [{**_symbol(), "path": "../outside.py"}])
    with pytest.raises(SnapshotIntegrityError, match="normalized relative POSIX"):
        manager.save_snapshot(_SHA_A, [{**_symbol(), "path": "src//sample.py"}])
    with pytest.raises(ValidationError, match="extra_forbidden"):
        StructuralSymbol.model_validate({**_symbol(), "classes": []})


def test_loader_rejects_digest_status_identity_and_canonicality_tampering(tmp_path: Path) -> None:
    manager = SnapshotManager(tmp_path)
    path = manager.save_snapshot(_SHA_A, [_symbol()])

    digest_tampered = json.loads(path.read_text(encoding="utf-8"))
    digest_tampered["symbols"][0]["name"] = "changed"
    path.write_text(canonical_json_object(digest_tampered), encoding="utf-8")
    with pytest.raises(SnapshotIntegrityError, match="digest"):
        manager.get_snapshot(_SHA_A)

    invalid_status_content = {
        "commit_sha": _SHA_A,
        "schema_version": "1.0",
        "status": "building",
        "symbols": [_symbol()],
    }
    invalid_status = {
        **invalid_status_content,
        "digest": canonical_json_digest(canonical_json_object(invalid_status_content)),
    }
    path.write_text(canonical_json_object(invalid_status), encoding="utf-8")
    with pytest.raises(SnapshotIntegrityError, match="status"):
        manager.get_snapshot(_SHA_A)

    path.write_text(StructuralSnapshot.create(_SHA_B, [_symbol()]).canonical_json(), encoding="utf-8")
    with pytest.raises(SnapshotIntegrityError, match="requested identity"):
        manager.get_snapshot(_SHA_A)

    valid = StructuralSnapshot.create(_SHA_A, [_symbol()])
    path.write_text(json.dumps(valid.model_dump(mode="json")), encoding="utf-8")
    with pytest.raises(SnapshotIntegrityError, match="not canonical JSON"):
        manager.get_snapshot(_SHA_A)


def test_snapshot_write_is_idempotent_but_never_overwrites_conflicting_content(tmp_path: Path) -> None:
    manager = SnapshotManager(tmp_path)
    first = manager.save_snapshot(_SHA_A, [_symbol("first")])
    original = first.read_bytes()

    assert manager.save_snapshot(_SHA_A, [_symbol("first")]) == first
    with pytest.raises(SnapshotConflictError, match="immutable commit identity"):
        manager.save_snapshot(_SHA_A, [_symbol("second")])
    assert first.read_bytes() == original


def test_atomic_write_failure_leaves_no_snapshot_or_temporary_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = SnapshotManager(tmp_path)

    def fail_replace(source: Path, destination: Path) -> None:
        raise OSError("injected replace failure")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(SnapshotWriteError, match="atomically"):
        manager.save_snapshot(_SHA_A, [_symbol()])

    assert not manager.snapshot_path(_SHA_A).exists()
    assert list(manager.index_dir.glob("*.tmp")) == []


def test_git_revision_is_resolved_before_adapter_storage_or_serving(tmp_path: Path) -> None:
    real_sha = _initialize_git_repository(tmp_path)
    manager = SnapshotManager(tmp_path)
    adapter = CodebaseMemoryAdapter(tmp_path)

    assert resolve_git_commit(tmp_path, "HEAD") == real_sha
    assert resolve_git_commit(tmp_path, "HEAD~0") == real_sha
    with pytest.raises(GitCommitResolutionError):
        resolve_git_commit(tmp_path, "--verify")
    with pytest.raises(GitCommitResolutionError):
        resolve_git_commit(tmp_path, "missing-ref")

    with pytest.raises(SnapshotNotFoundError, match=real_sha):
        adapter.query_ast("get_structure", "HEAD")
    assert not manager.index_dir.exists()

    manager.save_snapshot(real_sha, [_symbol()])
    served = adapter.query_ast("get_structure", "HEAD")
    assert served["commit_sha"] == real_sha
    assert served["symbols"] == [_symbol()]
    assert not (manager.index_dir / "HEAD.json").exists()
