"""Resolução tipada da configuração efetiva em seis níveis determinísticos.

Ordem de precedência, da menor para a maior:

1. defaults empacotados em ``ai_engineering_harness.defaults``;
2. perfil selecionado;
3. manifesto ``.harness/project.yaml``;
4. overrides do time ``.harness/bmad/custom/*.toml``;
5. overrides pessoais ``.harness/bmad/custom/*.user.toml``;
6. overrides explícitos do CLI.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Annotated, Any, Literal, cast

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StringConstraints,
    ValidationError,
    field_validator,
)

try:
    import tomllib
except ImportError:  # pragma: no cover - Python 3.11+ is required by the package
    import tomli as tomllib  # type: ignore[import-not-found,no-redef]

from ai_engineering_harness.models.router import ModelRouter, ModelsConfiguration

_PROFILE_NAME_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]*$"
_PROFILE_NAME_RE = re.compile(_PROFILE_NAME_PATTERN)
_REDACTED_SECRET = "[REDACTED_SECRET]"
_SENSITIVE_KEY_NAMES = frozenset(
    {
        "access_key",
        "api_key",
        "authorization",
        "credential",
        "password",
        "private_key",
        "secret",
        "token",
    }
)

_NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
_ProfileName = Annotated[str, StringConstraints(pattern=_PROFILE_NAME_PATTERN)]


class ConfigResolutionError(ValueError):
    """Base class for configuration that cannot be resolved safely."""


class ConfigDocumentError(ConfigResolutionError):
    """A package or project configuration document is missing or malformed."""


class ConfigValidationError(ConfigResolutionError):
    """The merged effective configuration violates its typed contract."""


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")


class DataEgressConfiguration(_StrictFrozenModel):
    """Providers authorized to receive model data."""

    allowed_providers: tuple[_NonEmptyStr, ...] = Field(min_length=1)

    @field_validator("allowed_providers", mode="before")
    @classmethod
    def freeze_allowed_providers(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @field_validator("allowed_providers")
    @classmethod
    def require_unique_providers(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("allowed_providers contains duplicates")
        return value


class BudgetConfiguration(_StrictFrozenModel):
    """Configuration consumed by the current model router budget boundary."""

    max_tokens: int = Field(gt=0)


class VerificationConfiguration(_StrictFrozenModel):
    """Runtime verification selection switches owned by effective configuration."""

    enforce_applicable_only: bool


class EffectiveConfiguration(_StrictFrozenModel):
    """Complete redaction-safe configuration required to start an execution."""

    version: Literal["1.0"]
    profile_name: _ProfileName
    context_sufficiency_threshold: float = Field(ge=0.0, le=1.0)
    approval_policy: _NonEmptyStr
    data_egress: DataEgressConfiguration
    models: ModelsConfiguration
    budget: BudgetConfiguration
    verification: VerificationConfiguration
    project: dict[str, JsonValue] = Field(default_factory=dict)

    def as_json_object(self) -> dict[str, Any]:
        """Return a detached JSON-compatible object with stable container types."""
        return cast(dict[str, Any], self.model_dump(mode="json"))


def deep_merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    """Merge detached mappings recursively without mutating either input."""
    merged = dict(base)
    for key, value in override.items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            merged[key] = deep_merge(current, value)
        else:
            merged[key] = value
    return merged


def redact_configuration(value: object) -> object:
    """Return a detached projection that never persists secret-bearing values."""
    if type(value) is dict:
        redacted: dict[str, object] = {}
        for raw_key, child in value.items():
            if type(raw_key) is not str:
                raise ConfigValidationError("configuration keys must be strings")
            redacted[raw_key] = (
                _REDACTED_SECRET
                if _is_sensitive_key(raw_key)
                else redact_configuration(child)
            )
        return redacted
    if type(value) is list:
        return [redact_configuration(item) for item in value]
    return value


def _is_sensitive_key(raw_key: str) -> bool:
    normalized = raw_key.casefold().replace("-", "_")
    if normalized.endswith("_env"):
        return False
    return normalized in _SENSITIVE_KEY_NAMES or any(
        normalized.endswith(f"_{name}") for name in _SENSITIVE_KEY_NAMES
    )


class ConfigResolver:
    """Load, validate and redact the only effective runtime configuration."""

    def __init__(self, project_root: Path | None = None) -> None:
        raw_root = Path.cwd() if project_root is None else Path(project_root)
        try:
            resolved_root = raw_root.resolve(strict=True)
        except OSError as exc:
            raise ConfigDocumentError("project_root must resolve to an existing directory") from exc
        if not resolved_root.is_dir():
            raise ConfigDocumentError("project_root must resolve to an existing directory")
        self.project_root = resolved_root

    def resolve(
        self,
        profile_name: str = "default",
        cli_overrides: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Resolve all layers and return only the typed redacted projection."""
        selected_profile = self._validate_profile_name(profile_name)
        config = self._read_package_yaml(
            files("ai_engineering_harness.defaults").joinpath(
                "profiles",
                "default.yaml",
            ),
            label="package default profile",
            required=True,
        )

        profile_found = selected_profile == "default"
        if selected_profile != "default":
            package_profile = files("ai_engineering_harness.defaults").joinpath(
                "profiles",
                f"{selected_profile}.yaml",
            )
            if package_profile.is_file():
                config = deep_merge(
                    config,
                    self._read_package_yaml(
                        package_profile,
                        label=f"package profile {selected_profile!r}",
                        required=True,
                    ),
                )
                profile_found = True

        project_profile_path = (
            self.project_root
            / ".harness"
            / "profiles"
            / f"{selected_profile}.yaml"
        )
        if project_profile_path.is_file():
            config = deep_merge(
                config,
                self._read_project_yaml(
                    project_profile_path,
                    label=f"project profile {selected_profile!r}",
                ),
            )
            profile_found = True
        if not profile_found:
            raise ConfigDocumentError(f"selected profile {selected_profile!r} does not exist")

        project_manifest = self.project_root / ".harness" / "project.yaml"
        if project_manifest.is_file():
            config = deep_merge(
                config,
                {
                    "project": self._read_project_yaml(
                        project_manifest,
                        label="project manifest",
                    )
                },
            )

        custom_dir = self.project_root / ".harness" / "bmad" / "custom"
        if custom_dir.is_dir():
            team_overrides = sorted(
                path
                for path in custom_dir.glob("*.toml")
                if not path.name.endswith(".user.toml")
            )
            for path in team_overrides:
                config = deep_merge(config, self._read_project_toml(path))
            for path in sorted(custom_dir.glob("*.user.toml")):
                config = deep_merge(config, self._read_project_toml(path))

        if cli_overrides is not None:
            if not isinstance(cli_overrides, Mapping):
                raise ConfigValidationError("CLI overrides must be a mapping")
            config = deep_merge(config, cli_overrides)

        # Profile selection itself is a CLI/runtime argument and has the highest priority.
        config["profile_name"] = selected_profile
        return self.validate_and_redact(config)

    @staticmethod
    def validate_and_redact(configuration: Mapping[str, Any]) -> dict[str, Any]:
        """Validate a complete configuration and return its redacted projection."""
        try:
            model = EffectiveConfiguration.model_validate(configuration)
        except (TypeError, ValueError, ValidationError) as exc:
            raise ConfigValidationError(f"effective configuration is invalid: {exc}") from exc

        effective = model.as_json_object()
        # Preserve the existing cross-field provider/egress fail-closed contract.
        ModelRouter.validate_effective_config(effective)
        redacted = redact_configuration(effective)
        if type(redacted) is not dict:  # pragma: no cover - model dump is always an object
            raise ConfigValidationError("redacted configuration must be an object")
        try:
            validated_redacted = EffectiveConfiguration.model_validate(redacted)
        except (TypeError, ValueError, ValidationError) as exc:
            raise ConfigValidationError(
                "redacted configuration violates the effective contract"
            ) from exc
        return validated_redacted.as_json_object()

    @classmethod
    def validate_persisted(cls, configuration: Mapping[str, Any]) -> dict[str, Any]:
        """Reject a bundle configuration that is invalid or was not already redacted."""
        redacted = cls.validate_and_redact(configuration)
        if redacted != dict(configuration):
            raise ConfigValidationError(
                "persisted configuration is not the canonical redacted projection"
            )
        return redacted

    @staticmethod
    def _validate_profile_name(profile_name: object) -> str:
        if type(profile_name) is not str or _PROFILE_NAME_RE.fullmatch(profile_name) is None:
            raise ConfigValidationError(
                "profile_name must match [A-Za-z0-9][A-Za-z0-9._-]*"
            )
        return profile_name

    def _read_project_yaml(self, path: Path, *, label: str) -> dict[str, Any]:
        resolved = self._confined_project_file(path, label=label)
        try:
            text = resolved.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise ConfigDocumentError(f"{label} cannot be read as UTF-8") from exc
        return self._parse_yaml(text, label=label)

    def _read_project_toml(self, path: Path) -> dict[str, Any]:
        label = f"configuration override {path.name!r}"
        resolved = self._confined_project_file(path, label=label)
        try:
            with resolved.open("rb") as stream:
                document = tomllib.load(stream)
        except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
            raise ConfigDocumentError(f"{label} is not valid TOML") from exc
        if type(document) is not dict:
            raise ConfigDocumentError(f"{label} must contain a TOML table")
        return cast(dict[str, Any], document)

    def _confined_project_file(self, path: Path, *, label: str) -> Path:
        try:
            resolved = path.resolve(strict=True)
        except OSError as exc:
            raise ConfigDocumentError(f"{label} does not resolve to a regular file") from exc
        if not resolved.is_file() or not resolved.is_relative_to(self.project_root):
            raise ConfigDocumentError(f"{label} escapes project_root or is not a regular file")
        return resolved

    @classmethod
    def _read_package_yaml(
        cls,
        resource: Traversable,
        *,
        label: str,
        required: bool,
    ) -> dict[str, Any]:
        try:
            if not resource.is_file():
                if required:
                    raise ConfigDocumentError(f"{label} is missing from the installed package")
                return {}
            text = resource.read_text(encoding="utf-8")
        except ConfigDocumentError:
            raise
        except (OSError, UnicodeError) as exc:
            raise ConfigDocumentError(f"{label} cannot be read as UTF-8") from exc
        return cls._parse_yaml(text, label=label)

    @staticmethod
    def _parse_yaml(text: str, *, label: str) -> dict[str, Any]:
        try:
            document = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise ConfigDocumentError(f"{label} is not valid YAML") from exc
        if type(document) is not dict:
            raise ConfigDocumentError(f"{label} must contain a YAML mapping")
        return cast(dict[str, Any], document)


__all__ = [
    "BudgetConfiguration",
    "ConfigDocumentError",
    "ConfigResolutionError",
    "ConfigResolver",
    "ConfigValidationError",
    "DataEgressConfiguration",
    "EffectiveConfiguration",
    "VerificationConfiguration",
    "deep_merge",
    "redact_configuration",
]
