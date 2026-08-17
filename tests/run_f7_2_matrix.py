"""Validate and execute the canonical F7.2 pytest matrix."""

from __future__ import annotations

import argparse
import ast
import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
MATRIX_PATH = ROOT / "tests" / "f7_2_matrix.json"
SCHEMA_VERSION = "1.0"
TASK_ID = "F7.2"

EXPECTED_REQUIREMENTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("contracts", ("validation", "compatibility", "serialization")),
    ("compiler", ("valid_graphs", "invalid_graphs")),
    ("runtime", ("branches", "retry", "pause", "resume", "cancellation")),
    ("persistence", ("atomicity", "lock", "replay", "corruption")),
    ("models", ("errors", "timeout", "tokens", "structured_output", "tools")),
    ("tools", ("authorization", "path_guard", "timeout", "output_limit")),
    ("git", ("worktree", "commit", "divergence", "promotion", "revert")),
    ("verification", ("pass", "fail", "missing_tool", "empty_suite")),
    ("security", ("secrets", "egress", "trust", "command_injection")),
    ("observability", ("sequence", "hash", "redaction", "export")),
    ("e2e", ("full_cycle_external_repository",)),
    ("recovery", ("crash_injection_critical_checkpoints",)),
)


class MatrixValidationError(ValueError):
    """Raised when the F7.2 matrix is malformed or references an invalid test."""


