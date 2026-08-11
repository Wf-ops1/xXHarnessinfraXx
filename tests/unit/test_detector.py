"""Unit tests for fail-closed stack and command detection."""

from pathlib import Path

import pytest

from ai_engineering_harness.core.detector import StackDetectionError, StackDetector


def test_detect_python_stack_from_real_pyproject_configuration(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        """
[build-system]
requires = ["setuptools>=61"]
build-backend = "setuptools.build_meta"

[project]
name = "sample"
version = "0.1.0"
dependencies = []

[project.optional-dependencies]
dev = ["pytest>=8", "mypy>=1", "ruff>=0.11"]

[tool.pytest.ini_options]
testpaths = ["tests"]

[tool.mypy]
python_version = "3.11"

[tool.ruff]
line-length = 100
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "uv.lock").write_text("version = 1\n", encoding="utf-8")

    stack = StackDetector(project_root=tmp_path).detect()

    assert stack.language == "python"
    assert stack.package_manager == "uv"
    assert stack.type_checker == "mypy"
    assert stack.test_runner == "pytest"
    assert stack.linter == "ruff"
    assert stack.build_tool == "build"
    assert stack.security_scanner is None
    assert stack.detected_files == ("pyproject.toml", "uv.lock")
    assert tuple(command.gate_id for command in stack.commands) == (
        "typecheck",
        "lint",
        "unit_test",
        "build",
    )
    assert stack.commands[0].argv_tail == ("-m", "mypy", ".")
    assert stack.commands[1].argv_tail == ("-m", "ruff", "check", ".")


def test_detect_node_stack_uses_manifest_scripts_and_lockfile(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        """{
  "name": "sample",
  "scripts": {
    "typecheck": "tsc --noEmit",
    "lint": "eslint .",
    "test": "vitest run",
    "build": "vite build"
  },
  "devDependencies": {
    "typescript": "1.0.0",
    "eslint": "1.0.0",
    "vitest": "1.0.0"
  }
}
""",
        encoding="utf-8",
    )
    (tmp_path / "pnpm-lock.yaml").write_text("lockfileVersion: 9\n", encoding="utf-8")

    stack = StackDetector(project_root=tmp_path).detect()

    assert stack.language == "typescript/javascript"
    assert stack.package_manager == "pnpm"
    assert stack.linter == "eslint"
    assert tuple(command.argv_tail for command in stack.commands) == (
        ("run", "typecheck"),
        ("run", "lint"),
        ("run", "test"),
        ("run", "build"),
    )


def test_detect_go_stack(tmp_path: Path) -> None:
    (tmp_path / "go.mod").write_text("module example.test/sample\n", encoding="utf-8")
    stack = StackDetector(project_root=tmp_path).detect()
    assert stack.language == "go"
    assert stack.package_manager == "go"
    assert tuple(command.gate_id for command in stack.commands) == (
        "typecheck",
        "unit_test",
        "build",
    )


def test_detect_rust_stack(tmp_path: Path) -> None:
    (tmp_path / "Cargo.toml").write_text(
        '[package]\nname = "sample"\nversion = "0.1.0"\n', encoding="utf-8"
    )
    stack = StackDetector(project_root=tmp_path).detect()
    assert stack.language == "rust"
    assert stack.package_manager == "cargo"


def test_detect_java_stack(tmp_path: Path) -> None:
    (tmp_path / "pom.xml").write_text("<project/>\n", encoding="utf-8")
    stack = StackDetector(project_root=tmp_path).detect()
    assert stack.language == "java"
    assert stack.package_manager == "maven"


@pytest.mark.parametrize(
    ("filename", "content", "message"),
    [
        ("pyproject.toml", "[tool.mypy\n", "not valid TOML"),
        ("package.json", '{"scripts": {}, "scripts": {}}', "duplicate key"),
    ],
)
def test_invalid_configuration_fails_closed(
    tmp_path: Path,
    filename: str,
    content: str,
    message: str,
) -> None:
    (tmp_path / filename).write_text(content, encoding="utf-8")

    with pytest.raises(StackDetectionError, match=message):
        StackDetector(tmp_path).detect()


def test_multiple_stack_manifests_fail_closed(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='sample'\n", encoding="utf-8")
    (tmp_path / "package.json").write_text('{"name":"sample"}\n', encoding="utf-8")

    with pytest.raises(StackDetectionError, match="multiple supported stack manifests"):
        StackDetector(tmp_path).detect()


def test_ambiguous_python_tools_fail_closed(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[tool.mypy]\npython_version='3.11'\n[tool.pyright]\ntypeCheckingMode='strict'\n",
        encoding="utf-8",
    )

    with pytest.raises(StackDetectionError, match="ambiguous configured tools"):
        StackDetector(tmp_path).detect()


def test_dependency_only_tool_records_the_real_pyproject_source(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='sample'\nversion='0.1.0'\ndependencies=['pytest>=8']\n",
        encoding="utf-8",
    )

    stack = StackDetector(tmp_path).detect()

    assert stack.test_runner == "pytest"
    assert stack.commands[0].source == "pyproject.toml:project.dependencies"


def test_unknown_stack_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(StackDetectionError, match="could not be detected"):
        StackDetector(tmp_path).detect()


@pytest.mark.parametrize(
    ("filename", "content", "message"),
    [
        ("go.mod", "go 1.24\n", "declare one module path"),
        ("pom.xml", "<not-project/>\n", "root element must be project"),
        ("build.gradle", "", "must not be empty"),
    ],
)
def test_non_python_manifests_are_read_before_commands_are_selected(
    tmp_path: Path,
    filename: str,
    content: str,
    message: str,
) -> None:
    (tmp_path / filename).write_text(content, encoding="utf-8")

    with pytest.raises(StackDetectionError, match=message):
        StackDetector(tmp_path).detect()
