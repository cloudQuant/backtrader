"""Store-independent redaction for runtime values and exception fields.

Callers provide the configuration objects that may contain secrets. This
module keeps no Store reference or credential state; it makes bounded copies
with the existing :mod:`backtrader.utils.redaction` primitives and can
optionally report projection failures through a caller-owned warning sink.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import fields, is_dataclass
from decimal import Decimal
from typing import Any, Callable, Optional, Set

from .redaction import is_sensitive_key, masked_copy

__all__ = [
    "credential_values",
    "is_sensitive_key",
    "redact_runtime_value",
    "replace_secret_values",
    "sanitize_exception",
]


def credential_values(
    value: Any,
    sensitive_parent: bool = False,
    _active: Optional[Set[int]] = None,
) -> Set[str]:
    """Collect credential strings from an explicitly supplied value tree.

    Strings are collected only beneath a sensitive key and only when at least
    four characters long, matching the Store's prior runtime projection.
    Mapping/sequence/dataclass/object traversal is cycle-safe and does not call
    arbitrary ``repr`` methods.
    """

    result: Set[str] = set()
    if sensitive_parent and isinstance(value, str):
        if len(value) >= 4:
            result.add(value)
        return result
    if value is None or isinstance(value, (str, bytes, bool, int, float, Decimal)):
        return result

    active = set() if _active is None else _active
    identity = id(value)
    if identity in active:
        return result
    active.add(identity)
    try:
        if isinstance(value, Mapping):
            for key, item in value.items():
                result.update(
                    credential_values(
                        item,
                        sensitive_parent or is_sensitive_key(key),
                        active,
                    )
                )
            return result
        if isinstance(value, (list, tuple, set, frozenset)):
            for item in value:
                result.update(credential_values(item, sensitive_parent, active))
            return result
        if is_dataclass(value) and not isinstance(value, type):
            # Walk the fields in place: ``dataclasses.asdict`` deep-copies every
            # leaf and fails on values that cannot be copied (a mappingproxy
            # payload of an SDK market bootstrap, locks, sockets), which turned
            # a runtime-event redaction into a Store crash (iteration 62).
            return credential_values(
                {field.name: getattr(value, field.name, None) for field in fields(value)},
                sensitive_parent,
                active,
            )
        try:
            attributes = vars(value)
        except (TypeError, AttributeError):
            return result
        return credential_values(attributes, sensitive_parent, active)
    finally:
        active.discard(identity)


def replace_secret_values(value: Any, secret_values: Iterable[str]) -> Any:
    """Return a recursive copy with each supplied secret substring masked."""

    return _replace_secret_values(value, tuple(secret_values))


def _replace_secret_values(value: Any, secret_values: tuple[str, ...]) -> Any:
    if isinstance(value, Mapping):
        return {
            key: _replace_secret_values(item, secret_values)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_replace_secret_values(item, secret_values) for item in value]
    if isinstance(value, tuple):
        return tuple(_replace_secret_values(item, secret_values) for item in value)
    if isinstance(value, set):
        return {_replace_secret_values(item, secret_values) for item in value}
    if isinstance(value, frozenset):
        return frozenset(_replace_secret_values(item, secret_values) for item in value)
    if isinstance(value, str):
        for secret in secret_values:
            value = value.replace(secret, "***")
    return value


def _collect_secrets(secret_sources: Iterable[Any]) -> Set[str]:
    result: Set[str] = set()
    for source in secret_sources:
        result.update(credential_values(source))
    return result


def _redact_with_secrets(value: Any, secrets: Set[str]) -> Any:
    if isinstance(value, BaseException):
        safe_args = [replace_secret_values(masked_copy(item), secrets) for item in value.args]
        message = " ".join(str(item) for item in safe_args if item not in (None, ""))
        return message or type(value).__name__
    return replace_secret_values(masked_copy(value), secrets)


def redact_runtime_value(value: Any, *, secret_sources: Iterable[Any] = ()) -> Any:
    """Make a diagnostic-safe value copy using explicit credential sources."""

    return _redact_with_secrets(value, _collect_secrets(secret_sources))


def sanitize_exception(
    exc: BaseException,
    *,
    secret_sources: Iterable[Any] = (),
    warning_sink: Optional[Callable[[str], Any]] = None,
) -> BaseException:
    """Redact an exception's args and attached fields in place.

    ``warning_sink`` receives only one of two finite phase codes if projection
    itself fails. It never receives the exception, its text, or field values.
    """

    sources = tuple(secret_sources)
    try:
        exc.args = tuple(
            redact_runtime_value(item, secret_sources=sources) for item in exc.args
        )
    except Exception:
        _warn(warning_sink, "EXCEPTION_ARGS_PROJECTION_FAILED")
    try:
        for key, value in vars(exc).items():
            setattr(exc, key, redact_runtime_value(value, secret_sources=sources))
    except Exception:
        _warn(warning_sink, "EXCEPTION_ATTRIBUTES_PROJECTION_FAILED")
    return exc


def _warn(warning_sink: Optional[Callable[[str], Any]], phase_code: str) -> None:
    if warning_sink is None:
        return
    try:
        warning_sink(phase_code)
    except Exception:
        pass
