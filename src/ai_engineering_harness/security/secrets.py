"""Gerenciador seguro de secrets exclusivamente em memória."""

import os
from typing import ClassVar

from .trust import TrustEvaluationResult


class SecretManager:
    """Carrega chaves e tokens de variáveis de ambiente sem persistir no disco."""

    _sensitive_keys: ClassVar[list[str]] = [
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "SERENA_MCP_TOKEN",
        "CODEBASE_MEMORY_TOKEN",
        "HARNESS_SECRET_KEY"
    ]

    @classmethod
    def get_secret(
        cls,
        key: str,
        *,
        boundary: TrustEvaluationResult,
        consumer: str,
        default: str | None = None,
    ) -> str | None:
        """Read one environment value only after an exact boundary decision."""

        if not isinstance(boundary, TrustEvaluationResult):
            raise TypeError("boundary must be a TrustEvaluationResult")
        boundary.require_secret(key, consumer=consumer)
        return os.environ.get(key, default)

    @classmethod
    def load_all_known_secrets(
        cls,
        *,
        boundary: TrustEvaluationResult,
        consumer: str,
    ) -> dict[str, str]:
        """Return only known secrets explicitly granted to one consumer."""

        if not isinstance(boundary, TrustEvaluationResult):
            raise TypeError("boundary must be a TrustEvaluationResult")
        allowed = {
            grant.name
            for grant in boundary.secret_grants
            if consumer in grant.consumers
        }
        found: dict[str, str] = {}
        for key in cls._sensitive_keys:
            if key not in allowed:
                continue
            boundary.require_secret(key, consumer=consumer)
            val = os.environ.get(key)
            if val:
                found[key] = val
        return found
