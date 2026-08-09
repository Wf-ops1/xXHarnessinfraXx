"""Canonical contract for commit-bound structural index snapshots."""

from __future__ import annotations

import hmac
import re
from collections.abc import Iterable, Mapping
from pathlib import PurePosixPath
from typing import Final, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from ai_engineering_harness.persistence.base import canonical_json_digest, canonical_json_object

STRUCTURAL_SNAPSHOT_SCHEMA_VERSION: Final = "1.0"
_FULL_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")

StructuralSymbolKind = Literal["module", "class", "function", "method", "import"]


def validate_commit_sha(value: object) -> str:
    """Return a canonical full Git SHA or reject the identity."""

    if type(value) is not str or _FULL_GIT_SHA.fullmatch(value) is None:
        raise ValueError("commit_sha must be a lowercase 40-character hexadecimal Git SHA")
    return value


class StructuralSymbol(BaseModel):
    """One normalized source symbol produced by a structural index backend."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: StructuralSymbolKind
    name: str = Field(min_length=1, max_length=512)
    qualified_name: str = Field(min_length=1, max_length=2048)
    path: str = Field(min_length=1, max_length=4096)
    line_start: int = Field(ge=1, strict=True)
    line_end: int = Field(ge=1, strict=True)

    @field_validator("name", "qualified_name")
    @classmethod
    def _validate_nonblank_text(cls, value: str) -> str:
        if not value.strip() or value != value.strip() or "\x00" in value:
            raise ValueError("symbol names must be nonblank, trimmed, and NUL-free")
        return value

    @field_validator("path")
    @classmethod
    def _validate_relative_posix_path(cls, value: str) -> str:
        if "\x00" in value or "\\" in value or value != value.strip():
            raise ValueError("symbol path must be a trimmed NUL-free POSIX path")
        path = PurePosixPath(value)
        if (
            path.is_absolute()
            or value.startswith("/")
            or path.as_posix() != value
            or any(part in {"", ".", ".."} for part in path.parts)
        ):
            raise ValueError("symbol path must be a normalized relative POSIX path")
        return value

    @model_validator(mode="after")
    def _validate_line_range(self) -> Self:
        if self.line_end < self.line_start:
            raise ValueError("line_end must be greater than or equal to line_start")
        return self


class StructuralSnapshot(BaseModel):
    """Immutable, digest-bound structural snapshot that is safe to serve."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = STRUCTURAL_SNAPSHOT_SCHEMA_VERSION
    commit_sha: str
    status: Literal["ready"] = "ready"
    digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    symbols: tuple[StructuralSymbol, ...]

    @field_validator("commit_sha")
    @classmethod
    def _validate_commit_sha(cls, value: str) -> str:
        return validate_commit_sha(value)

    @classmethod
    def create(
        cls,
        commit_sha: str,
        symbols: Iterable[StructuralSymbol | Mapping[str, object]],
    ) -> StructuralSnapshot:
        """Validate content and attach its canonical SHA-256 digest."""

        validated_sha = validate_commit_sha(commit_sha)
        validated_symbols: list[StructuralSymbol] = []
        for symbol in symbols:
            if isinstance(symbol, StructuralSymbol):
                validated_symbols.append(symbol)
            elif isinstance(symbol, Mapping):
                validated_symbols.append(StructuralSymbol.model_validate(dict(symbol)))
            else:
                raise TypeError("symbols must contain StructuralSymbol instances or mappings")
        content = {
            "commit_sha": validated_sha,
            "schema_version": STRUCTURAL_SNAPSHOT_SCHEMA_VERSION,
            "status": "ready",
            "symbols": [symbol.model_dump(mode="json") for symbol in validated_symbols],
        }
        return cls.model_validate(
            {
                **content,
                "digest": canonical_json_digest(canonical_json_object(content)),
            }
        )

    def content_document(self) -> dict[str, object]:
        """Return the exact content covered by ``digest``."""

        return {
            "commit_sha": self.commit_sha,
            "schema_version": self.schema_version,
            "status": self.status,
            "symbols": [symbol.model_dump(mode="json") for symbol in self.symbols],
        }

    def expected_digest(self) -> str:
        """Calculate the digest from the validated content fields."""

        return canonical_json_digest(canonical_json_object(self.content_document()))

    def verify_digest(self) -> None:
        """Reject a structurally valid document whose content was changed."""

        if not hmac.compare_digest(self.digest, self.expected_digest()):
            raise ValueError("structural snapshot digest does not match its content")

    def canonical_json(self) -> str:
        """Serialize the complete snapshot deterministically."""

        return canonical_json_object(self.model_dump(mode="json"))


__all__ = [
    "STRUCTURAL_SNAPSHOT_SCHEMA_VERSION",
    "StructuralSnapshot",
    "StructuralSymbol",
    "StructuralSymbolKind",
    "ValidationError",
    "validate_commit_sha",
]
