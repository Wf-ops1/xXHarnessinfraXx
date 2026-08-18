"""Unit coverage for redaction, secrets, and the unified F5.3 trust boundary."""

import os
from pathlib import Path

import pytest

from ai_engineering_harness.security import (
    Redactor,
    SecretGrant,
    SecretManager,
    TrustAuthorization,
    TrustBoundaryConfigurationError,
    TrustBoundaryEvaluator,
    TrustCapabilityDeniedError,
    TrustEvaluationResult,
)


def _authorization(root: Path) -> TrustAuthorization:
    return TrustAuthorization(
        repository_root=str(root.resolve()),
        python_contracts=("python:package.contracts:AllowedContract",),
        executable_aliases=("python",),
        secret_grants=(
            SecretGrant(
                name="OPENAI_API_KEY",
                consumers=("provider:openai",),
            ),
        ),
        hook_ids=("rollback-compensation",),
        promotion_allowed=True,
    )


def test_secret_manager_reads_only_an_explicit_name_consumer_grant(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test12345678901234567890123456789012")
    boundary = TrustBoundaryEvaluator(
        tmp_path,
        authorization=_authorization(tmp_path),
    ).evaluate()

    value = SecretManager.get_secret(
        "OPENAI_API_KEY",
        boundary=boundary,
        consumer="provider:openai",
    )

    assert value == "sk-test12345678901234567890123456789012"


def test_secret_denial_happens_before_environment_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boundary = TrustBoundaryEvaluator(tmp_path).evaluate()

    def fail_if_read(_key: str, _default: str | None = None) -> str | None:
        raise AssertionError("environment was read before authorization")

    monkeypatch.setattr(os.environ, "get", fail_if_read)
    with pytest.raises(TrustCapabilityDeniedError, match="secret name"):
        SecretManager.get_secret(
            "OPENAI_API_KEY",
            boundary=boundary,
            consumer="provider:openai",
        )


def test_redactor_sanitizes_openai_key() -> None:
    text = "Erro na chamada com a chave sk-abc12345678901234567890123456789012 no payload."
    redacted = Redactor.redact_text(text)
    assert "sk-abc" not in redacted
    assert "[REDACTED_SECRET]" in redacted


def test_redactor_dynamic_secrets() -> None:
    secrets = {"MY_TOKEN": "secret_token_val_123"}
    text = "Conectando usando secret_token_val_123 no endpoint."
    redacted = Redactor.redact_text(text, dynamic_secrets=secrets)
    assert "secret_token_val_123" not in redacted
    assert "[REDACTED_MY_TOKEN]" in redacted


def test_trust_boundary_default_restricted(tmp_path: Path) -> None:
    result = TrustBoundaryEvaluator(project_root=tmp_path).evaluate()

    assert result.is_trusted is False
    assert result.mode == "restricted"
    assert result.allow_python_contracts is False
    assert result.executable_aliases == ()
    assert result.secret_grants == ()
    assert result.hook_ids == ()
    assert result.promotion_allowed is False


def test_trusted_marker_alone_grants_no_effect_capability(tmp_path: Path) -> None:
    harness_dir = tmp_path / ".harness"
    harness_dir.mkdir()
    (harness_dir / "trusted_repository").touch()

    result = TrustBoundaryEvaluator(project_root=tmp_path).evaluate()

    assert result.is_trusted is True
    assert result.allow_python_contracts is False
    assert result.allow_unprompted_commands is False
    assert result.secret_grants == ()
    assert result.hook_ids == ()
    assert result.promotion_allowed is False


def test_external_authorization_is_intersected_with_trusted_marker(tmp_path: Path) -> None:
    harness_dir = tmp_path / ".harness"
    harness_dir.mkdir()
    (harness_dir / "trusted_repository").touch()

    result = TrustBoundaryEvaluator(
        tmp_path,
        authorization=_authorization(tmp_path),
    ).evaluate()

    assert result.mode == "trusted"
    assert result.python_contracts == ("python:package.contracts:AllowedContract",)
    assert result.executable_aliases == ("python",)
    assert result.hook_ids == ("rollback-compensation",)


def test_forced_restricted_mode_drops_python_and_hook_capabilities(tmp_path: Path) -> None:
    harness_dir = tmp_path / ".harness"
    harness_dir.mkdir()
    (harness_dir / "trusted_repository").touch()

    result = TrustBoundaryEvaluator(
        tmp_path,
        authorization=_authorization(tmp_path),
    ).evaluate(force_untrusted=True)

    assert result.mode == "restricted"
    assert result.python_contracts == ()
    assert result.hook_ids == ()
    assert result.executable_aliases == ("python",)


def test_trust_evaluator_rejects_a_non_boolean_force_flag(tmp_path: Path) -> None:
    with pytest.raises(TrustBoundaryConfigurationError, match="explicit bool"):
        TrustBoundaryEvaluator(tmp_path).evaluate(force_untrusted=1)  # type: ignore[arg-type]


def test_boundary_snapshot_is_deterministic_and_tamper_evident(tmp_path: Path) -> None:
    evaluator = TrustBoundaryEvaluator(tmp_path, authorization=_authorization(tmp_path))
    first = evaluator.evaluate()
    second = evaluator.evaluate()

    assert first == second
    assert first.snapshot_json() == second.snapshot_json()
    assert TrustEvaluationResult.from_snapshot(first.snapshot()) == first

    tampered = first.snapshot()
    tampered["promotion_allowed"] = False
    with pytest.raises(TrustBoundaryConfigurationError, match="digest mismatch"):
        TrustEvaluationResult.from_snapshot(tampered)


def test_boundary_rejects_a_mismatched_root(tmp_path: Path) -> None:
    other = tmp_path / "other"
    other.mkdir()
    boundary = TrustBoundaryEvaluator(tmp_path).evaluate()

    with pytest.raises(TrustCapabilityDeniedError, match="root"):
        boundary.require_root(other)


def test_rollback_hook_requires_allowlist_trust_and_destructive_approval(
    tmp_path: Path,
) -> None:
    harness_dir = tmp_path / ".harness"
    harness_dir.mkdir()
    (harness_dir / "trusted_repository").touch()
    evaluator = TrustBoundaryEvaluator(tmp_path, authorization=_authorization(tmp_path))
    boundary = evaluator.evaluate()

    assert evaluator.validate_rollback_hook(
        boundary,
        hook_id="rollback-compensation",
        is_destructive=True,
        user_approved=False,
    ) is False
    assert evaluator.validate_rollback_hook(
        boundary,
        hook_id="rollback-compensation",
        is_destructive=False,
        user_approved=False,
    ) is True
    assert evaluator.validate_rollback_hook(
        boundary,
        hook_id="rollback-compensation",
        is_destructive=True,
        user_approved=True,
    ) is True
