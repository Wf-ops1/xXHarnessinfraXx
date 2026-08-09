"""Confined UTF-8 file operations and strict single-file patch application."""

from __future__ import annotations

import hashlib
import os
import re
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path

from ai_engineering_harness.security import PathGuard


class LocalEditingError(RuntimeError):
    """Base error for local editing operations."""


class LocalEditingConfigurationError(LocalEditingError, ValueError):
    """The adapter or one of its bounded requests is invalid."""


class TextFileError(LocalEditingError):
    """A target is not a regular, strict UTF-8 text file."""


class PatchValidationError(LocalEditingError, ValueError):
    """A unified diff is malformed, ambiguous, or targets a different file."""


class StaleFileError(LocalEditingError):
    """The current file digest differs from the caller's expected digest."""


class NoFileChangeError(LocalEditingError):
    """A requested edit produced no observable content change."""


@dataclass(frozen=True, slots=True)
class FileSnapshot:
    """One real bounded text snapshot."""

    relative_path: str
    content: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class PatchResult:
    """Evidence returned only after an atomic file publication."""

    relative_path: str
    previous_sha256: str | None
    sha256: str
    size_bytes: int
    created: bool


@dataclass(frozen=True, slots=True)
class _Hunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    body: tuple[str, ...]


_HUNK_HEADER = re.compile(
    r"^@@ -(0|[1-9][0-9]*)(?:,([0-9]+))? \+(0|[1-9][0-9]*)(?:,([0-9]+))? @@(?: .*)?\n$"
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class LocalEditingAdapter:
    """Perform bounded file effects under one explicit authorized root."""

    __slots__ = ("_path_guard",)

    def __init__(self, *, path_guard: PathGuard) -> None:
        if not isinstance(path_guard, PathGuard):
            raise LocalEditingConfigurationError("path_guard must be an explicit PathGuard")
        self._path_guard = path_guard

    @property
    def path_guard(self) -> PathGuard:
        """Return the guard shared with the provisioned worktree."""

        return self._path_guard

    def read_file(self, path: str | os.PathLike[str]) -> FileSnapshot:
        """Read one regular strict UTF-8 file and return its real digest."""

        guarded = self._path_guard.guard_read(path)
        data = self._read_regular_file(guarded.absolute_path)
        try:
            content = data.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise TextFileError("file is not strict UTF-8 text") from exc
        return FileSnapshot(
            relative_path=guarded.relative_path,
            content=content,
            sha256=_digest(data),
            size_bytes=len(data),
        )

    def list_files(
        self,
        path: str | os.PathLike[str] = ".",
        *,
        max_depth: int = 4,
        max_entries: int = 1_000,
    ) -> tuple[dict[str, object], ...]:
        """List a bounded directory tree without following directory symlinks."""

        depth_limit = _positive_int("max_depth", max_depth, maximum=32)
        entry_limit = _positive_int("max_entries", max_entries, maximum=10_000)
        root = self._path_guard.guard_read(path)
        if not root.absolute_path.is_dir():
            raise TextFileError("list_files target must be a directory")

        result: list[dict[str, object]] = []
        pending: list[tuple[Path, int]] = [(root.absolute_path, 0)]
        while pending:
            directory, depth = pending.pop()
            try:
                with os.scandir(directory) as iterator:
                    entries = sorted(iterator, key=lambda item: item.name.casefold())
            except OSError as exc:
                raise TextFileError("directory could not be listed safely") from exc
            child_directories: list[Path] = []
            for entry in entries:
                guarded = self._path_guard.guard_read(entry.path)
                is_symlink = _is_directory_link(entry)
                try:
                    is_directory = entry.is_dir(follow_symlinks=False)
                    is_file = entry.is_file(follow_symlinks=False)
                except OSError as exc:
                    raise TextFileError("directory entry could not be inspected safely") from exc
                kind = "symlink" if is_symlink else "directory" if is_directory else "file" if is_file else "other"
                result.append(
                    {
                        "path": guarded.relative_path,
                        "kind": kind,
                        "depth": depth + 1,
                    }
                )
                if len(result) > entry_limit:
                    raise LocalEditingConfigurationError("list_files exceeded max_entries")
                if is_directory and not is_symlink and depth + 1 < depth_limit:
                    child_directories.append(guarded.absolute_path)
            for child in reversed(child_directories):
                pending.append((child, depth + 1))
        return tuple(sorted(result, key=lambda item: str(item["path"])))

    def search_text(
        self,
        query: str,
        path: str | os.PathLike[str] = ".",
        *,
        case_sensitive: bool = True,
        max_results: int = 200,
        max_files: int = 2_000,
    ) -> dict[str, object]:
        """Search literal text with explicit result, file, and read-size bounds."""

        if not isinstance(query, str) or not query or "\x00" in query or "\n" in query or "\r" in query:
            raise LocalEditingConfigurationError("query must be non-empty single-line text")
        if type(case_sensitive) is not bool:
            raise LocalEditingConfigurationError("case_sensitive must be a boolean")
        result_limit = _positive_int("max_results", max_results, maximum=10_000)
        file_limit = _positive_int("max_files", max_files, maximum=50_000)
        guarded = self._path_guard.guard_read(path)
        candidates = self._search_candidates(guarded.absolute_path, max_files=file_limit)

        needle = query if case_sensitive else query.casefold()
        matches: list[dict[str, object]] = []
        skipped: list[dict[str, str]] = []
        for candidate in candidates:
            try:
                snapshot = self.read_file(candidate)
            except TextFileError:
                relative = self._path_guard.guard_read(candidate).relative_path
                skipped.append({"path": relative, "reason": "NON_UTF8_OR_NON_REGULAR"})
                continue
            for line_number, line in enumerate(snapshot.content.splitlines(), start=1):
                haystack = line if case_sensitive else line.casefold()
                start = 0
                while True:
                    column = haystack.find(needle, start)
                    if column < 0:
                        break
                    matches.append(
                        {
                            "path": snapshot.relative_path,
                            "line": line_number,
                            "column": column + 1,
                            "text": line[:500],
                        }
                    )
                    if len(matches) >= result_limit:
                        return {
                            "query": query,
                            "matches": matches,
                            "skipped": skipped,
                            "truncated": True,
                            "files_scanned": len(candidates),
                        }
                    start = column + max(len(needle), 1)
        return {
            "query": query,
            "matches": matches,
            "skipped": skipped,
            "truncated": False,
            "files_scanned": len(candidates),
        }

    def apply_patch(
        self,
        path: str | os.PathLike[str],
        patch: str,
        *,
        expected_sha256: str | None,
    ) -> PatchResult:
        """Apply one strict unified diff and publish the result atomically."""

        if not isinstance(patch, str) or not patch or "\x00" in patch:
            raise PatchValidationError("patch must be non-empty text without null bytes")
        if not patch.endswith("\n"):
            raise PatchValidationError("patch must end with an unambiguous newline")

        raw_path = os.fspath(path)
        initial_write = self._path_guard.guard_write(raw_path, size_bytes=0)
        target = initial_write.absolute_path
        exists = target.exists()
        if target.is_symlink():
            raise PatchValidationError("patch target cannot be a symlink")

        previous: bytes
        previous_digest: str | None
        mode: int | None
        if exists:
            if expected_sha256 is None or _SHA256.fullmatch(expected_sha256) is None:
                raise StaleFileError("existing files require a lowercase SHA-256 digest")
            snapshot = self.read_file(raw_path)
            previous = snapshot.content.encode("utf-8")
            previous_digest = snapshot.sha256
            if previous_digest != expected_sha256:
                raise StaleFileError("file digest differs from expected_sha256")
            if previous and not previous.endswith(b"\n"):
                raise PatchValidationError("files without a final newline are not patchable")
            mode = stat.S_IMODE(target.stat().st_mode)
        else:
            if expected_sha256 is not None:
                raise StaleFileError("new files require expected_sha256 to be null")
            parent = self._path_guard.guard_read(target.parent)
            if not parent.absolute_path.is_dir():
                raise PatchValidationError("new file parent must be an existing directory")
            previous = b""
            previous_digest = None
            mode = None

        new_content = _apply_unified_diff(
            previous.decode("utf-8"),
            patch,
            target_path=initial_write.relative_path,
            creating=not exists,
        ).encode("utf-8")
        if not new_content:
            raise PatchValidationError("patch cannot create or publish an empty file")
        if new_content == previous:
            raise NoFileChangeError("patch produced no content change")
        guarded_write = self._path_guard.guard_write(raw_path, size_bytes=len(new_content))
        if guarded_write.absolute_path != target:
            raise StaleFileError("patch target changed during validation")

        self._revalidate_before_write(
            raw_path,
            target=target,
            expected_digest=previous_digest,
            creating=not exists,
        )
        self._atomic_replace(target, new_content, mode=mode)
        published = self.read_file(raw_path)
        published_digest = _digest(new_content)
        if published.sha256 != published_digest or published.content.encode("utf-8") != new_content:
            raise LocalEditingError("published file does not match the intended content")
        return PatchResult(
            relative_path=published.relative_path,
            previous_sha256=previous_digest,
            sha256=published.sha256,
            size_bytes=published.size_bytes,
            created=not exists,
        )

    def _search_candidates(self, path: Path, *, max_files: int) -> tuple[Path, ...]:
        if path.is_file():
            return (path,)
        if not path.is_dir():
            raise TextFileError("search_text target must be a file or directory")
        result: list[Path] = []
        pending = [path]
        while pending:
            directory = pending.pop()
            try:
                entries = sorted(os.scandir(directory), key=lambda item: item.name.casefold())
            except OSError as exc:
                raise TextFileError("search directory could not be listed safely") from exc
            directories: list[Path] = []
            for entry in entries:
                guarded = self._path_guard.guard_read(entry.path)
                is_link = _is_directory_link(entry)
                if is_link:
                    if guarded.absolute_path.is_file():
                        result.append(guarded.absolute_path)
                    continue
                if entry.is_dir(follow_symlinks=False):
                    directories.append(guarded.absolute_path)
                elif entry.is_file(follow_symlinks=False):
                    result.append(guarded.absolute_path)
                if len(result) > max_files:
                    raise LocalEditingConfigurationError("search_text exceeded max_files")
            pending.extend(reversed(directories))
        return tuple(sorted(set(result), key=lambda item: item.as_posix().casefold()))

    @staticmethod
    def _read_regular_file(path: Path) -> bytes:
        try:
            if not path.is_file():
                raise TextFileError("read target must be a regular file")
            return path.read_bytes()
        except TextFileError:
            raise
        except OSError as exc:
            raise TextFileError("file could not be read safely") from exc

    def _revalidate_before_write(
        self,
        raw_path: str,
        *,
        target: Path,
        expected_digest: str | None,
        creating: bool,
    ) -> None:
        if creating:
            if target.exists() or target.is_symlink():
                raise StaleFileError("new file appeared before publication")
            parent = self._path_guard.guard_read(target.parent)
            if not parent.absolute_path.is_dir():
                raise StaleFileError("new file parent changed before publication")
            return
        snapshot = self.read_file(raw_path)
        if snapshot.sha256 != expected_digest:
            raise StaleFileError("file changed before publication")

    @staticmethod
    def _atomic_replace(target: Path, content: bytes, *, mode: int | None) -> None:
        descriptor: int | None = None
        temporary: Path | None = None
        try:
            descriptor, raw_temporary = tempfile.mkstemp(
                prefix=f".{target.name}.",
                suffix=".f3-8.tmp",
                dir=target.parent,
            )
            temporary = Path(raw_temporary)
            with os.fdopen(descriptor, "wb") as stream:
                descriptor = None
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            if mode is not None:
                os.chmod(temporary, mode)
            os.replace(temporary, target)
            temporary = None
            _fsync_directory(target.parent)
        except OSError as exc:
            raise LocalEditingError("file could not be published atomically") from exc
        finally:
            if descriptor is not None:
                os.close(descriptor)
            if temporary is not None:
                temporary.unlink(missing_ok=True)


def _apply_unified_diff(source: str, patch: str, *, target_path: str, creating: bool) -> str:
    lines = patch.splitlines(keepends=True)
    if len(lines) < 3 or not lines[0].startswith("--- ") or not lines[1].startswith("+++ "):
        raise PatchValidationError("patch must contain exactly one unified-diff file header")
    old_path = _header_path(lines[0], prefix="--- ")
    new_path = _header_path(lines[1], prefix="+++ ")
    normalized = target_path.replace("\\", "/")
    allowed_paths = {normalized, f"a/{normalized}", f"b/{normalized}"}
    if creating:
        if old_path != "/dev/null" or new_path not in allowed_paths:
            raise PatchValidationError("new-file patch header does not match the target")
    elif old_path not in allowed_paths or new_path not in allowed_paths:
        raise PatchValidationError("patch header does not match the target")
    if new_path == "/dev/null":
        raise PatchValidationError("file deletion is outside the F3.8 patch contract")

    hunks = _parse_hunks(lines[2:])
    if not hunks:
        raise PatchValidationError("patch must contain at least one hunk")
    normalized_source, newline = _normalize_source_newlines(source)
    source_lines = normalized_source.splitlines(keepends=True)
    output: list[str] = []
    cursor = 0
    previous_new_end = 0
    for hunk in hunks:
        old_index = 0 if hunk.old_start == 0 else hunk.old_start - 1
        if old_index < cursor or hunk.new_start < previous_new_end:
            raise PatchValidationError("patch hunks overlap or are out of order")
        if old_index > len(source_lines):
            raise PatchValidationError("patch hunk starts beyond the source file")
        output.extend(source_lines[cursor:old_index])
        source_index = old_index
        old_seen = 0
        new_seen = 0
        for line in hunk.body:
            marker, content = line[0], line[1:]
            if marker in {" ", "-"}:
                if source_index >= len(source_lines) or source_lines[source_index] != content:
                    raise PatchValidationError("patch context does not match the current file")
                source_index += 1
                old_seen += 1
            if marker in {" ", "+"}:
                output.append(content)
                new_seen += 1
        if old_seen != hunk.old_count or new_seen != hunk.new_count:
            raise PatchValidationError("patch hunk line counts do not match its header")
        cursor = source_index
        previous_new_end = hunk.new_start + hunk.new_count
    output.extend(source_lines[cursor:])
    result = "".join(output)
    return result if newline == "\n" else result.replace("\n", newline)


def _parse_hunks(lines: list[str]) -> tuple[_Hunk, ...]:
    hunks: list[_Hunk] = []
    index = 0
    while index < len(lines):
        header = lines[index]
        match = _HUNK_HEADER.fullmatch(header)
        if match is None:
            raise PatchValidationError("patch contains trailing data or a malformed hunk header")
        old_start = int(match.group(1))
        old_count = int(match.group(2) if match.group(2) is not None else "1")
        new_start = int(match.group(3))
        new_count = int(match.group(4) if match.group(4) is not None else "1")
        index += 1
        body: list[str] = []
        while index < len(lines) and not lines[index].startswith("@@ "):
            line = lines[index]
            if not line.endswith("\n") or not line or line[0] not in {" ", "+", "-"}:
                raise PatchValidationError("patch body contains an ambiguous or unsupported line")
            body.append(line)
            index += 1
        hunks.append(
            _Hunk(
                old_start=old_start,
                old_count=old_count,
                new_start=new_start,
                new_count=new_count,
                body=tuple(body),
            )
        )
    return tuple(hunks)


def _header_path(line: str, *, prefix: str) -> str:
    if not line.endswith("\n") or "\t" in line:
        raise PatchValidationError("patch headers cannot contain timestamps or ambiguous paths")
    path = line[len(prefix) : -1]
    if not path or "\x00" in path or "\\" in path:
        raise PatchValidationError("patch header path is invalid")
    return path


def _normalize_source_newlines(source: str) -> tuple[str, str]:
    if "\r\n" not in source:
        if "\r" in source:
            raise PatchValidationError("carriage-return-only files are not patchable")
        return source, "\n"
    normalized = source.replace("\r\n", "\n")
    if "\r" in normalized:
        raise PatchValidationError("mixed or ambiguous newlines are not patchable")
    return normalized, "\r\n"


def _positive_int(name: str, value: int, *, maximum: int) -> int:
    if type(value) is not int or value <= 0 or value > maximum:
        raise LocalEditingConfigurationError(f"{name} must be an integer between 1 and {maximum}")
    return value


def _digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _is_directory_link(entry: os.DirEntry[str]) -> bool:
    is_junction = getattr(Path(entry.path), "is_junction", lambda: False)
    return entry.is_symlink() or bool(is_junction())


def _fsync_directory(directory: Path) -> None:
    try:
        descriptor = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


__all__ = [
    "FileSnapshot",
    "LocalEditingAdapter",
    "LocalEditingConfigurationError",
    "LocalEditingError",
    "NoFileChangeError",
    "PatchResult",
    "PatchValidationError",
    "StaleFileError",
    "TextFileError",
]
