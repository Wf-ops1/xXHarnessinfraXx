"""Fail-closed coverage thresholds for the F7.3 critical decision kernels."""

from __future__ import annotations

import argparse
import ast
import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = ROOT / "tests" / "ci" / "f7_3_quality_gates.json"


class CoverageGateError(RuntimeError):
    """The manifest or coverage evidence is absent, malformed, or below threshold."""


@dataclass(frozen=True, slots=True)
class DecisionFunction:
    path: str
    qualname: str


@dataclass(frozen=True, slots=True)
class CoverageContract:
    minimum_percent: float
    core_files: tuple[str, ...]
    decision_functions: tuple[DecisionFunction, ...]


@dataclass(frozen=True, slots=True)
class CoverageResult:
    core_percent: float
    measured_files: int
    measured_functions: int


def _load_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8", errors="strict"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CoverageGateError(f"{label} is not valid UTF-8 JSON: {path}") from exc
    if type(document) is not dict:
        raise CoverageGateError(f"{label} must be a JSON object")
    return document


def _source_path(value: object, *, root: Path) -> tuple[str, Path]:
    if type(value) is not str or not value or "\\" in value:
        raise CoverageGateError("source paths must be non-empty canonical POSIX strings")
    pure = PurePosixPath(value)
    if pure.is_absolute() or ".." in pure.parts or pure.as_posix() != value:
        raise CoverageGateError(f"source path is not confined and canonical: {value!r}")
    if pure.parts[:2] != ("src", "ai_engineering_harness") or pure.suffix != ".py":
        raise CoverageGateError(f"source path is outside the Python package: {value!r}")
    resolved = (root / Path(*pure.parts)).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise CoverageGateError(f"source path escaped the repository: {value!r}") from exc
    if not resolved.is_file():
        raise CoverageGateError(f"source path does not exist: {value!r}")
    return value, resolved


def load_contract(
    manifest_path: Path = MANIFEST_PATH,
    *,
    root: Path = ROOT,
) -> CoverageContract:
    document = _load_json(manifest_path, label="coverage manifest")
    expected_keys = {
        "schema_version",
        "task_id",
        "core_minimum_percent",
        "core_files",
        "decision_functions",
    }
    if set(document) != expected_keys:
        raise CoverageGateError("coverage manifest has missing or extra fields")
    if document["schema_version"] != "1.0" or document["task_id"] != "F7.3":
        raise CoverageGateError("coverage manifest identity is not F7.3 schema 1.0")
    minimum = document["core_minimum_percent"]
    if type(minimum) not in {int, float} or not 80.0 <= float(minimum) <= 100.0:
        raise CoverageGateError("core minimum must remain between 80 and 100 percent")

    raw_core = document["core_files"]
    if type(raw_core) is not list or not raw_core:
        raise CoverageGateError("core_files must be a non-empty list")
    core_files = tuple(_source_path(item, root=root)[0] for item in raw_core)
    if len(set(core_files)) != len(core_files):
        raise CoverageGateError("core_files must be unique")

    raw_functions = document["decision_functions"]
    if type(raw_functions) is not list or not raw_functions:
        raise CoverageGateError("decision_functions must be a non-empty list")
    functions: list[DecisionFunction] = []
    for item in raw_functions:
        if type(item) is not dict or set(item) != {"path", "qualname"}:
            raise CoverageGateError("each decision function must contain only path and qualname")
        path = _source_path(item["path"], root=root)[0]
        qualname = item["qualname"]
        if type(qualname) is not str or not qualname or any(
            not part.isidentifier() for part in qualname.split(".")
        ):
            raise CoverageGateError(f"invalid decision function qualname: {qualname!r}")
        if path not in core_files:
            raise CoverageGateError(f"decision function is outside core_files: {path}:{qualname}")
        functions.append(DecisionFunction(path=path, qualname=qualname))
    if len(set(functions)) != len(functions):
        raise CoverageGateError("decision_functions must be unique")
    return CoverageContract(float(minimum), core_files, tuple(functions))


