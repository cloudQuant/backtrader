"""Regression coverage for redacting dataclasses with runtime-only fields."""

import socket
import threading
from dataclasses import dataclass
from types import MappingProxyType

from backtrader.utils.redaction import masked_copy, redact_diagnostic
from backtrader.utils.runtime_redaction import redact_runtime_value, sanitize_exception


_SYNTHETIC_SECRET = "redaction-test-marker-never-log"


@dataclass
class RuntimeDiagnostic:
    api_secret: str
    metadata: object
    lock: object
    socket_value: object
    recursive: object = None


def _make_runtime_diagnostic():
    sock = socket.socket()
    value = RuntimeDiagnostic(
        api_secret=_SYNTHETIC_SECRET,
        metadata=MappingProxyType(
            {
                "context_token": _SYNTHETIC_SECRET,
                "description": "safe metadata",
            }
        ),
        lock=threading.Lock(),
        socket_value=sock,
    )
    value.recursive = value
    return value, sock


def _assert_secret_not_present(value):
    if _SYNTHETIC_SECRET in repr(value):
        raise AssertionError("redaction leaked a synthetic credential marker")


def test_masked_copy_walks_dataclass_fields_without_deepcopy():
    value, sock = _make_runtime_diagnostic()
    try:
        masked = masked_copy(value)
        diagnostic = redact_diagnostic(value)
    finally:
        sock.close()

    assert masked["api_secret"] == "***"
    assert diagnostic == masked
    assert masked["metadata"] == {
        "context_token": "***",
        "description": "safe metadata",
    }
    assert masked["lock"] == type(value.lock).__name__
    assert masked["socket_value"] == "socket"
    assert masked["recursive"] == "<recursive>"
    _assert_secret_not_present(masked)


def test_runtime_redaction_collects_and_masks_dataclass_secrets():
    value, sock = _make_runtime_diagnostic()
    try:
        redacted = redact_runtime_value(value, secret_sources=(value,))
    finally:
        sock.close()

    assert redacted["api_secret"] == "***"
    assert redacted["metadata"]["context_token"] == "***"
    assert redacted["metadata"]["description"] == "safe metadata"
    assert redacted["lock"] == type(value.lock).__name__
    assert redacted["socket_value"] == "socket"
    assert redacted["recursive"] == "<recursive>"
    _assert_secret_not_present(redacted)


def test_sanitize_exception_preserves_error_and_redacts_runtime_dataclass_fields():
    value, sock = _make_runtime_diagnostic()
    error = RuntimeError(value)
    error.diagnostic = value
    warnings = []
    try:
        result = sanitize_exception(
            error,
            secret_sources=(value,),
            warning_sink=warnings.append,
        )
    finally:
        sock.close()

    assert result is error
    assert isinstance(error.args[0], dict)
    assert error.args[0]["api_secret"] == "***"
    assert error.diagnostic["metadata"]["context_token"] == "***"
    assert warnings == []
    _assert_secret_not_present((error.args, vars(error)))
