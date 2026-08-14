"""Context-scoped secret redaction for text and JSON-safe public evidence."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import ClassVar

_SECRET_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_.:-]*$")
_PLACEHOLDER_CHARACTER = re.compile(r"[^A-Za-z0-9_]")


@dataclass(frozen=True, slots=True, repr=False)
class RedactionContext:
    """Immutable, in-memory values known only to one adapter or execution boundary."""

    _secrets: Mapping[str, str] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self._secrets, Mapping):
            raise TypeError("secrets must be a mapping")
        copied: dict[str, str] = {}
        for name, value in self._secrets.items():
            if not isinstance(name, str) or _SECRET_NAME.fullmatch(name) is None:
                raise ValueError("secret names must be portable non-empty identifiers")
            if not isinstance(value, str) or not value or "\x00" in value:
                raise ValueError("secret values must be non-empty text without null bytes")
            copied[name] = value
        object.__setattr__(self, "_secrets", MappingProxyType(copied))

    @property
    def secret_names(self) -> tuple[str, ...]:
        """Return only nominal identities; raw values are intentionally not enumerable."""

        return tuple(sorted(self._secrets))

    def redact_text(self, text: str) -> str:
        """Project text through this boundary without exposing its values."""

        return Redactor.redact_text(text, context=self)

    def redact_json(self, value: object) -> object:
        """Recursively project one JSON-like value through this boundary."""

        return Redactor.redact_json(value, context=self)

    def _with_secret(self, name: str, value: str) -> RedactionContext:
        """Return a detached context extended by one adapter-owned value."""

        return RedactionContext({**self._secrets, name: value})

    def __repr__(self) -> str:
        return f"RedactionContext(secret_names={self.secret_names!r})"


class Redactor:
    """Remove known and context-scoped secrets before public serialization."""

    _patterns: ClassVar[tuple[re.Pattern[str], ...]] = (
        re.compile(r"sk-[a-zA-Z0-9]{32,}", re.IGNORECASE),
        re.compile(r"sk-ant-[a-zA-Z0-9_-]{32,}", re.IGNORECASE),
        re.compile(
            r"eyJ[a-zA-Z0-9_-]{10,}\.eyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]+"
        ),
        re.compile(
            r"-----BEGIN (?:RSA|OPENSSH) PRIVATE KEY-----[\s\S]+?"
            r"-----END (?:RSA|OPENSSH) PRIVATE KEY-----"
        ),
    )
    _assignment_pattern: ClassVar[re.Pattern[str]] = re.compile(
        r"(?i)(?P<prefix>\b(?:password|passwd|secret|api[_-]?key|access[_-]?token|token)"
        r"\b\s*[:=]\s*)(?:(?P<quote>[\"'])(?P<quoted_value>[^\r\n]*?)"
        r"(?P=quote)|(?P<value>[^\"'\s,;}]+))"
    )
    _header_pattern: ClassVar[re.Pattern[str]] = re.compile(
        r"(?im)^(?P<prefix>[ \t]*(?:authorization|proxy-authorization|cookie|set-cookie|"
        r"x-api-key|api-key)[ \t]*:[ \t]*)(?P<value>[^\r\n]*)"
    )
    _sensitive_key_pattern: ClassVar[re.Pattern[str]] = re.compile(
        r"(?i)(?:^|[^a-z0-9])(?:authorization|proxy[_-]?authorization|cookie|set[_-]?cookie|"
        r"password|passwd|secret|token|api[_-]?key|private[_-]?key)(?:$|[^a-z0-9])"
    )

    @classmethod
    def redact_text(
        cls,
        text: str,
        dynamic_secrets: Mapping[str, str] | None = None,
        *,
        context: RedactionContext | None = None,
    ) -> str:
        """Redact exact and line-wrapped values plus well-known secret surfaces."""

        if not isinstance(text, str):
            raise TypeError("text must be a string")
        if not text:
            return text
        if context is not None and not isinstance(context, RedactionContext):
            raise TypeError("context must be a RedactionContext or None")

        redacted = text
        for name, value in cls._secret_items(context, dynamic_secrets):
            placeholder = cls._placeholder(name)
            redacted = redacted.replace(value, placeholder)
            compact = re.sub(r"[ \t\r\n]+", "", value)
            if len(compact) >= 8:
                fragmented = re.compile(r"[ \t\r\n]*".join(re.escape(char) for char in compact))
                redacted = fragmented.sub(placeholder, redacted)

        redacted = cls._header_pattern.sub(
            lambda match: f"{match.group('prefix')}[REDACTED_SECRET]",
            redacted,
        )
        redacted = cls._assignment_pattern.sub(
            lambda match: (
                f"{match.group('prefix')}{match.group('quote') or ''}"
                f"[REDACTED_SECRET]{match.group('quote') or ''}"
            ),
            redacted,
        )
        for pattern in cls._patterns:
            redacted = pattern.sub("[REDACTED_SECRET]", redacted)
        return redacted

    @classmethod
    def redact_json(
        cls,
        value: object,
        dynamic_secrets: Mapping[str, str] | None = None,
        *,
        context: RedactionContext | None = None,
    ) -> object:
        """Recursively redact JSON-like data while preserving its enclosing structure."""

        if context is not None and not isinstance(context, RedactionContext):
            raise TypeError("context must be a RedactionContext or None")
        if isinstance(value, str):
            return cls.redact_text(value, dynamic_secrets, context=context)
        if value is None or isinstance(value, (bool, int, float)):
            return value
        if isinstance(value, Mapping):
            redacted: dict[str, object] = {}
            for key, item in value.items():
                if not isinstance(key, str):
                    raise TypeError("JSON object keys must be strings")
                safe_key = cls.redact_text(key, dynamic_secrets, context=context)
                if cls._is_sensitive_key(key):
                    redacted[safe_key] = "[REDACTED_SECRET]"
                else:
                    redacted[safe_key] = cls.redact_json(
                        item,
                        dynamic_secrets,
                        context=context,
                    )
            return redacted
        if isinstance(value, (list, tuple)):
            return [
                cls.redact_json(item, dynamic_secrets, context=context)
                for item in value
            ]
        raise TypeError("value must contain only JSON-native data")

    @classmethod
    def _secret_items(
        cls,
        context: RedactionContext | None,
        dynamic_secrets: Mapping[str, str] | None,
    ) -> tuple[tuple[str, str], ...]:
        copied = dict(context._secrets) if context is not None else {}
        if dynamic_secrets is not None:
            if not isinstance(dynamic_secrets, Mapping):
                raise TypeError("dynamic_secrets must be a mapping or None")
            for name, value in dynamic_secrets.items():
                if not isinstance(name, str) or not isinstance(value, str):
                    raise TypeError("dynamic secret names and values must be strings")
                if value:
                    copied[name] = value
        return tuple(sorted(copied.items(), key=lambda item: len(item[1]), reverse=True))

    @staticmethod
    def _placeholder(name: str) -> str:
        normalized = _PLACEHOLDER_CHARACTER.sub("_", name).upper()[:64] or "SECRET"
        return f"[REDACTED_{normalized}]"

    @classmethod
    def _is_sensitive_key(cls, key: str) -> bool:
        normalized = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", key).casefold()
        return cls._sensitive_key_pattern.search(normalized) is not None


__all__ = ["RedactionContext", "Redactor"]
