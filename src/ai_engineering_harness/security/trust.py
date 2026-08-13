"""Deterministic, capability-based trust boundary for one repository root."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

TrustMode = Literal["restricted", "trusted"]
_DIGEST_PATTERN = r"^sha256:[0-9a-f]{64}$"
_CAPABILITY_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$"
_ENVIRONMENT_NAME_PATTERN = r"^[A-Za-z_][A-Za-z0-9_]*$"
_CapabilityId = Annotated[str, StringConstraints(pattern=_CAPABILITY_ID_PATTERN)]
_EnvironmentName = Annotated[str, StringConstraints(pattern=_ENVIRONMENT_NAME_PATTERN)]
_PYTHON_REFERENCE = re.compile(r"^python:[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*:[A-Za-z_]\w*$")


class TrustBoundaryError(ValueError):
    """Base error for invalid or denied trust-boundary operations."""


class TrustBoundaryConfigurationError(TrustBoundaryError):
    """An explicit authorization or persisted snapshot is malformed."""


class TrustCapabilityDeniedError(TrustBoundaryError, PermissionError):
    """A requested capability is not present in the effective boundary."""


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")


class SecretGrant(_StrictFrozenModel):
    """Allow one exact environment name only for named consumers."""

    name: _EnvironmentName
    consumers: tuple[_CapabilityId, ...] = Field(min_length=1)

    @field_validator("consumers", mode="before")
    @classmethod
    def freeze_consumers(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @field_validator("consumers")
    @classmethod
    def validate_consumers(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("secret consumers must be unique")
        return tuple(sorted(value))


class TrustAuthorization(_StrictFrozenModel):
    """External capability grant bound to one exact repository root.

    Project files and the trust marker never construct this object. A caller must provide it through
    an explicit composition boundary.
    """

    repository_root: Annotated[str, StringConstraints(min_length=1)]
    python_contracts: tuple[str, ...] = ()
    executable_aliases: tuple[str, ...] = ()
    secret_grants: tuple[SecretGrant, ...] = ()
    hook_ids: tuple[_CapabilityId, ...] = ()
    promotion_allowed: bool = False

    @field_validator(
        "python_contracts",
        "executable_aliases",
        "secret_grants",
        "hook_ids",
        mode="before",
    )
    @classmethod
    def freeze_sequences(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @field_validator("python_contracts")
    @classmethod
    def validate_python_contracts(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(_PYTHON_REFERENCE.fullmatch(reference) is None for reference in value):
            raise ValueError("python contracts must be exact python:module:Symbol references")
        return _sorted_unique(value, label="python contracts")

    @field_validator("executable_aliases")
    @classmethod
    def validate_executable_aliases(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _validated_executables(value)

    @field_validator("hook_ids")
    @classmethod
    def validate_hook_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _sorted_unique(value, label="hook ids")

    @field_validator("secret_grants")
    @classmethod
    def validate_secret_grants(cls, value: tuple[SecretGrant, ...]) -> tuple[SecretGrant, ...]:
        names = tuple(grant.name for grant in value)
        if len(set(names)) != len(names):
            raise ValueError("secret grant names must be unique")
        return tuple(sorted(value, key=lambda grant: grant.name))


class TrustEvaluationResult(_StrictFrozenModel):
    """Effective non-secret boundary snapshot used by all effect consumers."""

    schema_version: Literal["1.0"] = "1.0"
    repository_root: Annotated[str, StringConstraints(min_length=1)]
    authorized_root: Annotated[str, StringConstraints(min_length=1)]
    mode: TrustMode
    marker_present: bool
    python_contracts: tuple[str, ...] = ()
    executable_aliases: tuple[str, ...] = ()
    secret_grants: tuple[SecretGrant, ...] = ()
    hook_ids: tuple[str, ...] = ()
    promotion_allowed: bool = False
    reasons: tuple[str, ...] = Field(min_length=1)
    digest: str = Field(pattern=_DIGEST_PATTERN)

    @field_validator(
        "python_contracts",
        "executable_aliases",
        "secret_grants",
        "hook_ids",
        "reasons",
        mode="before",
    )
    @classmethod
    def freeze_sequences(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def validate_snapshot(self) -> Self:
        repository_root = _resolve_directory(self.repository_root, label="snapshot repository root")
        authorized_root = _resolve_directory(self.authorized_root, label="snapshot authorized root")
        if os.fspath(repository_root) != self.repository_root or os.fspath(authorized_root) != self.authorized_root:
            raise TrustBoundaryConfigurationError("trust boundary roots must be canonical")
        if (
            _sorted_unique(self.python_contracts, label="python contracts")
            != self.python_contracts
            or any(_PYTHON_REFERENCE.fullmatch(value) is None for value in self.python_contracts)
            or _validated_executables(self.executable_aliases) != self.executable_aliases
            or _sorted_unique(self.hook_ids, label="hook ids") != self.hook_ids
            or any(re.fullmatch(_CAPABILITY_ID_PATTERN, value) is None for value in self.hook_ids)
        ):
            raise TrustBoundaryConfigurationError(
                "trust boundary capability lists must be canonical"
            )
        secret_names = tuple(grant.name for grant in self.secret_grants)
        if secret_names != tuple(sorted(set(secret_names))):
            raise TrustBoundaryConfigurationError(
                "trust boundary secret grants must be canonical"
            )
        if self.mode == "restricted" and (self.python_contracts or self.hook_ids):
            raise TrustBoundaryConfigurationError(
                "restricted boundaries cannot authorize project Python imports or hooks"
            )
        expected = _snapshot_digest(self._payload())
        if self.digest != expected:
            raise TrustBoundaryConfigurationError(
                f"trust boundary digest mismatch: expected {expected}, received {self.digest}"
            )
        return self

    @property
    def is_trusted(self) -> bool:
        return self.mode == "trusted"

    @property
    def allow_python_contracts(self) -> bool:
        return bool(self.python_contracts)

    @property
    def allow_unprompted_commands(self) -> bool:
        return bool(self.executable_aliases)

    def snapshot(self) -> dict[str, object]:
        """Return the canonical non-secret persisted representation including its digest."""

        return self.model_dump(mode="json")

    def snapshot_json(self) -> str:
        return _canonical_json(self.snapshot())

    @classmethod
    def from_snapshot(cls, value: object) -> TrustEvaluationResult:
        if type(value) is dict and type(value.get("digest")) is str:
            payload = {key: item for key, item in value.items() if key != "digest"}
            if value["digest"] != _snapshot_digest(payload):
                raise TrustBoundaryConfigurationError(
                    "persisted trust boundary digest mismatch"
                )
        try:
            return cls.model_validate(value)
        except (TypeError, ValueError) as exc:
            raise TrustBoundaryConfigurationError("persisted trust boundary is invalid") from exc

    def bind_authorized_root(self, root: str | os.PathLike[str]) -> TrustEvaluationResult:
        """Create an equally capable boundary confined to another exact existing root."""

        self._require_repository_signal_unchanged()
        resolved = _resolve_directory(root, label="authorized root")
        payload = self._payload()
        payload["authorized_root"] = os.fspath(resolved)
        return self._build(payload)

    def require_root(self, root: str | os.PathLike[str]) -> None:
        self._require_repository_signal_unchanged()
        resolved = _resolve_directory(root, label="effect root")
        if resolved != Path(self.authorized_root):
            raise TrustCapabilityDeniedError("effect root does not match the trust boundary")

    def require_executable(self, alias: str) -> None:
        self._require_repository_signal_unchanged()
        if alias not in self.executable_aliases:
            raise TrustCapabilityDeniedError("executable alias is not allowed by the trust boundary")

    def require_secret(self, name: str, *, consumer: str) -> None:
        self._require_repository_signal_unchanged()
        for grant in self.secret_grants:
            if grant.name == name and consumer in grant.consumers:
                return
        raise TrustCapabilityDeniedError(
            "secret name is not allowed for this trust-boundary consumer"
        )

    def validate_hook(
        self,
        hook_id: str,
        *,
        destructive: bool,
        approval_granted: bool,
    ) -> bool:
        try:
            self._require_repository_signal_unchanged()
        except TrustCapabilityDeniedError:
            return False
        if self.mode != "trusted" or hook_id not in self.hook_ids:
            return False
        return not (destructive and not approval_granted)

    def require_promotion(self, *, approval_granted: bool) -> None:
        self._require_repository_signal_unchanged()
        if not self.promotion_allowed:
            raise TrustCapabilityDeniedError("promotion is not allowed by the trust boundary")
        if not approval_granted:
            raise TrustCapabilityDeniedError("promotion requires explicit approval")

    def _require_repository_signal_unchanged(self) -> None:
        marker = Path(self.repository_root) / ".harness" / "trusted_repository"
        if marker.is_file() != self.marker_present:
            raise TrustCapabilityDeniedError(
                "repository trust signal diverges from the boundary snapshot"
            )

    def _payload(self) -> dict[str, object]:
        return self.model_dump(mode="json", exclude={"digest"})

    @classmethod
    def _build(cls, payload: dict[str, object]) -> TrustEvaluationResult:
        return cls.model_validate({**payload, "digest": _snapshot_digest(payload)})


class TrustBoundaryEvaluator:
    """Evaluate repository signals and intersect them with an external capability grant."""

    def __init__(
        self,
        project_root: Path | None = None,
        *,
        authorization: TrustAuthorization | None = None,
    ) -> None:
        self.project_root = _resolve_directory(project_root or Path.cwd(), label="project root")
        if authorization is not None and not isinstance(authorization, TrustAuthorization):
            raise TrustBoundaryConfigurationError(
                "authorization must be an explicit TrustAuthorization"
            )
        if authorization is not None:
            authorized_repository = _resolve_directory(
                authorization.repository_root,
                label="authorization repository root",
            )
            if authorized_repository != self.project_root:
                raise TrustBoundaryConfigurationError(
                    "authorization repository root does not match project root"
                )
        self.authorization = authorization

    def evaluate(self, force_untrusted: bool = False) -> TrustEvaluationResult:
        """Return a deterministic snapshot; the project marker grants no capability by itself."""

        if type(force_untrusted) is not bool:
            raise TrustBoundaryConfigurationError("force_untrusted must be an explicit bool")
        marker = self.project_root / ".harness" / "trusted_repository"
        marker_present = marker.is_file()
        mode: TrustMode = "trusted" if marker_present and not force_untrusted else "restricted"
        authorization = self.authorization
        python_contracts = (
            authorization.python_contracts
            if authorization is not None and mode == "trusted"
            else ()
        )
        hook_ids = (
            authorization.hook_ids
            if authorization is not None and mode == "trusted"
            else ()
        )
        executable_aliases = authorization.executable_aliases if authorization is not None else ()
        secret_grants = authorization.secret_grants if authorization is not None else ()
        promotion_allowed = authorization.promotion_allowed if authorization is not None else False
        reasons = (
            "restricted mode forced by the caller",
        ) if force_untrusted else (
            "trusted marker observed; capabilities require an external authorization",
        ) if marker_present else (
            "trusted marker absent; restricted mode is the default",
        )
        payload: dict[str, object] = {
            "schema_version": "1.0",
            "repository_root": os.fspath(self.project_root),
            "authorized_root": os.fspath(self.project_root),
            "mode": mode,
            "marker_present": marker_present,
            "python_contracts": python_contracts,
            "executable_aliases": executable_aliases,
            "secret_grants": tuple(grant.model_dump(mode="json") for grant in secret_grants),
            "hook_ids": hook_ids,
            "promotion_allowed": promotion_allowed,
            "reasons": reasons,
        }
        return TrustEvaluationResult._build(payload)

    def validate_rollback_hook(
        self,
        boundary: TrustEvaluationResult,
        *,
        hook_id: str,
        is_destructive: bool,
        user_approved: bool,
    ) -> bool:
        if not isinstance(boundary, TrustEvaluationResult):
            raise TrustBoundaryConfigurationError("boundary must be a TrustEvaluationResult")
        return boundary.validate_hook(
            hook_id,
            destructive=is_destructive,
            approval_granted=user_approved,
        )


def _sorted_unique(values: tuple[str, ...], *, label: str) -> tuple[str, ...]:
    if len(set(values)) != len(values):
        raise ValueError(f"{label} must be unique")
    return tuple(sorted(values))


def _validated_executables(values: tuple[str, ...]) -> tuple[str, ...]:
    if any(
        type(value) is not str
        or not value.strip()
        or value != value.strip()
        or "\x00" in value
        or "\r" in value
        or "\n" in value
        for value in values
    ):
        raise ValueError("executable aliases must be trimmed non-empty command identities")
    return _sorted_unique(values, label="executable aliases")


def _resolve_directory(root: str | os.PathLike[str], *, label: str) -> Path:
    try:
        resolved = Path(root).resolve(strict=True)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise TrustBoundaryConfigurationError(
            f"{label} must resolve to an existing directory"
        ) from exc
    if not resolved.is_dir() or resolved.parent == resolved:
        raise TrustBoundaryConfigurationError(
            f"{label} must resolve to a non-filesystem-root directory"
        )
    return resolved


def _canonical_json(value: object) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise TrustBoundaryConfigurationError("trust boundary is not canonical JSON") from exc


def _snapshot_digest(payload: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


__all__ = [
    "SecretGrant",
    "TrustAuthorization",
    "TrustBoundaryConfigurationError",
    "TrustBoundaryError",
    "TrustBoundaryEvaluator",
    "TrustCapabilityDeniedError",
    "TrustEvaluationResult",
    "TrustMode",
]
