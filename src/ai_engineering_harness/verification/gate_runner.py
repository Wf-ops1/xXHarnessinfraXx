"""Runner poliglota de tipos abstratos de gate de verificação."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from ai_engineering_harness.security import PathGuard, Redactor
from ai_engineering_harness.tools.adapters.terminal import (
    CommandRequest,
    TerminalAdapter,
    TerminalAdapterError,
    TerminalConfigurationError,
)
from ai_engineering_harness.verification.evaluator import VerificationEvaluator
from ai_engineering_harness.verification.results import GateResult, VerificationSuiteResult


class GateRunner:
    """Executa somente verificadores estáticos aplicáveis ao projeto."""

    _SAFE_ENVIRONMENT_NAMES = ("PATH", "SYSTEMROOT")

    def __init__(self, language: str, working_dir: Path):
        self.language = language
        self.working_dir = working_dir
        self._path_guard = PathGuard(working_dir)
        self._environment = self._capture_environment()
        self._adapters: dict[str, TerminalAdapter] = {}

    def run_applicable_gates(self, active_gates: list[str]) -> VerificationSuiteResult:
        results = []
        all_passed = True

        for gate in active_gates:
            argv = VerificationEvaluator.get_argv(self.language, gate)
            if argv is None:
                continue
            command = VerificationEvaluator.get_command(self.language, gate)
            assert command is not None

            try:
                adapter = self._adapter_for(argv[0])
                term_res = adapter.execute(
                    CommandRequest(
                        argv=argv,
                        cwd=".",
                        timeout_seconds=30,
                        env_allowlist=tuple(self._environment),
                        max_output_bytes=1_000_000,
                    )
                )
                passed = not term_res.timed_out and term_res.exit_code == 0
                stdout = term_res.stdout
                stderr = term_res.stderr
            except TerminalAdapterError as exc:
                passed = False
                stdout = ""
                stderr = Redactor.redact_text(str(exc))

            if not passed:
                all_passed = False
            results.append(
                GateResult(
                    gate_type=gate,
                    command=command,
                    passed=passed,
                    stdout=stdout,
                    stderr=stderr,
                )
            )

        return VerificationSuiteResult(
            all_passed=all_passed,
            total_gates=len(results),
            passed_gates=sum(1 for result in results if result.passed),
            gate_results=results,
        )

    def _adapter_for(self, executable_alias: str) -> TerminalAdapter:
        adapter = self._adapters.get(executable_alias)
        if adapter is not None:
            return adapter

        search_path = next(
            (value for key, value in self._environment.items() if key.casefold() == "path"),
            None,
        )
        resolved = shutil.which(executable_alias, path=search_path)
        if resolved is None:
            raise TerminalConfigurationError("verification executable is not available")
        try:
            executable_path = Path(resolved).resolve(strict=True)
        except (OSError, RuntimeError, ValueError) as exc:
            raise TerminalConfigurationError(
                "verification executable could not be resolved safely"
            ) from exc
        adapter = TerminalAdapter(
            path_guard=self._path_guard,
            executables={executable_alias: executable_path},
            environment=self._environment,
        )
        self._adapters[executable_alias] = adapter
        return adapter

    @classmethod
    def _capture_environment(cls) -> dict[str, str]:
        captured: dict[str, str] = {}
        current = {name.casefold(): (name, value) for name, value in os.environ.items()}
        for allowed_name in cls._SAFE_ENVIRONMENT_NAMES:
            entry = current.get(allowed_name.casefold())
            if entry is not None:
                name, value = entry
                captured[name] = value
        return captured
