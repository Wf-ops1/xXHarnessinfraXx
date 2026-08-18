"""Run the mandatory F7.3 secret and dependency scans without a shell."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[2]
BASELINE_PATH = ROOT / ".secrets.baseline"


class SecurityGateError(RuntimeError):
    """A security scanner or its reviewed evidence is unavailable or invalid."""


def _tool_path(name: str, *, python_executable: Path = Path(sys.executable)) -> str:
    suffix = ".exe" if os.name == "nt" else ""
    sibling = python_executable.resolve().with_name(name + suffix)
    if sibling.is_file():
        return str(sibling)
    discovered = shutil.which(name)
    if discovered is None:
        raise SecurityGateError(f"required scanner executable is unavailable: {name}")
    return discovered


def validate_reviewed_baseline(
    baseline_path: Path = BASELINE_PATH,
    *,
    root: Path = ROOT,
) -> int:
    try:
        document = json.loads(baseline_path.read_text(encoding="utf-8", errors="strict"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SecurityGateError(".secrets.baseline is not valid UTF-8 JSON") from exc
    if type(document) is not dict or not {
        "version",
        "plugins_used",
        "filters_used",
        "results",
    } <= set(document):
        raise SecurityGateError(".secrets.baseline has an incomplete detect-secrets schema")
    results = document["results"]
    if type(results) is not dict:
        raise SecurityGateError(".secrets.baseline results must be an object")
    finding_count = 0
    for raw_path, findings in results.items():
        if type(raw_path) is not str or "\\" in raw_path or type(findings) is not list:
            raise SecurityGateError(".secrets.baseline contains a malformed path entry")
        candidate = (root / raw_path).resolve()
        try:
            candidate.relative_to(root.resolve())
        except ValueError as exc:
            raise SecurityGateError(".secrets.baseline contains an escaping path") from exc
        if not candidate.is_file():
            raise SecurityGateError(f"baseline finding points to a missing file: {raw_path}")
        for finding in findings:
            if type(finding) is not dict or finding.get("is_secret") is not False:
                raise SecurityGateError(
                    f"baseline finding has not been explicitly reviewed as a fixture: {raw_path}"
                )
            finding_count += 1
    return finding_count


def repository_files(*, root: Path = ROOT) -> tuple[str, ...]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=root,
        check=False,
        capture_output=True,
        shell=False,
    )
    if result.returncode != 0:
        raise SecurityGateError("git could not enumerate tracked and untracked repository files")
    try:
        files = tuple(part.decode("utf-8", errors="strict") for part in result.stdout.split(b"\0") if part)
    except UnicodeError as exc:
        raise SecurityGateError("git returned a non-UTF-8 repository path") from exc
    if not files or len(set(files)) != len(files):
        raise SecurityGateError("repository file enumeration is empty or duplicated")
    return tuple(sorted(files))


def build_secret_command(
    files: Sequence[str],
    *,
    hook_executable: str,
    baseline_path: Path = BASELINE_PATH,
) -> list[str]:
    if not files:
        raise SecurityGateError("secret scan requires at least one repository file")
    return [hook_executable, "--baseline", baseline_path.name, *files]


def build_dependency_command(*, audit_executable: str) -> list[str]:
    return [
        audit_executable,
        "--local",
        "--skip-editable",
        "--progress-spinner",
        "off",
        "--format",
        "json",
    ]


def build_utf8_environment(environ: Mapping[str, str] | None = None) -> dict[str, str]:
    environment = dict(os.environ if environ is None else environ)
    environment["PYTHONUTF8"] = "1"
    return environment


def _run(command: Sequence[str], *, root: Path = ROOT) -> None:
    result = subprocess.run(
        list(command),
        cwd=root,
        check=False,
        shell=False,
        env=build_utf8_environment(),
    )
    if result.returncode != 0:
        raise SecurityGateError(f"scanner returned non-zero exit code {result.returncode}")


def _installed_distributions() -> dict[str, str]:
    installed: dict[str, str] = {}
    root_name = canonicalize_name("ai-engineering-harness")
    for distribution in importlib.metadata.distributions():
        name = distribution.metadata.get("Name")
        if not isinstance(name, str) or not name:
            raise SecurityGateError("installed distribution has no valid package name")
        canonical_name = canonicalize_name(name)
        if canonical_name in installed:
            if canonical_name == root_name and installed[canonical_name] == distribution.version:
                continue
            raise SecurityGateError(f"installed distribution is duplicated: {canonical_name}")
        installed[canonical_name] = distribution.version
    return installed


def validate_dependency_report(
    document: object,
    *,
    installed: Mapping[str, str] | None = None,
) -> int:
    if type(document) is not dict or type(document.get("dependencies")) is not list:
        raise SecurityGateError("pip-audit did not return its complete JSON dependency report")
    if document.get("fixes") != []:
        raise SecurityGateError("pip-audit returned an unexpected fixes projection")

    root_name = canonicalize_name("ai-engineering-harness")
    observed: dict[str, str] = {}
    root_seen = False
    for entry in document["dependencies"]:
        if type(entry) is not dict or type(entry.get("name")) is not str:
            raise SecurityGateError("pip-audit returned a malformed dependency entry")
        name = canonicalize_name(entry["name"])
        skip_reason = entry.get("skip_reason")
        if name == root_name:
            if root_seen:
                raise SecurityGateError("pip-audit returned the project root more than once")
            root_seen = True
            if skip_reason != "distribution marked as editable":
                raise SecurityGateError("pip-audit did not identify the editable project root exactly")
            continue
        if skip_reason is not None:
            raise SecurityGateError(f"pip-audit skipped locked dependency: {name}")
        version = entry.get("version")
        vulnerabilities = entry.get("vulns")
        if type(version) is not str or vulnerabilities != []:
            raise SecurityGateError(f"pip-audit found or incompletely reported dependency: {name}")
        if name in observed:
            raise SecurityGateError(f"pip-audit returned duplicate dependency: {name}")
        observed[name] = version

    if not root_seen:
        raise SecurityGateError("pip-audit did not report the editable project root")
    expected = {
        canonicalize_name(name): version
        for name, version in (installed or _installed_distributions()).items()
        if canonicalize_name(name) != root_name
    }
    if observed != expected:
        missing = sorted(set(expected) - set(observed))
        unexpected = sorted(set(observed) - set(expected))
        mismatched = sorted(
            name for name in set(expected) & set(observed) if expected[name] != observed[name]
        )
        raise SecurityGateError(
            "pip-audit coverage does not match the synchronized environment: "
            f"missing={missing} unexpected={unexpected} mismatched={mismatched}"
        )
    return len(observed)


def run_secret_scan(*, root: Path = ROOT) -> None:
    reviewed = validate_reviewed_baseline(root / ".secrets.baseline", root=root)
    files = repository_files(root=root)
    command = build_secret_command(
        files,
        hook_executable=_tool_path("detect-secrets-hook"),
        baseline_path=root / ".secrets.baseline",
    )
    _run(command, root=root)
    print(f"F7.3 secret gate: files={len(files)} reviewed_fixtures={reviewed} new_secrets=0")


def run_dependency_audit(*, root: Path = ROOT) -> None:
    command = build_dependency_command(audit_executable=_tool_path("pip-audit"))
    result = subprocess.run(
        command,
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        shell=False,
    )
    if result.returncode != 0:
        raise SecurityGateError(f"pip-audit returned non-zero exit code {result.returncode}")
    try:
        document = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise SecurityGateError("pip-audit did not return valid JSON") from exc
    audited = validate_dependency_report(document)
    print(f"F7.3 dependency gate: audited={audited} skipped_dependencies=0 vulnerabilities=0")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("gate", choices=("secrets", "dependencies"))
    args = parser.parse_args(argv)
    try:
        if args.gate == "secrets":
            run_secret_scan()
        else:
            run_dependency_audit()
    except SecurityGateError as exc:
        parser.exit(1, f"F7.3 {args.gate} gate failed: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
