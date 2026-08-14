"""F5.5 sentinels for scoped injection, rotation, and public redaction."""

from __future__ import annotations

import json
import os
from pathlib import Path

import httpx
import pytest

from ai_engineering_harness.models.adapters.local import LocalAdapter
from ai_engineering_harness.models.adapters.openai import OpenAIAdapter
from ai_engineering_harness.models.provider import ProviderAuthError
from ai_engineering_harness.models.registry import ProviderConfiguration, ProviderRegistry
from ai_engineering_harness.security import (
    PathGuard,
    RedactionContext,
    Redactor,
    SecretGrant,
    SecretManager,
    TrustAuthorization,
    TrustBoundaryEvaluator,
    TrustCapabilityDeniedError,
)
from ai_engineering_harness.tools.adapters.serena import (
    SerenaAdapter,
    SerenaConfigurationError,
    SerenaMcpConfiguration,
    SerenaTransport,
)

_SECRET = "opaqueSecretValue987654"


def _boundary(root: Path, *grants: tuple[str, str]):
    return TrustBoundaryEvaluator(
        root,
        authorization=TrustAuthorization(
            repository_root=str(root.resolve()),
            secret_grants=tuple(
                SecretGrant(name=name, consumers=(consumer,))
                for name, consumer in grants
            ),
        ),
    ).evaluate()


def _responses_payload(content: str = "safe") -> dict[str, object]:
    return {
        "id": "resp-f5-5",
        "model": "configured-model",
        "status": "completed",
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": content}],
            }
        ],
        "usage": {
            "input_tokens": 1,
            "output_tokens": 1,
            "total_tokens": 2,
        },
    }


def test_redaction_context_is_detached_immutable_and_repr_safe() -> None:
    source = {"OPENAI_API_KEY": _SECRET}
    context = RedactionContext(source)
    source["OPENAI_API_KEY"] = "rotated-value-that-must-not-replace-the-snapshot"

    assert context.secret_names == ("OPENAI_API_KEY",)
    assert _SECRET not in repr(context)
    assert "rotated-value" not in context.redact_text(f"value={_SECRET}")
    assert _SECRET not in context.redact_text(f"value={_SECRET}")
    assert not hasattr(context, "__dict__")
    with pytest.raises(TypeError):
        json.dumps(context)


def test_bulk_secret_resolution_returns_only_a_repr_safe_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", _SECRET)
    boundary = _boundary(tmp_path, ("OPENAI_API_KEY", "provider:openai"))

    context = SecretManager.load_all_known_secrets(
        boundary=boundary,
        consumer="provider:openai",
    )

    assert isinstance(context, RedactionContext)
    assert context.secret_names == ("OPENAI_API_KEY",)
    assert _SECRET not in repr(context)
    assert _SECRET not in context.redact_text(_SECRET)


def test_dynamic_exact_multiline_and_line_wrapped_values_are_redacted() -> None:
    context = RedactionContext({"DYNAMIC_TOKEN": _SECRET})
    wrapped = "opaque\nSecret\r\nValue\t987654"
    text = (
        f"exact={_SECRET}\nwrapped={wrapped}\n"
        "Authorization: Bearer visible-auth-value\n"
        "Cookie: session=visible-cookie\npassword=visible-password"
    )

    redacted = context.redact_text(text)

    assert _SECRET not in redacted
    assert "opaque" not in redacted
    assert "visible-auth-value" not in redacted
    assert "visible-cookie" not in redacted
    assert "visible-password" not in redacted
    assert redacted.count("[REDACTED_DYNAMIC_TOKEN]") == 2


def test_recursive_json_redaction_stays_valid_and_preserves_public_shape() -> None:
    context = RedactionContext({"SERENA_MCP_TOKEN": _SECRET})
    projected = Redactor.redact_json(
        {
            "Authorization": f"Bearer {_SECRET}",
            "nested": {
                "apiKey": _SECRET,
                "message": "opaqueSecret\nValue987654",
            },
            "items": ["safe", {"cookie": f"session={_SECRET}"}],
        },
        context=context,
    )

    encoded = json.dumps(projected, sort_keys=True)
    assert json.loads(encoded) == projected
    assert _SECRET not in encoded
    assert "opaqueSecret" not in encoded
    assert projected["Authorization"] == "[REDACTED_SECRET]"  # type: ignore[index]
    assert projected["nested"]["apiKey"] == "[REDACTED_SECRET]"  # type: ignore[index]
    assert projected["items"][0] == "safe"  # type: ignore[index]


