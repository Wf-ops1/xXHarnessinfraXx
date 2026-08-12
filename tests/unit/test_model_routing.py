"""Focused F3.2 tests for config-driven routing, fallback and budget."""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from ai_engineering_harness.core.config import ConfigResolver, ConfigValidationError
from ai_engineering_harness.governance import BudgetExceededError, BudgetTracker
from ai_engineering_harness.models import (
    CancellationToken,
    LLMResponse,
    ModelEgressDeniedError,
    ModelResponseCancelledError,
    ModelRouter,
    ModelRoutingConfigurationError,
    ModelRoutingIntegrityError,
    ProviderAuthError,
    ProviderCancelledError,
    ProviderConfiguration,
    ProviderError,
    ProviderInvalidRequestError,
    ProviderNotImplementedError,
    ProviderRegistry,
    ProviderResponseError,
    ProviderTimeoutError,
)


class _StaticProvider:
    def __init__(self, provider_id: str, outcomes: list[LLMResponse | Exception]) -> None:
        self.provider_id = provider_id
        self.outcomes = outcomes
        self.prompts: list[str] = []
        self.schemas: list[dict[str, object]] = []

    def complete(self, prompt: str, **_: object) -> LLMResponse:
        self.prompts.append(prompt)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def structured_output(
        self,
        prompt: str,
        response_schema: dict[str, object],
        **_: object,
    ) -> LLMResponse:
        self.schemas.append(response_schema)
        return self.complete(prompt)


class _StaticRegistry:
    def __init__(self, providers: Mapping[str, _StaticProvider]) -> None:
        self.providers = dict(providers)
        self.created: list[str] = []

    def is_configured(self, provider_id: str) -> bool:
        return provider_id in self.providers

    def create_provider(self, provider_id: str) -> _StaticProvider:
        self.created.append(provider_id)
        return self.providers[provider_id]


def _response(
    provider: str,
    *,
    model: str | None = None,
    total_tokens: int = 5,
    structured_output: dict[str, object] | None = None,
) -> LLMResponse:
    return LLMResponse(
        content="ok",
        provider=provider,
        model_name=model or f"{provider}-server-model",
        prompt_tokens=3,
        completion_tokens=2,
        total_tokens=total_tokens,
        request_id=f"req-{provider}",
        response_id=f"resp-{provider}",
        structured_output=structured_output,
    )


def _router(
    registry: _StaticRegistry,
    *,
    allowed: tuple[str, ...] = ("openai", "local"),
    budget: BudgetTracker | None = None,
) -> ModelRouter:
    return ModelRouter(
        allowed_providers=allowed,
        provider_registry=registry,  # type: ignore[arg-type]
        budget_tracker=budget,
        default_primary_provider="openai",
        default_fallback_providers=(
            ("local",) if "local" in registry.providers and "local" in allowed else ()
        ),
    )


def test_effective_config_builds_immutable_registry_and_default_route(tmp_path) -> None:
    effective = ConfigResolver(project_root=tmp_path).resolve()
    router = ModelRouter.from_effective_config(effective)

    assert router.validate_route() == ("local",)
    assert router.provider_registry is not None
    assert router.provider_registry.provider_ids == ("openai", "anthropic", "local")
    assert router.provider_registry.create_provider("local").model_name == "llama3"


def test_registry_detaches_provider_mapping() -> None:
    providers = {
        "local": ProviderConfiguration(
            adapter="local",
            model="configured-model",
            base_url="http://127.0.0.1:9999/v1",
        )
    }
    registry = ProviderRegistry(providers)
    providers.clear()

    assert registry.provider_ids == ("local",)
    assert registry.create_provider("local").model_name == "configured-model"


def test_transient_failure_falls_back_once_and_preserves_real_identity() -> None:
    primary = _StaticProvider(
        "openai",
        [ProviderTimeoutError("timeout", provider_id="openai")],
    )
    fallback = _StaticProvider("local", [_response("local", model="actual-local")])
    registry = _StaticRegistry({"openai": primary, "local": fallback})

    response = _router(registry).complete_with_fallback("sentinel")

    assert registry.created == ["openai", "local"]
    assert primary.prompts == ["sentinel"]
    assert fallback.prompts == ["sentinel"]
    assert (response.provider, response.model_name) == ("local", "actual-local")


def test_structured_output_uses_same_transient_fallback_identity_and_budget() -> None:
    schema = {
        "type": "object",
        "properties": {"status": {"type": "string"}},
        "required": ["status"],
        "additionalProperties": False,
    }
    primary = _StaticProvider(
        "openai",
        [ProviderTimeoutError("timeout", provider_id="openai")],
    )
    fallback = _StaticProvider(
        "local",
        [_response("local", structured_output={"status": "ready"})],
    )
    registry = _StaticRegistry({"openai": primary, "local": fallback})
    router = _router(registry)

    response = router.structured_output_with_fallback("plan", schema)

    assert response.structured_output == {"status": "ready"}
    assert registry.created == ["openai", "local"]
    assert primary.schemas == [schema]
    assert fallback.schemas == [schema]
    assert router.budget_tracker.consumed_tokens == 5


def test_structured_output_validates_egress_before_provider_creation() -> None:
    provider = _StaticProvider("openai", [_response("openai")])
    registry = _StaticRegistry({"openai": provider})

    with pytest.raises(ModelEgressDeniedError):
        _router(registry, allowed=("openai",)).structured_output_with_fallback(
            "must-not-leave",
            {"type": "object"},
            fallback_provider_ids=("local",),
        )

    assert registry.created == []
    assert provider.prompts == []


