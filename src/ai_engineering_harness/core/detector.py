"""Fail-closed detection of the target worktree's configured stack."""

from __future__ import annotations

import json
import re
import tomllib
import xml.etree.ElementTree as ET
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict


class StackDetectionError(ValueError):
    """The worktree does not contain one unambiguous supported stack."""


class DetectedCommand(BaseModel):
    """One command selected from project configuration, before tool resolution."""

    model_config = ConfigDict(strict=True, frozen=True)

    gate_id: str
    tool: str
    invocation: Literal["executable", "python_module"]
    argv_tail: tuple[str, ...]
    source: str


class DetectedStack(BaseModel):
    """Immutable evidence extracted from the worktree's real manifests."""

    model_config = ConfigDict(strict=True, frozen=True)

    language: str
    package_manager: str | None
    test_runner: str | None
    linter: str | None
    type_checker: str | None = None
    build_tool: str | None
    security_scanner: str | None = None
    detected_files: tuple[str, ...]
    configuration_sources: tuple[str, ...] = ()
    commands: tuple[DetectedCommand, ...] = ()


class StackDetector:
    """Read root manifests and derive the only configured verification commands."""

    _DEPENDENCY_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9_.-]*)")
    _PYTHON_MARKERS = frozenset({"pyproject.toml", "setup.py", "requirements.txt"})
    _NODE_MARKERS = frozenset({"package.json"})
    _GO_MARKERS = frozenset({"go.mod"})
    _RUST_MARKERS = frozenset({"Cargo.toml"})
    _JAVA_MARKERS = frozenset({"pom.xml", "build.gradle", "build.gradle.kts"})

    def __init__(self, project_root: Path | None = None):
        raw_root = Path.cwd() if project_root is None else Path(project_root)
        try:
            root = raw_root.resolve(strict=True)
        except (OSError, RuntimeError, ValueError) as exc:
            raise StackDetectionError("project root must resolve to an existing directory") from exc
        if not root.is_dir():
            raise StackDetectionError("project root must resolve to an existing directory")
        self.project_root = root

    def detect(self) -> DetectedStack:
        """Return one configured stack or fail when the root is unsupported/ambiguous."""

        try:
            files = tuple(
                sorted(entry.name for entry in self.project_root.iterdir() if entry.is_file())
            )
        except OSError as exc:
            raise StackDetectionError("project root could not be inspected") from exc
        file_names = frozenset(files)

        matches: list[str] = []
        if file_names & self._PYTHON_MARKERS:
            matches.append("python")
        if file_names & self._NODE_MARKERS:
            matches.append("typescript/javascript")
        if file_names & self._GO_MARKERS:
            matches.append("go")
        if file_names & self._RUST_MARKERS:
            matches.append("rust")
        if file_names & self._JAVA_MARKERS:
            matches.append("java")
        if not matches:
            raise StackDetectionError("project stack could not be detected from root manifests")
        if len(matches) != 1:
            raise StackDetectionError(
                "project root contains multiple supported stack manifests: "
                + ", ".join(matches)
            )

        language = matches[0]
        if language == "python":
            return self._detect_python(file_names)
        if language == "typescript/javascript":
            return self._detect_node(file_names)
        if language == "go":
            return self._detect_go()
        if language == "rust":
            return self._detect_rust()
        return self._detect_java(file_names)

    def _detect_python(self, files: frozenset[str]) -> DetectedStack:
        pyproject: Mapping[str, object] = {}
        sources: list[str] = []
        dependencies: Mapping[str, str] = {}
        tool_table: Mapping[str, object] = {}
        if "pyproject.toml" in files:
            pyproject = self._read_toml("pyproject.toml")
            tool_table = self._mapping(pyproject.get("tool"), "pyproject.toml:[tool]")
            dependencies = self._python_dependencies(pyproject)

        package_manager = self._python_package_manager(files, tool_table)
        type_checker_config = self._one_configured_tool(
            gate_id="typecheck",
            candidates=("mypy", "pyright"),
            tool_table=tool_table,
            dependencies=dependencies,
        )
        linter_config = self._one_configured_tool(
            gate_id="lint",
            candidates=("ruff", "pylint", "flake8"),
            tool_table=tool_table,
            dependencies=dependencies,
        )
        test_runner_config = self._one_configured_tool(
            gate_id="unit_test",
            candidates=("pytest",),
            tool_table=tool_table,
            dependencies=dependencies,
        )
        security_scanner_config = self._one_configured_tool(
            gate_id="security_scan",
            candidates=("bandit",),
            tool_table=tool_table,
            dependencies=dependencies,
        )

        type_checker = type_checker_config[0] if type_checker_config is not None else None
        linter = linter_config[0] if linter_config is not None else None
        test_runner = test_runner_config[0] if test_runner_config is not None else None
        security_scanner = (
            security_scanner_config[0]
            if security_scanner_config is not None
            else None
        )

        build_system = self._mapping(
            pyproject.get("build-system"), "pyproject.toml:[build-system]"
        )
        build_tool = "build" if build_system else None

        commands: list[DetectedCommand] = []
        if type_checker is not None:
            assert type_checker_config is not None
            sources.append(type_checker_config[1])
            typecheck_tail = ("-m", type_checker, ".")
            commands.append(
                DetectedCommand(
                    gate_id="typecheck",
                    tool=type_checker,
                    invocation="python_module",
                    argv_tail=typecheck_tail,
                    source=sources[-1],
                )
            )
        if linter is not None:
            assert linter_config is not None
            sources.append(linter_config[1])
            linter_tail: tuple[str, ...] = (
                ("-m", linter, "check", ".")
                if linter == "ruff"
                else ("-m", linter, ".")
            )
            commands.append(
                DetectedCommand(
                    gate_id="lint",
                    tool=linter,
                    invocation="python_module",
                    argv_tail=linter_tail,
                    source=sources[-1],
                )
            )
        if test_runner is not None:
            assert test_runner_config is not None
            source_name = test_runner_config[1]
            sources.append(source_name)
            commands.append(
                DetectedCommand(
                    gate_id="unit_test",
                    tool=test_runner,
                    invocation="python_module",
                    argv_tail=("-m", test_runner),
                    source=source_name,
                )
            )
        if build_tool is not None:
            source_name = "pyproject.toml:build-system"
            sources.append(source_name)
            commands.append(
                DetectedCommand(
                    gate_id="build",
                    tool=build_tool,
                    invocation="python_module",
                    argv_tail=("-m", "build"),
                    source=source_name,
                )
            )
        if security_scanner is not None:
            assert security_scanner_config is not None
            source_name = security_scanner_config[1]
            sources.append(source_name)
            commands.append(
                DetectedCommand(
                    gate_id="security_scan",
                    tool=security_scanner,
                    invocation="python_module",
                    argv_tail=("-m", security_scanner, "-r", "."),
                    source=source_name,
                )
            )

        detected_files = tuple(
            name
            for name in (
                "pyproject.toml",
                "uv.lock",
                "poetry.lock",
                "pdm.lock",
                "Pipfile.lock",
                "setup.py",
                "requirements.txt",
            )
            if name in files
        )
        return DetectedStack(
            language="python",
            package_manager=package_manager,
            test_runner=test_runner,
            linter=linter,
            type_checker=type_checker,
            build_tool=build_tool,
            security_scanner=security_scanner,
            detected_files=detected_files,
            configuration_sources=tuple(sources),
            commands=tuple(commands),
        )

    def _detect_node(self, files: frozenset[str]) -> DetectedStack:
        document = self._read_json("package.json")
        scripts = self._mapping(document.get("scripts"), "package.json:scripts")
        dependencies = self._node_dependencies(document)
        package_manager = self._node_package_manager(files)

        commands: list[DetectedCommand] = []
        gate_scripts = {
            "typecheck": "typecheck",
            "lint": "lint",
            "unit_test": "test",
            "build": "build",
            "security_scan": "security",
        }
        for gate_id, script_name in gate_scripts.items():
            script = scripts.get(script_name)
            if script is None:
                continue
            if type(script) is not str or not script.strip():
                raise StackDetectionError(
                    f"package.json script {script_name!r} must be non-empty text"
                )
            commands.append(
                DetectedCommand(
                    gate_id=gate_id,
                    tool=package_manager,
                    invocation="executable",
                    argv_tail=("run", script_name),
                    source=f"package.json:scripts.{script_name}",
                )
            )

        return DetectedStack(
            language="typescript/javascript",
            package_manager=package_manager,
            test_runner=self._first_present(("vitest", "jest"), dependencies),
            linter=self._first_present(("eslint",), dependencies),
            type_checker=self._first_present(("typescript",), dependencies),
            build_tool="package-script" if "build" in scripts else None,
            security_scanner="package-script" if "security" in scripts else None,
            detected_files=tuple(
                name
                for name in ("package.json", "pnpm-lock.yaml", "yarn.lock", "package-lock.json")
                if name in files
            ),
            configuration_sources=tuple(command.source for command in commands),
            commands=tuple(commands),
        )

    def _detect_go(self) -> DetectedStack:
        go_mod = self._read_text_configuration("go.mod")
        if re.search(r"(?m)^\s*module\s+\S+\s*$", go_mod) is None:
            raise StackDetectionError("go.mod must declare one module path")
        commands = (
            self._executable_command("typecheck", "go", ("vet", "./..."), "go.mod"),
            self._executable_command("unit_test", "go", ("test", "./..."), "go.mod"),
            self._executable_command("build", "go", ("build", "./..."), "go.mod"),
        )
        return DetectedStack(
            language="go",
            package_manager="go",
            test_runner="go",
            linter=None,
            type_checker="go",
            build_tool="go",
            detected_files=("go.mod",),
            configuration_sources=("go.mod",),
            commands=commands,
        )

    def _detect_rust(self) -> DetectedStack:
        self._read_toml("Cargo.toml")
        commands = (
            self._executable_command("typecheck", "cargo", ("check",), "Cargo.toml"),
            self._executable_command("lint", "cargo", ("clippy",), "Cargo.toml"),
            self._executable_command("unit_test", "cargo", ("test",), "Cargo.toml"),
            self._executable_command("build", "cargo", ("build",), "Cargo.toml"),
        )
        return DetectedStack(
            language="rust",
            package_manager="cargo",
            test_runner="cargo",
            linter="cargo-clippy",
            type_checker="cargo-check",
            build_tool="cargo",
            detected_files=("Cargo.toml",),
            configuration_sources=("Cargo.toml",),
            commands=commands,
        )

    def _detect_java(self, files: frozenset[str]) -> DetectedStack:
        if "pom.xml" in files and ({"build.gradle", "build.gradle.kts"} & files):
            raise StackDetectionError("java project contains both Maven and Gradle manifests")
        if "pom.xml" in files:
            pom = self._read_text_configuration("pom.xml")
            try:
                root = ET.fromstring(pom)
            except ET.ParseError as exc:
                raise StackDetectionError("pom.xml is not valid XML") from exc
            if root.tag.rsplit("}", maxsplit=1)[-1] != "project":
                raise StackDetectionError("pom.xml root element must be project")
            tool = "mvn"
            manifest = "pom.xml"
            commands = (
                self._executable_command("typecheck", tool, ("compile",), manifest),
                self._executable_command("lint", tool, ("checkstyle:check",), manifest),
                self._executable_command("unit_test", tool, ("test",), manifest),
                self._executable_command("build", tool, ("package",), manifest),
            )
            package_manager = "maven"
        else:
            tool = "gradle"
            manifest = "build.gradle.kts" if "build.gradle.kts" in files else "build.gradle"
            if not self._read_text_configuration(manifest).strip():
                raise StackDetectionError(f"{manifest} must not be empty")
            commands = (
                self._executable_command("typecheck", tool, ("classes",), manifest),
                self._executable_command("lint", tool, ("check",), manifest),
                self._executable_command("unit_test", tool, ("test",), manifest),
                self._executable_command("build", tool, ("build",), manifest),
            )
            package_manager = "gradle"
        return DetectedStack(
            language="java",
            package_manager=package_manager,
            test_runner=tool,
            linter=tool,
            type_checker=tool,
            build_tool=tool,
            detected_files=(manifest,),
            configuration_sources=(manifest,),
            commands=commands,
        )

    def _read_toml(self, filename: str) -> Mapping[str, object]:
        path = self._regular_configuration_file(filename)
        try:
            with path.open("rb") as stream:
                document = tomllib.load(stream)
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise StackDetectionError(f"{filename} is not valid TOML") from exc
        if not isinstance(document, dict):  # pragma: no cover - tomllib contract
            raise StackDetectionError(f"{filename} root must be a table")
        return document

    def _read_json(self, filename: str) -> Mapping[str, object]:
        path = self._regular_configuration_file(filename)

        def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
            result: dict[str, object] = {}
            for key, value in pairs:
                if key in result:
                    raise StackDetectionError(f"{filename} contains duplicate key {key!r}")
                result[key] = value
            return result

        try:
            document = json.loads(
                path.read_text(encoding="utf-8", errors="strict"),
                object_pairs_hook=reject_duplicates,
                parse_constant=lambda value: self._reject_json_constant(filename, value),
            )
        except StackDetectionError:
            raise
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise StackDetectionError(f"{filename} is not valid UTF-8 JSON") from exc
        if not isinstance(document, dict):
            raise StackDetectionError(f"{filename} root must be an object")
        return document

    def _read_text_configuration(self, filename: str) -> str:
        path = self._regular_configuration_file(filename)
        try:
            return path.read_text(encoding="utf-8", errors="strict")
        except (OSError, UnicodeError) as exc:
            raise StackDetectionError(f"{filename} is not valid UTF-8 text") from exc

    def _regular_configuration_file(self, filename: str) -> Path:
        path = self.project_root / filename
        if path.is_symlink() or not path.is_file():
            raise StackDetectionError(f"{filename} must be a regular file in the project root")
        return path

    @staticmethod
    def _mapping(value: object, location: str) -> Mapping[str, object]:
        if value is None:
            return {}
        if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
            raise StackDetectionError(f"{location} must be a string-keyed table/object")
        return value

    def _python_dependencies(self, document: Mapping[str, object]) -> dict[str, str]:
        project = self._mapping(document.get("project"), "pyproject.toml:[project]")
        raw_dependencies: list[tuple[object, str]] = []
        dependencies = project.get("dependencies")
        if dependencies is not None:
            if not isinstance(dependencies, Sequence) or isinstance(dependencies, (str, bytes)):
                raise StackDetectionError("pyproject.toml project.dependencies must be an array")
            raw_dependencies.extend(
                (value, "pyproject.toml:project.dependencies")
                for value in dependencies
            )
        optional = self._mapping(
            project.get("optional-dependencies"),
            "pyproject.toml:[project.optional-dependencies]",
        )
        for group, values in optional.items():
            if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
                raise StackDetectionError(
                    f"pyproject.toml optional dependency group {group!r} must be an array"
                )
            raw_dependencies.extend(
                (value, f"pyproject.toml:project.optional-dependencies.{group}")
                for value in values
            )

        normalized: dict[str, str] = {}
        for value, source in raw_dependencies:
            if type(value) is not str:
                raise StackDetectionError("pyproject.toml dependencies must contain only strings")
            match = self._DEPENDENCY_NAME.match(value)
            if match is None:
                raise StackDetectionError("pyproject.toml contains an invalid dependency entry")
            name = match.group(1).lower().replace("_", "-")
            normalized.setdefault(name, source)
        return normalized

    def _node_dependencies(self, document: Mapping[str, object]) -> frozenset[str]:
        names: set[str] = set()
        for field in ("dependencies", "devDependencies", "optionalDependencies"):
            entries = self._mapping(document.get(field), f"package.json:{field}")
            names.update(name.lower() for name in entries)
        return frozenset(names)

    def _one_configured_tool(
        self,
        *,
        gate_id: str,
        candidates: tuple[str, ...],
        tool_table: Mapping[str, object],
        dependencies: Mapping[str, str],
    ) -> tuple[str, str] | None:
        configured = tuple(
            candidate
            for candidate in candidates
            if candidate in tool_table or candidate.replace("_", "-") in dependencies
        )
        if len(configured) > 1:
            raise StackDetectionError(
                f"python gate {gate_id!r} has ambiguous configured tools: "
                + ", ".join(configured)
            )
        if not configured:
            return None
        selected = configured[0]
        source = (
            f"pyproject.toml:tool.{selected}"
            if selected in tool_table
            else dependencies[selected.replace("_", "-")]
        )
        return selected, source

    def _python_package_manager(
        self, files: frozenset[str], tool_table: Mapping[str, object]
    ) -> str:
        candidates: list[str] = []
        if "uv.lock" in files:
            candidates.append("uv")
        if "poetry.lock" in files or "poetry" in tool_table:
            candidates.append("poetry")
        if "pdm.lock" in files or "pdm" in tool_table:
            candidates.append("pdm")
        if "Pipfile.lock" in files:
            candidates.append("pipenv")
        if len(candidates) > 1:
            raise StackDetectionError(
                "python project has ambiguous package-manager configuration: "
                + ", ".join(candidates)
            )
        return candidates[0] if candidates else "pip"

    @staticmethod
    def _node_package_manager(files: frozenset[str]) -> str:
        candidates = tuple(
            manager
            for marker, manager in (
                ("pnpm-lock.yaml", "pnpm"),
                ("yarn.lock", "yarn"),
                ("package-lock.json", "npm"),
            )
            if marker in files
        )
        if len(candidates) > 1:
            raise StackDetectionError(
                "node project has ambiguous package-manager lockfiles: "
                + ", ".join(candidates)
            )
        return candidates[0] if candidates else "npm"

    @staticmethod
    def _first_present(candidates: tuple[str, ...], available: frozenset[str]) -> str | None:
        return next((candidate for candidate in candidates if candidate in available), None)

    @staticmethod
    def _executable_command(
        gate_id: str,
        tool: str,
        argv_tail: tuple[str, ...],
        source: str,
    ) -> DetectedCommand:
        return DetectedCommand(
            gate_id=gate_id,
            tool=tool,
            invocation="executable",
            argv_tail=argv_tail,
            source=source,
        )

    @staticmethod
    def _reject_json_constant(filename: str, value: str) -> None:
        raise StackDetectionError(f"{filename} contains invalid JSON constant {value!r}")


__all__ = [
    "DetectedCommand",
    "DetectedStack",
    "StackDetectionError",
    "StackDetector",
]