def test_legacy_provider_adapters_never_read_credential_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", _SECRET)
    monkeypatch.setenv("HARNESS_LOCAL_MODEL_API_KEY", _SECRET)

    openai = OpenAIAdapter(api_key=None)
    local = LocalAdapter(api_key=None)

    assert openai._api_key is None
    assert local._api_key is None
    assert _SECRET not in repr(openai)
    assert _SECRET not in repr(local)


def test_provider_injects_secret_only_into_header_and_redacts_response() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json=_responses_payload("opaqueSecret\nValue987654"),
            headers={"x-request-id": _SECRET},
            request=request,
        )

    provider = OpenAIAdapter(
        model_name="configured-model",
        api_key=_SECRET,
        redaction_context=RedactionContext({"OPENAI_API_KEY": _SECRET}),
        transport=httpx.MockTransport(handler),
    )
    response = provider.complete("prompt-without-credential")

    assert len(requests) == 1
    assert requests[0].headers["authorization"] == f"Bearer {_SECRET}"
    assert _SECRET.encode() not in requests[0].content
    assert b"OPENAI_API_KEY" not in requests[0].content
    assert _SECRET not in response.content
    assert "opaqueSecret" not in response.content
    assert "REDACTED_OPENAI_API_KEY" in response.content
    assert response.request_id == "[REDACTED_OPENAI_API_KEY]"


def test_provider_always_tracks_its_direct_key_when_context_is_incomplete() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_responses_payload("opaqueSecret\nValue987654"),
            request=request,
        )

    provider = OpenAIAdapter(
        model_name="configured-model",
        api_key=_SECRET,
        redaction_context=RedactionContext({"UNRELATED_SECRET": "unrelated-secret-value"}),
        transport=httpx.MockTransport(handler),
    )

    response = provider.complete("prompt-without-credential")

    assert _SECRET not in response.content
    assert "opaqueSecret" not in response.content
    assert "REDACTED_PROVIDER_API_KEY" in response.content


def test_missing_legacy_openai_key_fails_before_transport_even_when_env_is_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=_responses_payload(), request=request)

    monkeypatch.setenv("OPENAI_API_KEY", _SECRET)
    provider = OpenAIAdapter(api_key=None, transport=httpx.MockTransport(handler))

    with pytest.raises(ProviderAuthError, match="credencial"):
        provider.complete("must-fail-closed")
    assert calls == 0


def test_provider_rotation_occurs_only_on_next_composition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boundary = _boundary(tmp_path, ("OPENAI_API_KEY", "provider:openai"))
    registry = ProviderRegistry(
        {
            "openai": ProviderConfiguration(
                adapter="openai",
                model="configured-model",
                api_key_env="OPENAI_API_KEY",
            )
        },
        trust_boundary=boundary,
    )
    monkeypatch.setenv("OPENAI_API_KEY", "first-rotation-value-12345")
    first = registry.create_provider("openai")
    monkeypatch.setenv("OPENAI_API_KEY", "second-rotation-value-67890")
    second = registry.create_provider("openai")

    assert first._api_key == "first-rotation-value-12345"
    assert second._api_key == "second-rotation-value-67890"
    assert first._api_key != second._api_key
    assert "first-rotation-value" not in repr(first._redaction_context)
    assert "second-rotation-value" not in repr(second._redaction_context)


