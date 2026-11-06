"""Runtime-event redaction must not crash on values it cannot deep-copy (iteration 62).

SimNow 2026-11-06: a Gateway pair example crashed in ``BtApiStore.subscribe``
because the redaction of its ``market_data_subscribe_request`` event walked the
SDK market runtime (a configured secret source) and ``dataclasses.asdict``
deep-copied a market bootstrap whose snapshot payload is a ``mappingproxy``.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from backtrader.utils.runtime_redaction import credential_values, redact_runtime_value

SECRET = "s3cret-value-1234"


@dataclass(frozen=True)
class _Envelope:
    payload: Any


@dataclass(frozen=True)
class _Bootstrap:
    snapshot: _Envelope
    stream_id: str = "stream-1"


@dataclass
class _HoldsLock:
    password: str
    lock: Any = field(default_factory=threading.Lock)


class _Runtime:
    def __init__(self) -> None:
        self.last_bootstrap = _Bootstrap(_Envelope(MappingProxyType({"data": {"price": 1.0}})))
        self.client = _HoldsLock(SECRET)


def test_dataclass_with_a_mappingproxy_payload_is_walked_without_copying():
    bootstrap = _Bootstrap(_Envelope(MappingProxyType({"password": SECRET, "x": 1})))
    assert credential_values(bootstrap) == {SECRET}


def test_uncopyable_dataclass_fields_do_not_break_secret_collection():
    assert credential_values(_HoldsLock(SECRET)) == {SECRET}


def test_runtime_event_redaction_with_a_live_runtime_secret_source():
    sources = ({"exchange_kwargs": {"CTP___FUTURE": {"password": SECRET}}}, {"runtime": _Runtime()})
    event = {"details": {"note": f"login with {SECRET}", "channels": ["tick"]}}
    redacted = redact_runtime_value(event, secret_sources=sources)
    assert SECRET not in str(redacted)
    assert redacted["details"]["channels"] == ["tick"]
