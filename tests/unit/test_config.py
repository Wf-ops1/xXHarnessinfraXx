"""Typed, redacted and deterministic effective configuration tests."""

from __future__ import annotations

import importlib.resources
from pathlib import Path

import pytest

import ai_engineering_harness.core.config as CONFIG_MODULE
from ai_engineering_harness.core.config import (
    ConfigDocumentError,
    ConfigResolver,
    ConfigValidationError,
)
from ai_engineering_harness.models.router import ModelEgressDeniedError


def test_config_resolver_applies_all_six_levels_in_documented_order(
    tmp_path: Path,
) -> None:
    harness_dir = tmp_path / ".harness"
    profiles_dir = harness_dir / "profiles"
    profiles_dir.mkdir(parents=True)
    (profiles_dir / "default.yaml").write_text(
        "context_sufficiency_threshold: 0.75\n",
        encoding="utf-8",
    )
    (harness_dir / "project.yaml").write_text(
        "language: python\nframework: pytest\ndeploy_token: raw-project-secret\n",
        encoding="utf-8",
    )
    custom_dir = harness_dir / "bmad" / "custom"
    custom_dir.mkdir(parents=True)
    (custom_dir / "a-team.toml").write_text(
        "context_sufficiency_threshold = 0.80\n",
        encoding="utf-8",
    )
    (custom_dir / "z-team.toml").write_text(
        "context_sufficiency_threshold = 0.81\n",
        encoding="utf-8",
    )
    (custom_dir / "developer.user.toml").write_text(
        "context_sufficiency_threshold = 0.85\n",
        encoding="utf-8",
    )

    config = ConfigResolver(project_root=tmp_path).resolve(
        cli_overrides={"context_sufficiency_threshold": 0.95}
    )

    assert config["context_sufficiency_threshold"] == 0.95
    assert config["profile_name"] == "default"
    assert config["project"] == {
        "language": "python",
        "framework": "pytest",
        "deploy_token": "[REDACTED_SECRET]",
    }


def test_config_resolver_reads_installed_package_defaults_with_importlib_resources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_files = CONFIG_MODULE.files
    calls: list[str] = []

    def traced_files(package: str):
        calls.append(package)
        return real_files(package)

    monkeypatch.setattr(CONFIG_MODULE, "files", traced_files)
    config = ConfigResolver(project_root=tmp_path).resolve()
    resource = importlib.resources.files("ai_engineering_harness.defaults").joinpath(
        "profiles",
        "default.yaml",
    )

    assert resource.is_file()
    assert calls == ["ai_engineering_harness.defaults"]
    assert config["models"]["routing"] == {
        "primary_provider": "local",
        "fallback_providers": [],
    }
    assert config["models"]["providers"]["local"]["model"] == "llama3"
    assert config["budget"]["max_tokens"] == 100_000
    assert config["budget"]["max_completion_tokens_per_call"] == 4_096
    assert config["budget"]["model_prices"] == {}
    assert config["budget"]["tool_prices_usd"] == {}
    assert config["verification"] == {"enforce_applicable_only": True}


def test_selected_project_profile_is_confined_and_persisted(tmp_path: Path) -> None:
    profile_dir = tmp_path / ".harness" / "profiles"
    profile_dir.mkdir(parents=True)
    (profile_dir / "secure.yaml").write_text(
        "approval_policy: two-person\ncontext_sufficiency_threshold: 0.9\n",
        encoding="utf-8",
    )

    config = ConfigResolver(tmp_path).resolve(profile_name="secure")

    assert config["profile_name"] == "secure"
    assert config["approval_policy"] == "two-person"
    assert config["context_sufficiency_threshold"] == 0.9


@pytest.mark.parametrize(
    "profile_name",
    ["", "../escape", "nested/profile", "C:profile", " profile"],
)
def test_profile_name_is_fail_closed(tmp_path: Path, profile_name: str) -> None:
    with pytest.raises(ConfigValidationError, match="profile_name"):
        ConfigResolver(tmp_path).resolve(profile_name=profile_name)


def test_missing_selected_profile_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigDocumentError, match="does not exist"):
        ConfigResolver(tmp_path).resolve(profile_name="missing")


@pytest.mark.parametrize(
    "override",
    [
        {"context_sufficiency_threshold": "not-a-number"},
        {"budget": {"max_tokens": True}},
        {"budget": {"max_cost_usd": 1.5}},
        {"budget": {"max_cost_usd": "01.50"}},
        {"verification": {"enforce_applicable_only": "yes"}},
        {"unknown_root_key": "unsupported"},
    ],
)
def test_complete_effective_configuration_is_pydantic_validated(
    tmp_path: Path,
    override: dict[str, object],
) -> None:
    with pytest.raises(ConfigValidationError, match="effective configuration"):
        ConfigResolver(tmp_path).resolve(cli_overrides=override)


def test_malformed_yaml_and_toml_fail_closed(tmp_path: Path) -> None:
    harness_dir = tmp_path / ".harness"
    profiles_dir = harness_dir / "profiles"
    profiles_dir.mkdir(parents=True)
    (profiles_dir / "default.yaml").write_text("[broken", encoding="utf-8")
    resolver = ConfigResolver(tmp_path)

    with pytest.raises(ConfigDocumentError, match="valid YAML"):
        resolver.resolve()

    (profiles_dir / "default.yaml").write_text("{}\n", encoding="utf-8")
    custom_dir = harness_dir / "bmad" / "custom"
    custom_dir.mkdir(parents=True)
    (custom_dir / "team.toml").write_text("broken = [", encoding="utf-8")
    with pytest.raises(ConfigDocumentError, match="valid TOML"):
        resolver.resolve()


def test_redacted_projection_is_required_for_persisted_configuration(
    tmp_path: Path,
) -> None:
    resolver = ConfigResolver(tmp_path)
    effective = resolver.resolve(
        cli_overrides={"project": {"service_password": "raw-password"}}
    )
    assert effective["project"]["service_password"] == "[REDACTED_SECRET]"
    assert resolver.validate_persisted(effective) == effective

    tampered = dict(effective)
    tampered["project"] = {"service_password": "raw-password"}
    with pytest.raises(ConfigValidationError, match="redacted projection"):
        resolver.validate_persisted(tampered)


def test_api_key_environment_reference_is_not_treated_as_a_secret(
    tmp_path: Path,
) -> None:
    config = ConfigResolver(tmp_path).resolve()
    assert config["models"]["providers"]["openai"]["api_key_env"] == "OPENAI_API_KEY"


def test_config_resolver_rejects_model_route_outside_egress(tmp_path: Path) -> None:
    with pytest.raises(ModelEgressDeniedError):
        ConfigResolver(project_root=tmp_path).resolve(
            cli_overrides={"data_egress": {"allowed_providers": ["openai"]}}
        )
