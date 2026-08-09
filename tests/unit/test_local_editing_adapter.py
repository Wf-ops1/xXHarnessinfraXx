"""Real positive and negative proofs for the confined local editing adapter."""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

import pytest

from ai_engineering_harness.security import (
    GitMetadataPathError,
    PathGuard,
    PathGuardError,
    PathOutsideRootError,
    PathSizeLimitError,
    PathTraversalError,
)
from ai_engineering_harness.tools.adapters.local_editing import (
    LocalEditingAdapter,
    LocalEditingConfigurationError,
    NoFileChangeError,
    PatchValidationError,
    StaleFileError,
    TextFileError,
)


def _digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _adapter(root: Path, *, max_read: int = 1_000_000, max_write: int = 1_000_000) -> LocalEditingAdapter:
    return LocalEditingAdapter(
        path_guard=PathGuard(
            root,
            max_read_bytes=max_read,
            max_write_bytes=max_write,
        )
    )


def _directory_link(link: Path, target: Path) -> None:
    if os.name == "nt":
        created = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
            check=False,
            shell=False,
            text=True,
        )
        assert created.returncode == 0, created.stderr or created.stdout
        return
    link.symlink_to(target, target_is_directory=True)


def _remove_directory_link(link: Path) -> None:
    if os.name == "nt":
        link.rmdir()
    else:
        link.unlink()


def test_read_file_returns_real_utf8_content_digest_and_relative_path(tmp_path: Path) -> None:
    target = tmp_path / "src" / "hello.py"
    target.parent.mkdir()
    target.write_bytes("print('olá')\n".encode())

    result = _adapter(tmp_path).read_file("src/hello.py")

    assert result.relative_path == "src/hello.py"
    assert result.content == "print('olá')\n"
    assert result.size_bytes == len(target.read_bytes())
    assert result.sha256 == _digest(target.read_bytes())


def test_read_rejects_non_utf8_directory_and_size_limit(tmp_path: Path) -> None:
    (tmp_path / "binary.bin").write_bytes(b"\xff\xfe")
    (tmp_path / "large.txt").write_text("12345", encoding="utf-8")

    with pytest.raises(TextFileError, match="strict UTF-8"):
        _adapter(tmp_path).read_file("binary.bin")
    with pytest.raises(TextFileError, match="regular file"):
        _adapter(tmp_path).read_file(".")
    with pytest.raises(PathSizeLimitError):
        _adapter(tmp_path, max_read=4).read_file("large.txt")


def test_list_files_is_bounded_sorted_and_does_not_recurse_symlink_dirs(tmp_path: Path) -> None:
    (tmp_path / "b").mkdir()
    (tmp_path / "b" / "two.txt").write_text("two\n", encoding="utf-8")
    (tmp_path / "a.txt").write_text("one\n", encoding="utf-8")
    link = tmp_path / "linked-b"
    _directory_link(link, tmp_path / "b")
    try:
        entries = _adapter(tmp_path).list_files(max_depth=4, max_entries=10)

        assert [entry["path"] for entry in entries] == ["a.txt", "b", "b", "b/two.txt"]
        assert sum(entry["kind"] == "symlink" for entry in entries) == 1
        with pytest.raises(LocalEditingConfigurationError, match="max_entries"):
            _adapter(tmp_path).list_files(max_entries=1)
    finally:
        _remove_directory_link(link)


