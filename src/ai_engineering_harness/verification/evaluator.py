"""Avaliador de argumentos de verificação mapeados por linguagem."""

from typing import ClassVar, cast

from ai_engineering_harness.contracts.policies import (
    CANONICAL_VERIFICATION_GATE_IDS,
    VerificationGateId,
)


class VerificationEvaluator:
    """Mapeia tipos abstratos de gate para argv estático e auditável."""

    _argv_by_language: ClassVar[
        dict[str, dict[VerificationGateId, tuple[str, ...]]]
    ] = {
        "python": {
            "typecheck": ("mypy", "."),
            "lint": ("ruff", "check", "."),
            "unit_test": ("pytest",),
            "build": ("python", "-m", "build"),
        },
        "typescript/javascript": {
            "typecheck": ("tsc",),
            "lint": ("eslint", "."),
            "unit_test": ("vitest", "run"),
            "build": ("npm", "run", "build"),
        },
        "go": {
            "typecheck": ("go", "vet", "./..."),
            "lint": ("golangci-lint", "run"),
            "unit_test": ("go", "test", "./..."),
            "build": ("go", "build", "./..."),
        },
        "rust": {
            "typecheck": ("cargo", "check"),
            "lint": ("cargo", "clippy"),
            "unit_test": ("cargo", "test"),
            "build": ("cargo", "build"),
        },
        "java": {
            "typecheck": ("mvn", "compile"),
            "lint": ("mvn", "checkstyle:check"),
            "unit_test": ("mvn", "test"),
            "build": ("mvn", "package"),
        },
    }

    @classmethod
    def canonical_gate_ids(cls) -> tuple[VerificationGateId, ...]:
        """Return the single ordered gate-id vocabulary shared with policy contracts."""

        return CANONICAL_VERIFICATION_GATE_IDS

    @classmethod
    def is_canonical_gate_id(cls, gate_type: object) -> bool:
        """Return whether one exact value is a canonical verification gate id."""

        return type(gate_type) is str and gate_type in CANONICAL_VERIFICATION_GATE_IDS

    _aliases: ClassVar[dict[str, str]] = {
        "py": "python",
        "js": "typescript/javascript",
        "ts": "typescript/javascript",
        "javascript": "typescript/javascript",
        "typescript": "typescript/javascript",
        "node": "typescript/javascript",
        "golang": "go",
    }

    @classmethod
    def get_argv(cls, language: str, gate_type: str) -> tuple[str, ...] | None:
        """Return immutable argv for one applicable gate."""

        if not cls.is_canonical_gate_id(gate_type):
            return None
        lang_key = language.lower().strip()
        lang_key = cls._aliases.get(lang_key, lang_key)
        lang_gates = cls._argv_by_language.get(lang_key, {})
        return lang_gates.get(cast(VerificationGateId, gate_type))

    @classmethod
    def get_command(cls, language: str, gate_type: str) -> str | None:
        """Return the legacy display-only representation used in evidence."""

        argv = cls.get_argv(language, gate_type)
        return " ".join(argv) if argv is not None else None
