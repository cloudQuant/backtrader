"""Credential redaction for diagnostics and exception surfaces.

The helpers are framework-owned and provider-neutral. They never invoke an
arbitrary object's ``repr``: vendor exceptions and transport objects commonly
include credentials in their default representation.
"""

from __future__ import annotations

import re
from dataclasses import asdict, is_dataclass
from decimal import Decimal
from typing import Any, Mapping, Optional

__all__ = [
    "SENSITIVE_KEYS",
    "is_sensitive_key",
    "masked_copy",
    "redact_diagnostic",
]

SENSITIVE_KEYS = frozenset(
    {
        "api_key",
        "api_secret",
        "access_token",
        "auth_code",
        "authorization",
        "credential",
        "credentials",
        "listen_key",
        "listenkey",
        "passphrase",
        "passwd",
        "password",
        "private_key",
        "public_key",
        "secret",
        "secret_key",
        "session_token",
        "signature",
        "token",
    }
)
_SENSITIVE_KEY_COMPACT = frozenset(key.replace("_", "") for key in SENSITIVE_KEYS)

_SENSITIVE_TEXT_RE = re.compile(
    r"(?i)\b(api[_-]?key|api[_-]?secret|auth[_-]?code|credential(?:s)?|"
    r"authorization|listen[_-]?key|passphrase|passwd|password|private[_-]?key|"
    r"secret(?:[_-]?key)?|signature|(?:access|session)[_-]?token|token)\b"
    r"(\s*[\"']?\s*[:=]\s*[\"']?)([^,;\s\"'}]+)"
)
_AUTHORIZATION_TEXT_RE = re.compile(r"(?i)\b(bearer|basic)\s+[^,;\s]+")
_SENSITIVE_QUERY_RE = re.compile(
    r"(?i)([?&](?:api[_-]?key|authorization|listen[_-]?key|signature|"
    r"(?:access|session)[_-]?token|token)=)[^&#\s]*"
)


def is_sensitive_key(key: Any) -> bool:
    """Return whether ``key`` conventionally names a credential value."""
    normalized = re.sub(r"[^a-z0-9]+", "_", str(key).strip().lower()).strip("_")
    compact = normalized.replace("_", "")
    if normalized in SENSITIVE_KEYS or compact in _SENSITIVE_KEY_COMPACT:
        return True
    return any(normalized.endswith(f"_{sensitive_key}") for sensitive_key in SENSITIVE_KEYS)


def _redact_text(value: str) -> str:
    value = _AUTHORIZATION_TEXT_RE.sub(r"\1 ***", value)
    value = _SENSITIVE_TEXT_RE.sub(r"\1\2***", value)
    return _SENSITIVE_QUERY_RE.sub(r"\1***", value)


def masked_copy(value: Any, _active: Optional[set[int]] = None) -> Any:
    """Build a cycle-safe diagnostic copy without invoking arbitrary repr methods."""
    if isinstance(value, BaseException):
        return type(value).__name__
    if isinstance(value, str):
        return _redact_text(value)
    if value is None or isinstance(value, (bool, int, float, Decimal)):
        return value

    active = set() if _active is None else _active
    identity = id(value)
    if identity in active:
        return "<recursive>"
    active.add(identity)
    try:
        if isinstance(value, Mapping):
            return {
                key: "***" if is_sensitive_key(key) else masked_copy(item, active)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [masked_copy(item, active) for item in value]
        if isinstance(value, tuple):
            return tuple(masked_copy(item, active) for item in value)
        if isinstance(value, set):
            return [masked_copy(item, active) for item in value]
        if isinstance(value, frozenset):
            return tuple(masked_copy(item, active) for item in value)
        if is_dataclass(value) and not isinstance(value, type):
            return masked_copy(asdict(value), active)
        try:
            attributes = vars(value)
        except (TypeError, AttributeError):
            return type(value).__name__
        return {
            key: "***" if is_sensitive_key(key) else masked_copy(item, active)
            for key, item in attributes.items()
        }
    finally:
        active.discard(identity)


def redact_diagnostic(value: Any) -> Any:
    """Recursively remove credential material from diagnostic values."""
    if isinstance(value, BaseException):
        return type(value).__name__
    if isinstance(value, Mapping):
        return {
            key: "***" if is_sensitive_key(key) else redact_diagnostic(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_diagnostic(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_diagnostic(item) for item in value)
    if isinstance(value, set):
        return [redact_diagnostic(item) for item in value]
    if isinstance(value, frozenset):
        return tuple(redact_diagnostic(item) for item in value)
    if isinstance(value, str):
        return _redact_text(value)
    if value is None or isinstance(value, (bool, int, float, Decimal)):
        return value
    try:
        return masked_copy(value)
    except Exception:
        return type(value).__name__