def _normalized_coverage_files(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw_files = document.get("files")
    if type(raw_files) is not dict:
        raise CoverageGateError("coverage JSON must contain a files object")
    normalized: dict[str, dict[str, Any]] = {}
    for raw_path, value in raw_files.items():
        if type(raw_path) is not str or type(value) is not dict:
            raise CoverageGateError("coverage file entries must map strings to objects")
        path = raw_path.replace("\\", "/")
        if path in normalized:
            raise CoverageGateError(f"coverage JSON contains duplicate normalized path: {path}")
        normalized[path] = value
    return normalized


def _non_negative_int(value: object, *, label: str) -> int:
    if type(value) is not int or value < 0:
        raise CoverageGateError(f"{label} must be a non-negative integer")
    return value


def _branch_edges(value: object, *, label: str) -> tuple[tuple[int, int], ...]:
    if type(value) is not list:
        raise CoverageGateError(f"{label} must be a list")
    edges: list[tuple[int, int]] = []
    for edge in value:
        if (
            type(edge) is not list
            or len(edge) != 2
            or any(type(line) is not int for line in edge)
        ):
            raise CoverageGateError(f"{label} contains a malformed branch edge")
        edges.append((edge[0], edge[1]))
    return tuple(edges)


class _QualifiedFunctions(ast.NodeVisitor):
    def __init__(self) -> None:
        self._scope: list[str] = []
        self.nodes: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._scope.append(node.name)
        self.generic_visit(node)
        self._scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        qualname = ".".join((*self._scope, node.name))
        if qualname in self.nodes:
            raise CoverageGateError(f"duplicate AST function qualname: {qualname}")
        self.nodes[qualname] = node
        self._scope.append(node.name)
        self.generic_visit(node)
        self._scope.pop()


def _function_nodes(path: Path) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="strict"), filename=str(path))
    except (OSError, UnicodeError, SyntaxError) as exc:
        raise CoverageGateError(f"cannot parse covered source: {path}") from exc
    visitor = _QualifiedFunctions()
    visitor.visit(tree)
    return visitor.nodes


def evaluate_coverage(
    coverage_path: Path,
    *,
    manifest_path: Path = MANIFEST_PATH,
    root: Path = ROOT,
) -> CoverageResult:
    contract = load_contract(manifest_path, root=root)
    coverage = _load_json(coverage_path, label="coverage report")
    measured = _normalized_coverage_files(coverage)
    total_opportunities = 0
    covered_opportunities = 0
    records: dict[str, dict[str, Any]] = {}

    for source in contract.core_files:
        record = measured.get(source)
        if record is None:
            raise CoverageGateError(f"core source is absent from coverage report: {source}")
        summary = record.get("summary")
        if type(summary) is not dict:
            raise CoverageGateError(f"coverage summary is missing for: {source}")
        statements = _non_negative_int(summary.get("num_statements"), label="num_statements")
        missing_lines = _non_negative_int(summary.get("missing_lines"), label="missing_lines")
        branches = _non_negative_int(summary.get("num_branches"), label="num_branches")
        missing_branches = _non_negative_int(
            summary.get("missing_branches"), label="missing_branches"
        )
        if missing_lines > statements or missing_branches > branches or statements + branches == 0:
            raise CoverageGateError(f"coverage summary is inconsistent for: {source}")
        total_opportunities += statements + branches
        covered_opportunities += statements - missing_lines + branches - missing_branches
        records[source] = record

    core_percent = 100.0 * covered_opportunities / total_opportunities
    if core_percent + 1e-9 < contract.minimum_percent:
        raise CoverageGateError(
            f"critical core coverage {core_percent:.2f}% is below {contract.minimum_percent:.2f}%"
        )

    missing_decisions: list[str] = []
    ast_cache: dict[str, dict[str, ast.FunctionDef | ast.AsyncFunctionDef]] = {}
    for decision in contract.decision_functions:
        record = records[decision.path]
        missing = _branch_edges(record.get("missing_branches"), label="missing_branches")
        executed = _branch_edges(record.get("executed_branches"), label="executed_branches")
        if decision.path not in ast_cache:
            ast_cache[decision.path] = _function_nodes(
                root / Path(*PurePosixPath(decision.path).parts)
            )
        nodes = ast_cache[decision.path]
        node = nodes.get(decision.qualname)
        if node is None or node.end_lineno is None:
            raise CoverageGateError(
                f"decision function is absent from source AST: {decision.path}:{decision.qualname}"
            )
        observed = tuple(
            edge for edge in (*executed, *missing) if node.lineno <= edge[0] <= node.end_lineno
        )
        if not observed:
            raise CoverageGateError(
                f"decision function has no measured branch opportunities: "
                f"{decision.path}:{decision.qualname}"
            )
        absent = tuple(edge for edge in missing if node.lineno <= edge[0] <= node.end_lineno)
        if absent:
            missing_decisions.append(f"{decision.path}:{decision.qualname}={list(absent)!r}")
    if missing_decisions:
        raise CoverageGateError(
            "decision branch coverage is below 100%:\n" + "\n".join(missing_decisions)
        )
    return CoverageResult(core_percent, len(contract.core_files), len(contract.decision_functions))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("coverage_json", type=Path)
    args = parser.parse_args(argv)
    try:
        result = evaluate_coverage(args.coverage_json)
    except CoverageGateError as exc:
        parser.exit(1, f"F7.3 coverage gate failed: {exc}\n")
    print(
        "F7.3 coverage gate: "
        f"core={result.core_percent:.2f}% files={result.measured_files} "
        f"decision_functions={result.measured_functions} missing_decision_branches=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