def test_structured_output_provider_identity_mismatch_fails_closed() -> None:
    provider = _StaticProvider(
        "openai",
        [_response("local", structured_output={"status": "ready"})],
    )
    registry = _StaticRegistry({"openai": provider})

    with pytest.raises(ModelRoutingIntegrityError):
        _router(registry, allowed=("openai",)).structured_output_with_fallback(
            "plan",
            {"type": "object"},
            fallback_provider_ids=(),
        )

    assert provider.prompts == ["plan"]


def test_structured_output_cancellation_after_response_prevents_charge() -> None:
    token = CancellationToken()

    class _CancellingStructuredProvider:
        def structured_output(self, prompt: str, schema: object, **_: object) -> LLMResponse:
            del prompt, schema
            token.cancel()
            return _response("openai", structured_output={"status": "ready"})

    registry = _StaticRegistry(  # type: ignore[arg-type]
        {"openai": _CancellingStructuredProvider()}
    )
    router = _router(registry, allowed=("openai",))

    with pytest.raises(ModelResponseCancelledError):
        router.structured_output_with_fallback(
            "plan",
            {"type": "object"},
            fallback_provider_ids=(),
            cancellation_token=token,
        )

    assert router.budget_tracker.consumed_tokens == 0


@pytest.mark.parametrize(
    "error_type",
    [
        ProviderAuthError,
        ProviderInvalidRequestError,
        ProviderResponseError,
        ProviderCancelledError,
        ProviderNotImplementedError,
    ],
)
def test_auth_invalid_response_cancel_and_not_implemented_never_fall_back(
    error_type: type[ProviderError],
) -> None:
    primary = _StaticProvider(
        "openai",
        [error_type("permanent", provider_id="openai")],
    )
    fallback = _StaticProvider("local", [_response("local")])
    registry = _StaticRegistry({"openai": primary, "local": fallback})

    with pytest.raises(error_type):
        _router(registry).complete_with_fallback("sentinel")

    assert registry.created == ["openai"]
    assert fallback.prompts == []


def test_entire_route_is_validated_before_provider_creation() -> None:
    primary = _StaticProvider("openai", [_response("openai")])
    registry = _StaticRegistry({"openai": primary})

    with pytest.raises(ModelRoutingConfigurationError, match="não registrado"):
        _router(registry).complete_with_fallback(
            "must-not-leave",
            fallback_provider_ids=("local",),
        )

    assert registry.created == []
    assert primary.prompts == []


def test_egress_denial_happens_before_provider_creation() -> None:
    local = _StaticProvider("local", [_response("local")])
    registry = _StaticRegistry({"local": local})

    with pytest.raises(ModelEgressDeniedError):
        ModelRouter(
            allowed_providers=("openai",),
            provider_registry=registry,  # type: ignore[arg-type]
            default_primary_provider="local",
        )

    assert registry.created == []
    assert local.prompts == []


def test_budget_records_real_usage_and_blocks_next_transport() -> None:
    provider = _StaticProvider("openai", [_response("openai"), _response("openai")])
    registry = _StaticRegistry({"openai": provider})
    budget = BudgetTracker(max_tokens=5)
    router = _router(registry, allowed=("openai",), budget=budget)

    router.complete_with_fallback("first", fallback_provider_ids=())
    with pytest.raises(BudgetExceededError):
        router.complete_with_fallback("second", fallback_provider_ids=())

    assert budget.consumed_tokens == 5
    assert provider.prompts == ["first"]


def test_provider_identity_mismatch_fails_closed() -> None:
    provider = _StaticProvider("openai", [_response("local")])
    registry = _StaticRegistry({"openai": provider})

    with pytest.raises(ModelRoutingIntegrityError) as captured:
        _router(registry, allowed=("openai",)).complete_with_fallback(
            "sentinel",
            fallback_provider_ids=(),
        )

    assert captured.value.response.response_id == "resp-local"


def test_cancel_after_transient_error_blocks_fallback_candidate() -> None:
    token = CancellationToken()

    class _CancellingProvider:
        def complete(self, prompt: str, **_: object) -> LLMResponse:
            token.cancel()
            raise ProviderTimeoutError("timeout", provider_id="openai")

    fallback = _StaticProvider("local", [_response("local")])
    registry = _StaticRegistry(  # type: ignore[arg-type]
        {"openai": _CancellingProvider(), "local": fallback}
    )
    router = _router(registry)

    with pytest.raises(ProviderCancelledError):
        router.complete_with_fallback("cancel", cancellation_token=token)

    assert registry.created == ["openai"]
    assert fallback.prompts == []
    assert router.budget_tracker.consumed_tokens == 0


def test_cancel_after_response_blocks_budget_and_return() -> None:
    token = CancellationToken()

    class _CancellingResponseProvider:
        def complete(self, prompt: str, **_: object) -> LLMResponse:
            token.cancel()
            return _response("openai")

    registry = _StaticRegistry(  # type: ignore[arg-type]
        {"openai": _CancellingResponseProvider()}
    )
    router = _router(registry, allowed=("openai",))

    with pytest.raises(ModelResponseCancelledError) as captured:
        router.complete_with_fallback(
            "cancel",
            fallback_provider_ids=(),
            cancellation_token=token,
        )

    assert registry.created == ["openai"]
    assert router.budget_tracker.consumed_tokens == 0
    assert captured.value.response.response_id == "resp-openai"


@pytest.mark.parametrize(
    "override",
    [
        {"models": {"routing": {"primary_provider": "missing"}}},
        {"data_egress": {"allowed_providers": ["local", "local"]}},
        {"budget": {"max_tokens": 0}},
    ],
)
def test_invalid_effective_route_configuration_fails_resolution(tmp_path, override) -> None:
    with pytest.raises(
        (
            ConfigValidationError,
            ModelRoutingConfigurationError,
            ModelEgressDeniedError,
        )
    ):
        ConfigResolver(project_root=tmp_path).resolve(cli_overrides=override)
