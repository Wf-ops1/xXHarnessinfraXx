"""Deterministic Python AST indexing for one exact Git commit tree."""

from __future__ import annotations

import ast
import io
import math
import os
import re
import subprocess
import tokenize
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Final

from ai_engineering_harness.contracts.structural_index import (
    StructuralSnapshot,
    StructuralSymbol,
    StructuralSymbolKind,
)
from ai_engineering_harness.indexer.snapshot_manager import (
    GitCommitResolutionError,
    SnapshotManager,
    StructuralIndexError,
    resolve_git_commit,
)

_GIT_OBJECT_ID: Final = re.compile(r"^[0-9a-f]{40}$")
_REGULAR_BLOB_MODES: Final = frozenset({"100644", "100755"})


class StructuralIndexBuildError(StructuralIndexError):
    """The committed Python tree could not be converted into a complete snapshot."""


@dataclass(frozen=True, slots=True)
class _GitBlob:
    path: str
    object_id: str


class PythonAstIndexer:
    """Rebuild structural symbols from regular Python blobs in an exact commit."""

    def __init__(
        self,
        project_root: Path,
        *,
        git_executable: str = "git",
        timeout_seconds: float = 30.0,
    ) -> None:
        if (
            type(git_executable) is not str
            or not git_executable.strip()
            or git_executable != git_executable.strip()
            or "\x00" in git_executable
        ):
            raise StructuralIndexBuildError("git_executable must be trimmed non-empty NUL-free text")
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(timeout_seconds)
            or timeout_seconds <= 0
        ):
            raise StructuralIndexBuildError("index timeout must be a positive finite number")

        self.snapshot_manager = SnapshotManager(project_root)
        self.project_root = self.snapshot_manager.project_root
        self.git_executable = git_executable
        self.timeout_seconds = float(timeout_seconds)

    def rebuild(self, revision: str = "HEAD") -> StructuralSnapshot:
        """Build and atomically publish the full Python index for ``revision``."""

        try:
            commit_sha = resolve_git_commit(
                self.project_root,
                revision,
                git_executable=self.git_executable,
                timeout_seconds=self.timeout_seconds,
            )
        except GitCommitResolutionError as exc:
            raise StructuralIndexBuildError("structural index revision could not be resolved") from exc

        symbols: list[StructuralSymbol] = []
        for blob in self._python_blobs(commit_sha):
            source_bytes = self._run_git("read committed blob", "cat-file", "blob", blob.object_id)
            source_text = _decode_python_source(source_bytes, blob.path)
            try:
                tree = ast.parse(source_text, filename=blob.path, type_comments=True)
            except (SyntaxError, ValueError) as exc:
                raise StructuralIndexBuildError(
                    f"committed Python source could not be parsed: {blob.path}"
                ) from exc
            symbols.extend(_symbols_for_module(tree, blob.path, source_text))

        symbols.sort(key=_symbol_sort_key)
        self.snapshot_manager.save_snapshot(commit_sha, symbols)
        return self.snapshot_manager.require_snapshot(commit_sha)

    def _python_blobs(self, commit_sha: str) -> tuple[_GitBlob, ...]:
        output = self._run_git(
            "list committed tree",
            "ls-tree",
            "-r",
            "-z",
            "--full-tree",
            commit_sha,
        )
        blobs: list[_GitBlob] = []
        seen_paths: set[str] = set()
        for raw_record in output.split(b"\x00"):
            if not raw_record:
                continue
            metadata, separator, raw_path = raw_record.partition(b"\t")
            metadata_parts = metadata.split(b" ")
            if not separator or len(metadata_parts) != 3 or not raw_path:
                raise StructuralIndexBuildError("Git returned a malformed tree record")
            try:
                mode, object_type, object_id = (
                    part.decode("ascii", errors="strict") for part in metadata_parts
                )
                path = raw_path.decode("utf-8", errors="strict")
            except UnicodeError as exc:
                raise StructuralIndexBuildError("Git tree metadata is not canonical UTF-8/ASCII") from exc
            if _GIT_OBJECT_ID.fullmatch(object_id) is None:
                raise StructuralIndexBuildError("Git returned an invalid object identity")
            if object_type != "blob" or mode not in _REGULAR_BLOB_MODES:
                continue
            _validate_git_path(path)
            if not path.endswith(".py"):
                continue
            if path in seen_paths:
                raise StructuralIndexBuildError("Git returned a duplicate Python path")
            seen_paths.add(path)
            blobs.append(_GitBlob(path=path, object_id=object_id))
        return tuple(sorted(blobs, key=lambda blob: blob.path))

    def _run_git(self, operation: str, *arguments: str) -> bytes:
        try:
            result = subprocess.run(
                [self.git_executable, *arguments],
                cwd=self.project_root,
                check=False,
                shell=False,
                capture_output=True,
                timeout=self.timeout_seconds,
                env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
            )
        except FileNotFoundError as exc:
            raise StructuralIndexBuildError("configured Git executable was not found") from exc
        except subprocess.TimeoutExpired as exc:
            raise StructuralIndexBuildError(f"Git timed out while attempting to {operation}") from exc
        except OSError as exc:
            raise StructuralIndexBuildError(f"Git could not start to {operation}") from exc
        if result.returncode != 0:
            raise StructuralIndexBuildError(
                f"Git failed to {operation} (exit {result.returncode})"
            )
        return result.stdout


