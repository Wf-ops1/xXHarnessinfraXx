"""Regression tests for repository text encoding and CLI console compatibility."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
TEXT_EXTENSIONS = {".py", ".md", ".yaml", ".yml", ".toml", ".json"}
IGNORED_DIRECTORIES = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "env",
    "venv",
}
MOJIBAKE_PATTERN = re.compile("\u00c3|\u00e2\u0153|\u00f0\u0178")
CLI_ENCODINGS = ("utf-8", "cp1252", "cp850")
CLI_COMMANDS = (("--help",), ("doctor",))
LEGACY_TASK_MANIFEST = REPOSITORY_ROOT / "docs" / "tasks" / "migration-manifest.json"


def _repository_text_files() -> list[Path]:
    files: list[Path] = []

    for path in REPOSITORY_ROOT.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in TEXT_EXTENSIONS:
            continue
        if any(part in IGNORED_DIRECTORIES for part in path.relative_to(REPOSITORY_ROOT).parts):
            continue
        files.append(path)

    return sorted(files)


def _mojibake_scope_files() -> list[Path]:
    legacy_payloads: set[str] = set()
    if LEGACY_TASK_MANIFEST.is_file():
        manifest = json.loads(
            LEGACY_TASK_MANIFEST.read_text(encoding="utf-8", errors="strict")
        )
        legacy_payloads = {entry["path"] for entry in manifest["entries"]}

    files = [
        path
        for root in (REPOSITORY_ROOT / "src", REPOSITORY_ROOT / "docs")
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in TEXT_EXTENSIONS
        and path.relative_to(REPOSITORY_ROOT).as_posix() not in legacy_payloads
    ]
    files.append(REPOSITORY_ROOT / "README.md")
    return sorted(files)


class RepositoryEncodingTests(unittest.TestCase):
    def test_repository_text_files_are_strict_utf8(self) -> None:
        failures: list[str] = []

        for path in _repository_text_files():
            try:
                path.read_text(encoding="utf-8", errors="strict")
            except UnicodeError as error:
                failures.append(f"{path.relative_to(REPOSITORY_ROOT)}: {error}")

        self.assertFalse(failures, "Invalid UTF-8 files:\n" + "\n".join(failures))

    def test_editorconfig_enforces_utf8(self) -> None:
        editorconfig = (REPOSITORY_ROOT / ".editorconfig").read_text(
            encoding="utf-8",
            errors="strict",
        )

        self.assertRegex(editorconfig, r"(?m)^root\s*=\s*true$")
        self.assertRegex(editorconfig, r"(?m)^charset\s*=\s*utf-8$")
        self.assertRegex(editorconfig, r"(?m)^insert_final_newline\s*=\s*true$")

    def test_source_docs_and_readme_have_no_known_mojibake(self) -> None:
        failures: list[str] = []

        for path in _mojibake_scope_files():
            text = path.read_text(encoding="utf-8", errors="strict")
            if MOJIBAKE_PATTERN.search(text):
                failures.append(str(path.relative_to(REPOSITORY_ROOT)))

        self.assertFalse(failures, "Known mojibake found in: " + ", ".join(failures))

    def test_cli_help_and_doctor_support_windows_encodings(self) -> None:
        for encoding in CLI_ENCODINGS:
            for arguments in CLI_COMMANDS:
                with self.subTest(encoding=encoding, arguments=arguments):
                    environment = os.environ.copy()
                    source_path = str(REPOSITORY_ROOT / "src")
                    existing_python_path = environment.get("PYTHONPATH")
                    environment["PYTHONPATH"] = (
                        os.pathsep.join((source_path, existing_python_path))
                        if existing_python_path
                        else source_path
                    )
                    environment["PYTHONIOENCODING"] = encoding
                    environment["PYTHONUTF8"] = "0"

                    result = subprocess.run(
                        [
                            sys.executable,
                            "-m",
                            "ai_engineering_harness.cli.main",
                            *arguments,
                        ],
                        cwd=REPOSITORY_ROOT,
                        env=environment,
                        capture_output=True,
                        check=False,
                    )
                    stdout = result.stdout.decode(encoding, errors="strict")
                    stderr = result.stderr.decode(encoding, errors="strict")
                    combined_output = stdout + stderr

                    expected_returncode = 1 if arguments == ("doctor",) else 0
                    self.assertEqual(result.returncode, expected_returncode, combined_output)
                    self.assertNotIn("\ufffd", combined_output)
                    self.assertIsNone(MOJIBAKE_PATTERN.search(combined_output))

                    if arguments == ("doctor",):
                        expected_status = "✖ UNHEALTHY" if encoding == "utf-8" else "[FAIL] UNHEALTHY"
                        self.assertIn(expected_status, stdout)


if __name__ == "__main__":
    unittest.main()
