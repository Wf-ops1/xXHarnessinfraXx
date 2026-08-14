"""Provider local real por endpoint OpenAI Chat Completions compatível."""

from __future__ import annotations

import os

import httpx

from ai_engineering_harness.models.provider import OpenAICompatibleHTTPProvider
from ai_engineering_harness.security import RedactionContext


class LocalAdapter(OpenAICompatibleHTTPProvider):
    """Executa chamadas reais contra um servidor local configurável."""

    def __init__(
        self,
        model_name: str | None = None,
        *,
        api_key: str | None = None,
        redaction_context: RedactionContext | None = None,
        base_url: str | None = None,
        timeout_seconds: float = 60.0,
        max_retries: int = 2,
        backoff_seconds: float = 0.25,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        super().__init__(
            provider_id="local",
            model_name=model_name or os.environ.get("HARNESS_LOCAL_MODEL_NAME", "llama3"),
            base_url=base_url
            or os.environ.get("HARNESS_LOCAL_MODEL_BASE_URL", "http://127.0.0.1:11434/v1"),
            api_style="chat_completions",
            api_key=api_key,
            redaction_context=redaction_context,
            requires_api_key=False,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            backoff_seconds=backoff_seconds,
            transport=transport,
        )