class _ModuleSymbolVisitor(ast.NodeVisitor):
    def __init__(self, path: str, module_name: str) -> None:
        self.path = path
        self.module_name = module_name
        self.scopes: list[tuple[str, str]] = []
        self.symbols: list[StructuralSymbol] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.symbols.append(self._definition_symbol("class", node.name, node))
        self.scopes.append((node.name, "class"))
        self.generic_visit(node)
        self.scopes.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            local_name = alias.asname or alias.name.split(".", maxsplit=1)[0]
            self.symbols.append(
                self._import_symbol(local_name, alias.name, node)
            )

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        base = "." * node.level + (node.module or "")
        separator = "" if not base or base.endswith(".") else "."
        for alias in node.names:
            target = f"{base}{separator}{alias.name}"
            self.symbols.append(
                self._import_symbol(alias.asname or alias.name, target, node)
            )

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        kind: StructuralSymbolKind = (
            "method" if self.scopes and self.scopes[-1][1] == "class" else "function"
        )
        self.symbols.append(self._definition_symbol(kind, node.name, node))
        self.scopes.append((node.name, "function"))
        self.generic_visit(node)
        self.scopes.pop()

    def _definition_symbol(
        self,
        kind: StructuralSymbolKind,
        name: str,
        node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> StructuralSymbol:
        qualified_name = ".".join(
            (self.module_name, *(scope_name for scope_name, _ in self.scopes), name)
        )
        decorator_lines = [decorator.lineno for decorator in node.decorator_list]
        line_start = min([node.lineno, *decorator_lines])
        line_end = node.end_lineno or node.lineno
        return StructuralSymbol(
            kind=kind,
            name=name,
            qualified_name=qualified_name,
            path=self.path,
            line_start=line_start,
            line_end=line_end,
        )

    def _import_symbol(
        self,
        name: str,
        target: str,
        node: ast.Import | ast.ImportFrom,
    ) -> StructuralSymbol:
        return StructuralSymbol(
            kind="import",
            name=name,
            qualified_name=target,
            path=self.path,
            line_start=node.lineno,
            line_end=node.end_lineno or node.lineno,
        )


def _symbols_for_module(tree: ast.Module, path: str, source_text: str) -> list[StructuralSymbol]:
    module_name = _module_name(path)
    visitor = _ModuleSymbolVisitor(path, module_name)
    visitor.symbols.append(
        StructuralSymbol(
            kind="module",
            name=module_name.rsplit(".", maxsplit=1)[-1],
            qualified_name=module_name,
            path=path,
            line_start=1,
            line_end=max(1, len(source_text.splitlines())),
        )
    )
    visitor.visit(tree)
    return visitor.symbols


def _module_name(path: str) -> str:
    parts = list(PurePosixPath(path).with_suffix("").parts)
    if parts[-1] == "__init__" and len(parts) > 1:
        parts.pop()
    return ".".join(parts)


def _decode_python_source(source: bytes, path: str) -> str:
    try:
        encoding, _ = tokenize.detect_encoding(io.BytesIO(source).readline)
        return source.decode(encoding, errors="strict")
    except (LookupError, SyntaxError, UnicodeError) as exc:
        raise StructuralIndexBuildError(
            f"committed Python source has invalid encoding: {path}"
        ) from exc


def _validate_git_path(path: str) -> None:
    pure_path = PurePosixPath(path)
    if (
        not path
        or "\x00" in path
        or "\\" in path
        or path != path.strip()
        or pure_path.is_absolute()
        or pure_path.as_posix() != path
        or any(part in {"", ".", ".."} for part in pure_path.parts)
    ):
        raise StructuralIndexBuildError("Git returned a noncanonical repository path")


def _symbol_sort_key(symbol: StructuralSymbol) -> tuple[object, ...]:
    return (
        symbol.path,
        symbol.line_start,
        symbol.line_end,
        symbol.kind,
        symbol.qualified_name,
        symbol.name,
    )


__all__ = ["PythonAstIndexer", "StructuralIndexBuildError"]