def test_list_and_search_reject_external_symlink_escape(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret\n", encoding="utf-8")
    escape = root / "escape"
    _directory_link(escape, outside)

    adapter = _adapter(root)
    try:
        with pytest.raises(PathOutsideRootError):
            adapter.list_files()
        with pytest.raises(PathOutsideRootError):
            adapter.search_text("secret")
    finally:
        _remove_directory_link(escape)


def test_search_text_returns_locations_and_reports_non_utf8_files(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("Alpha alpha\nnone\n", encoding="utf-8")
    (tmp_path / "b.bin").write_bytes(b"\xff")

    result = _adapter(tmp_path).search_text(
        "alpha",
        case_sensitive=False,
        max_results=10,
        max_files=10,
    )

    assert [(item["line"], item["column"]) for item in result["matches"]] == [(1, 1), (1, 7)]
    assert result["skipped"] == [{"path": "b.bin", "reason": "NON_UTF8_OR_NON_REGULAR"}]
    assert result["truncated"] is False
    assert result["files_scanned"] == 2


def test_search_text_limits_results_and_rejects_ambiguous_query(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("x x x\n", encoding="utf-8")
    adapter = _adapter(tmp_path)

    result = adapter.search_text("x", max_results=2)
    assert len(result["matches"]) == 2
    assert result["truncated"] is True
    with pytest.raises(LocalEditingConfigurationError, match="single-line"):
        adapter.search_text("x\ny")


def test_apply_patch_updates_existing_file_atomically_with_digest_evidence(tmp_path: Path) -> None:
    target = tmp_path / "hello.py"
    target.write_bytes(b"one\ntwo\n")
    before = target.read_bytes()
    patch = """--- a/hello.py
+++ b/hello.py
@@ -1,2 +1,2 @@
 one
-two
+three
"""

    result = _adapter(tmp_path).apply_patch(
        "hello.py",
        patch,
        expected_sha256=_digest(before),
    )

    assert target.read_text(encoding="utf-8") == "one\nthree\n"
    assert result.relative_path == "hello.py"
    assert result.previous_sha256 == _digest(before)
    assert result.sha256 == _digest(b"one\nthree\n")
    assert result.created is False
    assert list(tmp_path.glob("*.f3-8.tmp")) == []


def test_apply_patch_creates_non_empty_file_without_creating_parents(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    patch = """--- /dev/null
+++ b/src/new.py
@@ -0,0 +1,2 @@
+VALUE = 1
+print(VALUE)
"""

    result = _adapter(tmp_path).apply_patch("src/new.py", patch, expected_sha256=None)

    assert (tmp_path / "src" / "new.py").read_text(encoding="utf-8") == "VALUE = 1\nprint(VALUE)\n"
    assert result.created is True
    assert result.previous_sha256 is None

    missing_parent_patch = patch.replace("src/new.py", "missing/new.py")
    with pytest.raises((PatchValidationError, FileNotFoundError, PathGuardError)):
        _adapter(tmp_path).apply_patch("missing/new.py", missing_parent_patch, expected_sha256=None)


@pytest.mark.parametrize(
    ("patch", "message"),
    [
        ("--- a/a.txt\n+++ b/b.txt\n@@ -1 +1 @@\n-old\n+new\n", "header"),
        ("--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-wrong\n+new\n", "context"),
        ("--- a/a.txt\n+++ b/a.txt\n", "hunk"),
        ("--- a/a.txt\n+++ /dev/null\n@@ -1 +0,0 @@\n-old\n", "deletion"),
        ("--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n old\n", "no content change"),
    ],
)
def test_apply_patch_rejects_malformed_wrong_target_delete_and_noop(
    tmp_path: Path,
    patch: str,
    message: str,
) -> None:
    target = tmp_path / "a.txt"
    target.write_bytes(b"old\n")
    error = NoFileChangeError if message == "no content change" else PatchValidationError
    with pytest.raises(error):
        _adapter(tmp_path).apply_patch("a.txt", patch, expected_sha256=_digest(b"old\n"))
    assert target.read_text(encoding="utf-8") == "old\n"


def test_apply_patch_rejects_stale_digest_traversal_git_and_write_limit(tmp_path: Path) -> None:
    target = tmp_path / "a.txt"
    target.write_bytes(b"old\n")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_bytes(b"old\n")
    patch = "--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-old\n+new value\n"

    with pytest.raises(StaleFileError):
        _adapter(tmp_path).apply_patch("a.txt", patch, expected_sha256="0" * 64)
    with pytest.raises(PathTraversalError):
        _adapter(tmp_path).apply_patch("../a.txt", patch, expected_sha256=_digest(b"old\n"))
    git_patch = patch.replace("a/a.txt", "a/.git/config").replace("b/a.txt", "b/.git/config")
    with pytest.raises(GitMetadataPathError):
        _adapter(tmp_path).apply_patch(
            ".git/config",
            git_patch,
            expected_sha256=_digest(b"old\n"),
        )
    with pytest.raises(PathSizeLimitError):
        _adapter(tmp_path, max_write=4).apply_patch(
            "a.txt",
            patch,
            expected_sha256=_digest(b"old\n"),
        )
    assert target.read_text(encoding="utf-8") == "old\n"


def test_apply_patch_detects_a_file_change_during_final_revalidation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "a.txt"
    target.write_bytes(b"old\n")
    adapter = _adapter(tmp_path)
    original = LocalEditingAdapter._revalidate_before_write

    def race(self: LocalEditingAdapter, raw_path: str, **kwargs: object) -> None:
        target.write_bytes(b"raced\n")
        original(self, raw_path, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(LocalEditingAdapter, "_revalidate_before_write", race)
    patch = "--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-old\n+new\n"

    with pytest.raises(StaleFileError, match="changed before publication"):
        adapter.apply_patch("a.txt", patch, expected_sha256=_digest(b"old\n"))
    assert target.read_text(encoding="utf-8") == "raced\n"
