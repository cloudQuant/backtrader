"""Typed completion evidence for CTP multi-packet queries."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from math import isfinite
from typing import Any, Generic, TypeVar

T = TypeVar("T")

# These seals are intentionally module-private.  A regular ``QueryResult``
# constructed by a caller has no source provenance and cannot be promoted to
# account evidence merely because its string fields happen to match a session.
_QUERY_SOURCE_SEAL = object()
_QUERY_SCOPE_SEAL = object()
_QUERY_MONOTONIC_CLOCK_DOMAIN = "python.time.monotonic"
# Strict evidence is deliberately bounded by an issuer policy.  A caller can
# request a shorter TTL, but a later conversion cannot extend a query beyond
# this trusted maximum age by choosing new UTC and monotonic deadlines.
# Strict query provenance must survive the bounded serial seven-query
# certificate cadence. Individual position evidence keeps a shorter policy
# window in ctp_position_evidence.py.
_QUERY_EVIDENCE_MAX_TTL_SECONDS = 35.0
_QUERY_POSITION_EVIDENCE_MAX_TTL_SECONDS = 5.0


def _canonical_query_value(value: Any) -> Any:
    """Return a deterministic JSON value for native query snapshots.

    Query records remain mutable for legacy consumers.  The strict evidence
    boundary uses this representation only to bind a digest at terminal
    callback time and to detect later mutation; arbitrary ``__str__`` or
    ``repr`` implementations are intentionally unsupported.
    """

    if isinstance(value, Mapping):
        items: dict[str, Any] = {}
        for key, item in value.items():
            if type(key) is not str:
                raise TypeError("query snapshot keys must be exact strings")
            items[key] = _canonical_query_value(item)
        return {key: items[key] for key in sorted(items)}
    if isinstance(value, (list, tuple)):
        return [_canonical_query_value(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if type(value) is float:
        if not isfinite(value):
            # Preserve malformed native evidence as a stable typed marker so
            # the strict row parser can report the field-level reason.  It is
            # still bound by the source digest and can never become a valid
            # quantity merely because a caller mutates the later result.
            return {"__nonfinite_float__": value.hex()}
        return value
    if type(value) in (str, int, bool) or value is None:
        return value
    # Unsupported mutable/native objects are intentionally never normalized
    # via ``str`` or ``repr``.  The type marker keeps the terminal payload
    # bound while the strict parser rejects the field as non-native.
    return {"__unsupported_type__": f"{type(value).__module__}.{type(value).__qualname__}"}


def _query_records_digest(records: Iterable[Any]) -> str:
    """Hash one mutable-compatible record sequence at a point in time."""

    serialized = json.dumps(
        _canonical_query_value(tuple(records)),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return sha256(serialized).hexdigest()


@dataclass(frozen=True)
class _QuerySource:
    """Typed provenance issued by one live ``TraderClient`` query lane.

    ``request_intent_filters`` records the exact string values the SDK meant
    to put in the native request. ``request_filters`` records getter values
    read back from that populated native request before submission.
    """

    _seal: object
    issuer: object
    request_type: str
    request_id: int
    account_fingerprint: str
    connection_generation: int
    trading_day: str
    broker_id: str
    investor_id: str
    request_intent_filters: tuple[tuple[str, str], ...]
    request_filters: tuple[tuple[str, str], ...]
    request_intent_parameters: tuple[tuple[str, float], ...]
    request_parameters: tuple[tuple[str, float], ...]
    explicit_request_filters: tuple[str, ...]
    started_at_utc: datetime
    completed_at_utc: datetime | None
    started_monotonic: float
    completed_monotonic: float | None
    clock_domain_id: str
    records_sha256: str | None
    trusted_expires_at_utc: datetime | None
    trusted_expires_monotonic: float | None


@dataclass(frozen=True)
class _QuerySessionScope:
    """Current session scope issued by the same ``TraderClient`` instance."""

    _seal: object
    issuer: object
    account_fingerprint: str
    connection_generation: int
    trading_day: str
    broker_id: str
    investor_id: str
    read_only_ready: bool
    captured_at_utc: datetime
    captured_monotonic: float


def _new_query_source(
    *,
    issuer: object,
    request_type: str,
    request_id: int,
    account_fingerprint: str,
    connection_generation: int,
    trading_day: str,
    broker_id: str,
    investor_id: str,
    request_intent_filters: tuple[tuple[str, str], ...] = (),
    started_at_utc: datetime,
    completed_at_utc: datetime | None,
    started_monotonic: float,
    completed_monotonic: float | None,
    records_sha256: str | None,
    request_filters: tuple[tuple[str, str], ...] = (),
    request_intent_parameters: tuple[tuple[str, float], ...] = (),
    request_parameters: tuple[tuple[str, float], ...] = (),
    explicit_request_filters: tuple[str, ...] = (),
) -> _QuerySource:
    trusted_expires_at_utc = None
    trusted_expires_monotonic = None
    if completed_at_utc is not None:
        trusted_expires_at_utc = completed_at_utc + timedelta(
            seconds=_QUERY_EVIDENCE_MAX_TTL_SECONDS
        )
    if completed_monotonic is not None:
        trusted_expires_monotonic = completed_monotonic + _QUERY_EVIDENCE_MAX_TTL_SECONDS
    return _QuerySource(
        _seal=_QUERY_SOURCE_SEAL,
        issuer=issuer,
        request_type=request_type,
        request_id=request_id,
        account_fingerprint=account_fingerprint,
        connection_generation=connection_generation,
        trading_day=trading_day,
        broker_id=broker_id,
        investor_id=investor_id,
        request_intent_filters=request_intent_filters,
        request_filters=request_filters,
        request_intent_parameters=request_intent_parameters,
        request_parameters=request_parameters,
        explicit_request_filters=explicit_request_filters,
        started_at_utc=started_at_utc,
        completed_at_utc=completed_at_utc,
        started_monotonic=started_monotonic,
        completed_monotonic=completed_monotonic,
        clock_domain_id=_QUERY_MONOTONIC_CLOCK_DOMAIN,
        records_sha256=records_sha256,
        trusted_expires_at_utc=trusted_expires_at_utc,
        trusted_expires_monotonic=trusted_expires_monotonic,
    )


def _attach_query_source(result: QueryResult[Any], source: _QuerySource) -> QueryResult[Any]:
    if type(source) is not _QuerySource or source._seal is not _QUERY_SOURCE_SEAL:
        raise TypeError("invalid query source")
    object.__setattr__(result, "_source", source)
    return result


def _new_query_session_scope(
    *,
    issuer: object,
    account_fingerprint: str,
    connection_generation: int,
    trading_day: str,
    broker_id: str,
    investor_id: str,
    read_only_ready: bool,
    captured_at_utc: datetime,
    captured_monotonic: float,
) -> _QuerySessionScope:
    return _QuerySessionScope(
        _seal=_QUERY_SCOPE_SEAL,
        issuer=issuer,
        account_fingerprint=account_fingerprint,
        connection_generation=connection_generation,
        trading_day=trading_day,
        broker_id=broker_id,
        investor_id=investor_id,
        read_only_ready=read_only_ready,
        captured_at_utc=captured_at_utc,
        captured_monotonic=captured_monotonic,
    )


@dataclass(frozen=True)
class QueryResult(Generic[T]):
    """Immutable result for one CTP request ID and connection generation.

    ``records`` may be empty only when ``complete`` proves that the matching
    successful terminal packet was observed.  Consumers must not interpret an
    empty incomplete result as an empty account, position, order, trade, fee,
    margin, or instrument set.
    """

    request_type: str
    request_id: int
    connection_generation: int
    account_fingerprint: str
    started_at_utc: datetime
    completed_at_utc: datetime | None
    is_last_seen: bool
    error_code: int | None
    error_message: str
    timed_out: bool
    complete: bool
    records: tuple[T, ...] = field(default_factory=tuple)
    late_callback_count: int = 0
    unsupported: bool = False
    submit_code: int | None = None
    _source: _QuerySource | None = field(default=None, init=False, repr=False, compare=False)

    @property
    def query_source(self) -> _QuerySource | None:
        """Return private typed provenance, when issued by a live query lane."""

        return self._source

    @property
    def first(self) -> T | None:
        """Return the first record only for a complete query."""
        if not self.complete or not self.records:
            return None
        return self.records[0]

    @property
    def evidence_complete(self) -> bool:
        """Alias used by fail-closed consumers of heterogeneous query envelopes."""
        return self.complete

    def as_dict(self, *, include_records: bool = False) -> dict[str, Any]:
        """Return JSON-friendly completion evidence for public envelopes."""
        data: dict[str, Any] = {
            "request_type": self.request_type,
            "request_id": self.request_id,
            "connection_generation": self.connection_generation,
            "account_fingerprint": self.account_fingerprint,
            "started_at_utc": self.started_at_utc.isoformat(),
            "completed_at_utc": (
                self.completed_at_utc.isoformat() if self.completed_at_utc is not None else None
            ),
            "is_last_seen": self.is_last_seen,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "timed_out": self.timed_out,
            "complete": self.complete,
            "evidence_complete": self.evidence_complete,
            "record_count": len(self.records),
            "late_callback_count": self.late_callback_count,
            "unsupported": self.unsupported,
            "submit_code": self.submit_code,
        }
        if include_records:
            data["records"] = list(self.records)
        return data

    @classmethod
    def unavailable(
        cls,
        *,
        request_type: str,
        request_id: int,
        connection_generation: int,
        account_fingerprint: str,
        started_at_utc: datetime,
        error_message: str,
        error_code: int | None = None,
        unsupported: bool = False,
        records: Iterable[T] = (),
    ) -> QueryResult[T]:
        """Build a fail-closed local result when no valid terminal packet exists."""
        return cls(
            request_type=request_type,
            request_id=request_id,
            connection_generation=connection_generation,
            account_fingerprint=account_fingerprint,
            started_at_utc=started_at_utc,
            completed_at_utc=datetime.now(started_at_utc.tzinfo),
            is_last_seen=False,
            error_code=error_code,
            error_message=error_message,
            timed_out=False,
            complete=False,
            records=tuple(records),
            unsupported=unsupported,
        )


__all__ = ["QueryResult"]
