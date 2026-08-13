"""Registry configurável e fail-closed de providers de modelo."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import Annotated, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from ai_engineering_harness.models.adapters.anthropic import AnthropicAdapter
from ai_engineering_harness.models.adapters.local import LocalAdapter
from ai_engineering_harness.models.adapters.openai import OpenAIAdapter
from ai_engineering_harness.models.provider import BaseLLMProvider
from ai_engineering_harness.security import SecretManager, TrustEvaluationResult

AdapterId = Literal["openai", "anthropic", "local"]
_NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ProviderConfiguration(BaseModel):
    """Configuração sem segredo de um provider efetivo."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    adapter: AdapterId
    model: _NonEmptyStr
    base_url: _NonEmptyStr | None = None
    api_key_env: Annotated[
        str,
        StringConstraints(pattern=r"^[A-Z][A-Z0-9_]*$"),
    ] | None = None
    timeout_seconds: float = Field(default=60.0, gt=0)
    max_retries: int = Field(default=2, ge=0)
    backoff_seconds: float = Field(default=0.25, ge=0)

    @field_validator("base_url")
    @classmethod
    def require_http_url(cls, value: str | None) -> str | None:
        if value is not None and not value.startswith(("http://", "https://")):
            raise ValueError("base_url deve usar http:// ou https://")
        return value


class ProviderRegistry:
    """Fábrica imutável dos providers declarados na configuração efetiva."""

    _legacy_registry: ClassVar[dict[str, Callable[[], BaseLLMProvider]]] = {
        "openai": OpenAIAdapter,
        "anthropic": AnthropicAdapter,
        "local": LocalAdapter,
    }

    def __init__(
        self,
        providers: Mapping[str, ProviderConfiguration],
        *,
        trust_boundary: TrustEvaluationResult | None = None,
    ) -> None:
        if not providers:
            raise ValueError("ao menos um provider deve ser configurado")
        copied: dict[str, ProviderConfiguration] = {}
        for provider_id, spec in providers.items():
            if provider_id != spec.adapter:
                raise ValueError(
                    f"provider id {provider_id!r} deve coincidir com adapter {spec.adapter!r}"
                )
            if provider_id in copied:
                raise ValueError(f"provider duplicado: {provider_id}")
            copied[provider_id] = spec
        self._providers = MappingProxyType(copied)
        if trust_boundary is not None and not isinstance(trust_boundary, TrustEvaluationResult):
            raise TypeError("trust_boundary must be a TrustEvaluationResult or None")
        self._trust_boundary = trust_boundary

    @classmethod
    def from_mapping(
        cls,
        providers: Mapping[str, object],
        *,
        trust_boundary: TrustEvaluationResult | None = None,
    ) -> ProviderRegistry:
        parsed: dict[str, ProviderConfiguration] = {}
        for provider_id, raw_spec in providers.items():
            if not isinstance(provider_id, str) or not provider_id.strip():
                raise ValueError("provider id deve ser string não vazia")
            parsed[provider_id] = ProviderConfiguration.model_validate(raw_spec)
        return cls(parsed, trust_boundary=trust_boundary)

    @property
    def provider_ids(self) -> tuple[str, ...]:
        return tuple(self._providers)

    def is_configured(self, provider_id: str) -> bool:
        return provider_id in self._providers

    def create_provider(self, provider_id: str) -> BaseLLMProvider:
        try:
            spec = self._providers[provider_id]
        except KeyError as exc:
            raise ValueError(f"Provedor não configurado: {provider_id}") from exc

        api_key = None
        if spec.api_key_env is not None:
            if self._trust_boundary is None:
                raise PermissionError(
                    "provider credential requires an explicit trust boundary"
                )
            api_key = SecretManager.get_secret(
                spec.api_key_env,
                boundary=self._trust_boundary,
                consumer=f"provider:{provider_id}",
            )
        if spec.adapter == "openai":
            return OpenAIAdapter(
                model_name=spec.model,
                api_key=api_key if api_key is not None else "",
                base_url=spec.base_url,
                timeout_seconds=spec.timeout_seconds,
                max_retries=spec.max_retries,
                backoff_seconds=spec.backoff_seconds,
            )
        if spec.adapter == "local":
            return LocalAdapter(
                model_name=spec.model,
                api_key=api_key if api_key is not None else "",
                base_url=spec.base_url,
                timeout_seconds=spec.timeout_seconds,
                max_retries=spec.max_retries,
                backoff_seconds=spec.backoff_seconds,
            )
        return AnthropicAdapter(model_name=spec.model)

    @classmethod
    def is_registered(cls, provider_id: str) -> bool:
        """Compatibilidade para routers legados construídos diretamente."""
        return provider_id in cls._legacy_registry

    @classmethod
    def get_provider(cls, provider_id: str) -> BaseLLMProvider:
        """Compatibilidade: factory default sem configuração efetiva."""
        if provider_id not in cls._legacy_registry:
            raise ValueError(f"Provedor não registrado: {provider_id}")
        return cls._legacy_registry[provider_id]()
