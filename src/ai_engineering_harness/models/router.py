"""Roteamento de modelos por configuração efetiva, egress e budget."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, StringConstraints, field_validator

from ai_engineering_harness.governance.budget import BudgetExceededError, BudgetTracker
from ai_engineering_harness.models.provider import (
    BaseLLMProvider,
    CancellationToken,
    LLMResponse,
    ModelToolConversation,
    ProviderCancelledError,
    ProviderError,
)
from ai_engineering_harness.models.registry import ProviderConfiguration, ProviderRegistry
from ai_engineering_harness.security import TrustEvaluationResult

_NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ModelRoutingConfigurationError(ValueError):
    """A configuração efetiva de modelos não forma uma rota válida."""


class ModelEgressDeniedError(PermissionError):
    """Um candidato não está autorizado pela política de data egress."""


class ModelRoutingIntegrityError(RuntimeError):
    """O provider respondeu com identidade incompatível com a rota selecionada."""

    def __init__(self, message: str, *, response: LLMResponse) -> None:
        super().__init__(message)
        self.response = response


class ModelResponseCancelledError(ProviderCancelledError):
    """Cancellation observed after a response completed but before charging."""

    def __init__(self, response: LLMResponse, *, provider_id: str) -> None:
        super().__init__(
            "chamada do provider cancelada após a resposta",
            provider_id=provider_id,
        )
        self.response = response


class ModelResponseBudgetExceededError(BudgetExceededError):
    """Budget exceeded by a completed response whose metadata must survive."""

    def __init__(self, response: LLMResponse, cause: BudgetExceededError) -> None:
        super().__init__(
            max_tokens=cause.max_tokens,
            consumed_tokens=cause.consumed_tokens,
        )
        self.response = response


class ModelRouteConfiguration(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    primary_provider: _NonEmptyStr
    fallback_providers: tuple[_NonEmptyStr, ...] = ()

    @field_validator("fallback_providers", mode="before")
    @classmethod
    def freeze_fallbacks(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value


class ModelsConfiguration(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    providers: dict[str, ProviderConfiguration]
    routing: ModelRouteConfiguration


class ModelRouter:
    """Roteador fail-closed com egress pré-prompt, fallback transitório e budget."""

    def __init__(
        self,
        allowed_providers: list[str] | tuple[str, ...],
        *,
        provider_registry: ProviderRegistry | None = None,
        budget_tracker: BudgetTracker | None = None,
        default_primary_provider: str | None = None,
        default_fallback_providers: tuple[str, ...] = (),
    ) -> None:
        if not allowed_providers:
            raise ModelRoutingConfigurationError("allowed_providers não pode ser vazio")
        if len(set(allowed_providers)) != len(allowed_providers):
            raise ModelRoutingConfigurationError("allowed_providers contém duplicatas")
        self.allowed_providers = tuple(allowed_providers)
        self.provider_registry = provider_registry
        self.budget_tracker = budget_tracker or BudgetTracker()
        self.default_primary_provider = default_primary_provider or self.allowed_providers[0]
        self.default_fallback_providers = tuple(default_fallback_providers)
        self.validate_route()

    @classmethod
    def from_effective_config(
        cls,
        config: Mapping[str, object],
        *,
        trust_boundary: TrustEvaluationResult | None = None,
    ) -> ModelRouter:
        """Constrói o router exclusivamente da configuração já resolvida."""
        models_raw = config.get("models")
        if not isinstance(models_raw, dict):
            raise ModelRoutingConfigurationError("configuração efetiva não contém models")
        try:
            models = ModelsConfiguration.model_validate(models_raw)
        except (TypeError, ValueError) as exc:
            raise ModelRoutingConfigurationError(
                f"configuração efetiva de models inválida: {exc}"
            ) from exc

        data_egress = config.get("data_egress")
        if not isinstance(data_egress, dict):
            raise ModelRoutingConfigurationError("configuração efetiva não contém data_egress")
        allowed_raw = data_egress.get("allowed_providers")
        if not isinstance(allowed_raw, list) or not all(
            isinstance(item, str) and item for item in allowed_raw
        ):
            raise ModelRoutingConfigurationError("allowed_providers deve ser lista não vazia")

        budget_raw = config.get("budget", {})
        if not isinstance(budget_raw, dict):
            raise ModelRoutingConfigurationError("budget deve ser objeto")
        max_tokens = budget_raw.get("max_tokens", 100_000)
        if type(max_tokens) is not int or max_tokens <= 0:
            raise ModelRoutingConfigurationError("budget.max_tokens deve ser inteiro positivo")

        registry = ProviderRegistry(models.providers, trust_boundary=trust_boundary)
        return cls(
            allowed_providers=allowed_raw,
            provider_registry=registry,
            budget_tracker=BudgetTracker(max_tokens=max_tokens),
            default_primary_provider=models.routing.primary_provider,
            default_fallback_providers=models.routing.fallback_providers,
        )

    @classmethod
    def validate_effective_config(cls, config: Mapping[str, object]) -> None:
        cls.from_effective_config(config)

    def validate_route(
        self,
        primary_provider_id: str | None = None,
        fallback_provider_ids: list[str] | tuple[str, ...] | None = None,
    ) -> tuple[str, ...]:
        """Valida todos os candidatos antes de prompt, provider ou transporte."""
        primary = primary_provider_id or self.default_primary_provider
        fallbacks = (
            self.default_fallback_providers
            if fallback_provider_ids is None
            else tuple(fallback_provider_ids)
        )
        candidates = (primary, *fallbacks)
        if len(set(candidates)) != len(candidates):
            raise ModelRoutingConfigurationError("rota contém provider duplicado")
        for provider_id in candidates:
            self._validate_egress(provider_id)
            if not self._is_registered(provider_id):
                raise ModelRoutingConfigurationError(
                    f"provider não registrado/configurado: {provider_id}"
                )
        return candidates

    def complete_with_fallback(
        self,
        prompt: str,
        primary_provider_id: str | None = None,
        fallback_provider_ids: list[str] | tuple[str, ...] | None = None,
        *,
        cancellation_token: CancellationToken | None = None,
    ) -> LLMResponse:
        """Executa uma vez por candidato e só avança após falha transitória."""
        candidates = self.validate_route(primary_provider_id, fallback_provider_ids)
        last_transient_error: ProviderError | None = None
        for provider_id in candidates:
            self._raise_if_cancelled(cancellation_token, provider_id=provider_id)
            self.budget_tracker.ensure_available()
            provider = self._create_provider(provider_id)
            try:
                response = provider.complete(
                    prompt,
                    cancellation_token=cancellation_token,
                )
            except ProviderError as exc:
                self._raise_if_cancelled(cancellation_token, provider_id=provider_id)
                if not exc.retryable:
                    raise
                last_transient_error = exc
                continue

            self._raise_if_cancelled(
                cancellation_token,
                provider_id=provider_id,
                response=response,
            )
            if response.provider != provider_id:
                raise ModelRoutingIntegrityError(
                    "provider retornado não corresponde ao candidato selecionado",
                    response=response,
                )
            self._charge_response(response)
            return response

        assert last_transient_error is not None
        raise last_transient_error

    def structured_output_with_fallback(
        self,
        prompt: str,
        response_schema: dict[str, Any],
        primary_provider_id: str | None = None,
        fallback_provider_ids: list[str] | tuple[str, ...] | None = None,
        *,
        cancellation_token: CancellationToken | None = None,
    ) -> LLMResponse:
        """Request strict structured output under the canonical route invariants."""
        candidates = self.validate_route(primary_provider_id, fallback_provider_ids)
        last_transient_error: ProviderError | None = None
        for provider_id in candidates:
            self._raise_if_cancelled(cancellation_token, provider_id=provider_id)
            self.budget_tracker.ensure_available()
            provider = self._create_provider(provider_id)
            try:
                response = provider.structured_output(
                    prompt,
                    response_schema,
                    cancellation_token=cancellation_token,
                )
            except ProviderError as exc:
                self._raise_if_cancelled(cancellation_token, provider_id=provider_id)
                if not exc.retryable:
                    raise
                last_transient_error = exc
                continue

            self._raise_if_cancelled(
                cancellation_token,
                provider_id=provider_id,
                response=response,
            )
            if response.provider != provider_id:
                raise ModelRoutingIntegrityError(
                    "provider retornado não corresponde ao candidato selecionado",
                    response=response,
                )
            self._charge_response(response)
            return response

        assert last_transient_error is not None
        raise last_transient_error

    def call_tools_with_fallback(
        self,
        prompt: str,
        tools: list[dict[str, Any]],
        primary_provider_id: str | None = None,
        fallback_provider_ids: list[str] | tuple[str, ...] | None = None,
        *,
        cancellation_token: CancellationToken | None = None,
    ) -> LLMResponse:
        """Call provider tools with the same F3.2 route, budget and fallback rules."""
        candidates = self.validate_route(primary_provider_id, fallback_provider_ids)
        last_transient_error: ProviderError | None = None
        for provider_id in candidates:
            self._raise_if_cancelled(cancellation_token, provider_id=provider_id)
            self.budget_tracker.ensure_available()
            provider = self._create_provider(provider_id)
            try:
                response = provider.call_tools(
                    prompt,
                    tools,
                    cancellation_token=cancellation_token,
                )
            except ProviderError as exc:
                self._raise_if_cancelled(cancellation_token, provider_id=provider_id)
                if not exc.retryable:
                    raise
                last_transient_error = exc
                continue

            self._raise_if_cancelled(
                cancellation_token,
                provider_id=provider_id,
                response=response,
            )
            if response.provider != provider_id:
                raise ModelRoutingIntegrityError(
                    "provider retornado não corresponde ao candidato selecionado",
                    response=response,
                )
            self._charge_response(response)
            return response

        assert last_transient_error is not None
        raise last_transient_error

    def continue_tools_with_fallback(
        self,
        conversation: ModelToolConversation,
        tools: list[dict[str, Any]],
        primary_provider_id: str | None = None,
        fallback_provider_ids: list[str] | tuple[str, ...] | None = None,
        *,
        cancellation_token: CancellationToken | None = None,
    ) -> LLMResponse:
        """Continue a native typed tool conversation under the same route rules."""
        candidates = self.validate_route(primary_provider_id, fallback_provider_ids)
        last_transient_error: ProviderError | None = None
        for provider_id in candidates:
            self._raise_if_cancelled(cancellation_token, provider_id=provider_id)
            self.budget_tracker.ensure_available()
            provider = self._create_provider(provider_id)
            try:
                response = provider.continue_tools(
                    conversation,
                    tools,
                    cancellation_token=cancellation_token,
                )
            except ProviderError as exc:
                self._raise_if_cancelled(cancellation_token, provider_id=provider_id)
                if not exc.retryable:
                    raise
                last_transient_error = exc
                continue

            self._raise_if_cancelled(
                cancellation_token,
                provider_id=provider_id,
                response=response,
            )
            if response.provider != provider_id:
                raise ModelRoutingIntegrityError(
                    "provider retornado não corresponde ao candidato selecionado",
                    response=response,
                )
            self._charge_response(response)
            return response

        assert last_transient_error is not None
        raise last_transient_error

    def _charge_response(self, response: LLMResponse) -> None:
        try:
            self.budget_tracker.add_tokens(response.total_tokens)
        except BudgetExceededError as exc:
            raise ModelResponseBudgetExceededError(response, exc) from exc

    @staticmethod
    def _raise_if_cancelled(
        token: CancellationToken | None,
        *,
        provider_id: str,
        response: LLMResponse | None = None,
    ) -> None:
        if token is not None and token.is_cancelled:
            if response is not None:
                raise ModelResponseCancelledError(
                    response,
                    provider_id=provider_id,
                )
            raise ProviderCancelledError(
                "chamada do provider cancelada antes do próximo candidato",
                provider_id=provider_id,
            )

    def _validate_egress(self, provider_id: str) -> None:
        if provider_id not in self.allowed_providers:
            raise ModelEgressDeniedError(
                f"[SECURITY VIOLATION] Provedor '{provider_id}' não está autorizado "
                f"na política de data egress: {list(self.allowed_providers)}"
            )

    def _is_registered(self, provider_id: str) -> bool:
        if self.provider_registry is not None:
            return self.provider_registry.is_configured(provider_id)
        return ProviderRegistry.is_registered(provider_id)

    def _create_provider(self, provider_id: str) -> BaseLLMProvider:
        if self.provider_registry is not None:
            return self.provider_registry.create_provider(provider_id)
        return ProviderRegistry.get_provider(provider_id)