def test_serena_rejects_clear_sensitive_surfaces_and_repr_hides_mappings() -> None:
    with pytest.raises(SerenaConfigurationError, match="secret_headers"):
        SerenaMcpConfiguration(
            transport=SerenaTransport.STREAMABLE_HTTP,
            endpoint="https://example.invalid/mcp",
            headers={"Authorization": f"Bearer {_SECRET}"},
        )
    with pytest.raises(SerenaConfigurationError, match="secret_environment"):
        SerenaMcpConfiguration(
            transport=SerenaTransport.STDIO,
            command=os.path.abspath(os.sys.executable),
            environment={"SERENA_MCP_TOKEN": _SECRET},
        )
    with pytest.raises(SerenaConfigurationError, match="secret_headers"):
        SerenaMcpConfiguration(
            transport=SerenaTransport.STREAMABLE_HTTP,
            endpoint="https://example.invalid/mcp",
            headers={"X-Auth-Token": _SECRET},
        )
    with pytest.raises(SerenaConfigurationError, match="must not overlap"):
        SerenaMcpConfiguration(
            transport=SerenaTransport.STDIO,
            command=os.path.abspath(os.sys.executable),
            environment={"PUBLIC_SETTING": "public"},
            secret_environment={"PUBLIC_SETTING": "SERENA_MCP_TOKEN"},
        )

    configuration = SerenaMcpConfiguration(
        transport=SerenaTransport.STREAMABLE_HTTP,
        endpoint="https://example.invalid/mcp",
        headers={"X-Public-Metadata": "public-value"},
        secret_headers={"Authorization": "SERENA_MCP_TOKEN"},
    )
    assert _SECRET not in repr(configuration)
    assert "public-value" not in repr(configuration)


def test_serena_secret_resolution_requires_exact_consumer_before_environment_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configuration = SerenaMcpConfiguration(
        transport=SerenaTransport.STREAMABLE_HTTP,
        endpoint="https://example.invalid/mcp",
        secret_headers={"Authorization": "SERENA_MCP_TOKEN"},
    )
    boundary = _boundary(tmp_path, ("SERENA_MCP_TOKEN", "provider:openai"))

    def fail_if_read(_key: str, _default: str | None = None) -> str | None:
        raise AssertionError("environment read preceded exact Serena authorization")

    monkeypatch.setattr(os.environ, "get", fail_if_read)
    with pytest.raises(TrustCapabilityDeniedError, match="consumer"):
        SerenaAdapter(
            path_guard=PathGuard(tmp_path),
            configuration=configuration,
            trust_boundary=boundary,
        )


def test_serena_secret_rotation_is_scoped_to_adapter_composition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configuration = SerenaMcpConfiguration(
        transport=SerenaTransport.STREAMABLE_HTTP,
        endpoint="https://example.invalid/mcp",
        secret_headers={"Authorization": "SERENA_MCP_TOKEN"},
    )
    boundary = _boundary(tmp_path, ("SERENA_MCP_TOKEN", "tool:serena"))
    monkeypatch.setenv("SERENA_MCP_TOKEN", "first-serena-rotation-12345")
    first = SerenaAdapter(
        path_guard=PathGuard(tmp_path),
        configuration=configuration,
        trust_boundary=boundary,
    )
    monkeypatch.setenv("SERENA_MCP_TOKEN", "second-serena-rotation-67890")
    second = SerenaAdapter(
        path_guard=PathGuard(tmp_path),
        configuration=configuration,
        trust_boundary=boundary,
    )

    assert first._secret_headers["Authorization"] == "Bearer first-serena-rotation-12345"
    assert second._secret_headers["Authorization"] == "Bearer second-serena-rotation-67890"
    assert "first-serena-rotation" not in repr(first.redaction_context)
    assert "second-serena-rotation" not in repr(second.redaction_context)


def test_serena_secret_boundary_must_match_the_path_guard_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorized_root = tmp_path / "authorized"
    other_root = tmp_path / "other"
    authorized_root.mkdir()
    other_root.mkdir()
    configuration = SerenaMcpConfiguration(
        transport=SerenaTransport.STREAMABLE_HTTP,
        endpoint="https://example.invalid/mcp",
        secret_headers={"Authorization": "SERENA_MCP_TOKEN"},
    )
    boundary = _boundary(other_root, ("SERENA_MCP_TOKEN", "tool:serena"))

    def fail_if_read(_key: str, _default: str | None = None) -> str | None:
        raise AssertionError("environment read preceded exact Serena root authorization")

    monkeypatch.setattr(os.environ, "get", fail_if_read)
    with pytest.raises(SerenaConfigurationError, match="PathGuard root"):
        SerenaAdapter(
            path_guard=PathGuard(authorized_root),
            configuration=configuration,
            trust_boundary=boundary,
        )