def _object_without_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise MatrixValidationError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def load_matrix(path: Path = MATRIX_PATH) -> dict[str, object]:
    """Load strict UTF-8 JSON while rejecting duplicate object keys."""
    try:
        raw = path.read_text(encoding="utf-8")
        value = json.loads(raw, object_pairs_hook=_object_without_duplicates)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MatrixValidationError(f"cannot load matrix {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise MatrixValidationError("matrix root must be an object")
    return value


def _require_exact_keys(value: object, expected: tuple[str, ...], context: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise MatrixValidationError(f"{context} must be an object")
    actual = tuple(value)
    if actual != expected:
        raise MatrixValidationError(f"{context} keys must be {expected!r}, got {actual!r}")
    return value


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _validate_node_id(node_id: object, root: Path) -> str:
    if not isinstance(node_id, str) or not node_id or node_id != node_id.strip():
        raise MatrixValidationError("pytest node IDs must be non-empty trimmed strings")
    if node_id.count("::") != 1:
        raise MatrixValidationError(f"node ID must select exactly one function: {node_id!r}")

    path_text, symbol = node_id.split("::")
    if "\\" in path_text or any(part in {"", ".", ".."} for part in path_text.split("/")):
        raise MatrixValidationError(f"node ID path must be normalized POSIX without traversal: {node_id!r}")
    pure_path = PurePosixPath(path_text)
    if pure_path.is_absolute() or pure_path.suffix != ".py":
        raise MatrixValidationError(f"node ID must reference a relative Python file: {node_id!r}")
    if pure_path.parts[:2] not in {("tests", "unit"), ("tests", "e2e")}:
        raise MatrixValidationError(f"node ID must be under tests/unit or tests/e2e: {node_id!r}")
    if not symbol.isidentifier() or not symbol.startswith("test_"):
        raise MatrixValidationError(f"node ID must reference a top-level pytest function: {node_id!r}")

    try:
        target = root.joinpath(*pure_path.parts).resolve(strict=True)
    except OSError as exc:
        raise MatrixValidationError(f"node ID file does not exist: {node_id!r}") from exc
    allowed_roots = ((root / "tests" / "unit").resolve(), (root / "tests" / "e2e").resolve())
    if not any(_is_within(target, allowed_root) for allowed_root in allowed_roots):
        raise MatrixValidationError(f"resolved node ID escapes the allowed test roots: {node_id!r}")

    try:
        module = ast.parse(target.read_text(encoding="utf-8"), filename=str(target))
    except (OSError, UnicodeError, SyntaxError) as exc:
        raise MatrixValidationError(f"cannot inspect node ID file {node_id!r}: {exc}") from exc
    functions = {
        statement.name
        for statement in module.body
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    if symbol not in functions:
        raise MatrixValidationError(f"pytest function does not exist at module scope: {node_id!r}")
    return node_id


def validate_matrix(matrix: Mapping[str, object], root: Path = ROOT) -> tuple[str, ...]:
    """Validate schema, canonical order, references and global node-ID uniqueness."""
    root_object = _require_exact_keys(matrix, ("schema_version", "task_id", "layers"), "matrix")
    if root_object["schema_version"] != SCHEMA_VERSION:
        raise MatrixValidationError(f"schema_version must be {SCHEMA_VERSION!r}")
    if root_object["task_id"] != TASK_ID:
        raise MatrixValidationError(f"task_id must be {TASK_ID!r}")

    layers = root_object["layers"]
    if not isinstance(layers, list) or len(layers) != len(EXPECTED_REQUIREMENTS):
        raise MatrixValidationError(f"layers must contain exactly {len(EXPECTED_REQUIREMENTS)} entries")

    selected: list[str] = []
    seen: set[str] = set()
    for index, ((expected_layer, expected_requirements), raw_layer) in enumerate(
        zip(EXPECTED_REQUIREMENTS, layers, strict=True)
    ):
        layer = _require_exact_keys(raw_layer, ("id", "requirements"), f"layers[{index}]")
        if layer["id"] != expected_layer:
            raise MatrixValidationError(f"layers[{index}].id must be {expected_layer!r}")
        requirements = _require_exact_keys(
            layer["requirements"], expected_requirements, f"layer {expected_layer!r} requirements"
        )
        for requirement_name in expected_requirements:
            raw_node_ids = requirements[requirement_name]
            if not isinstance(raw_node_ids, list) or not raw_node_ids:
                raise MatrixValidationError(
                    f"requirement {expected_layer}.{requirement_name} must contain at least one node ID"
                )
            for raw_node_id in raw_node_ids:
                node_id = _validate_node_id(raw_node_id, root)
                if node_id in seen:
                    raise MatrixValidationError(f"duplicate pytest node ID: {node_id!r}")
                seen.add(node_id)
                selected.append(node_id)

    return tuple(selected)


def matrix_counts(matrix: Mapping[str, object]) -> tuple[int, int]:
    """Return layer and requirement counts after validation of the canonical shape."""
    layers = matrix.get("layers")
    if not isinstance(layers, list):
        return 0, 0
    requirement_count = 0
    for layer in layers:
        if isinstance(layer, dict) and isinstance(layer.get("requirements"), dict):
            requirement_count += len(layer["requirements"])
    return len(layers), requirement_count


def build_pytest_command(node_ids: Sequence[str], *, collect_only: bool, basetemp: Path) -> list[str]:
    """Build an argv-only pytest invocation using the active Python interpreter."""
    command = [sys.executable, "-m", "pytest"]
    if collect_only:
        command.append("--collect-only")
    command.extend(("-q", "-p", "no:cacheprovider", "--basetemp", str(basetemp), *node_ids))
    return command


def configured_temp_parent() -> Path | None:
    """Resolve the optional writable parent used by restricted execution environments."""
    configured = os.environ.get("HARNESS_F7_2_TEMP_PARENT")
    if configured is None:
        return None
    try:
        parent = Path(configured).resolve(strict=True)
    except OSError as exc:
        raise MatrixValidationError(f"HARNESS_F7_2_TEMP_PARENT does not exist: {configured!r}") from exc
    if not parent.is_dir():
        raise MatrixValidationError(f"HARNESS_F7_2_TEMP_PARENT is not a directory: {configured!r}")
    if _is_within(parent, ROOT):
        raise MatrixValidationError("HARNESS_F7_2_TEMP_PARENT must be outside the source checkout")
    return parent


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collect-only", action="store_true", help="validate and collect without running tests")
    args = parser.parse_args(argv)

    try:
        matrix = load_matrix()
        node_ids = validate_matrix(matrix)
    except MatrixValidationError as exc:
        print(f"F7.2 matrix error: {exc}", file=sys.stderr)
        return 2

    layer_count, requirement_count = matrix_counts(matrix)
    print(
        f"F7.2 matrix: {layer_count} layers, {requirement_count} requirements, "
        f"{len(node_ids)} unique pytest nodes",
        flush=True,
    )
    try:
        temp_parent = configured_temp_parent()
        with tempfile.TemporaryDirectory(prefix="f7-2-", dir=temp_parent) as basetemp:
            completed = subprocess.run(
                build_pytest_command(node_ids, collect_only=args.collect_only, basetemp=Path(basetemp)),
                cwd=ROOT,
                check=False,
                shell=False,
            )
            return completed.returncode
    except (OSError, MatrixValidationError) as exc:
        print(f"F7.2 matrix temporary directory error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
