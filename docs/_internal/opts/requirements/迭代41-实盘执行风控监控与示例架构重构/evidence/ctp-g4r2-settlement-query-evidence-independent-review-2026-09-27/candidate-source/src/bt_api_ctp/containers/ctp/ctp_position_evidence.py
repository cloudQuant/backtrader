"""Strict, read-only evidence for one CTP investor-position query.

The legacy :mod:`ctp_position` container is intentionally permissive.  It
turns absent numeric fields into zero and an unknown direction into ``net`` so
older consumers keep working.  This module is a separate boundary for
consumers that need to know whether a value was present, unknown, or an
explicit zero.  It only records the facts returned by one completed public
``QueryResult``; it does not apply exchange offset policy or derive close
buckets.
"""

from __future__ import annotations

import json
import time
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from math import isfinite
from types import MappingProxyType
from typing import Any, NoReturn

from bt_api_ctp.query import (
    _QUERY_EVIDENCE_MAX_TTL_SECONDS,
    _QUERY_MONOTONIC_CLOCK_DOMAIN,
    _QUERY_POSITION_EVIDENCE_MAX_TTL_SECONDS,
    _QUERY_SCOPE_SEAL,
    _QUERY_SOURCE_SEAL,
    QueryResult,
    _query_records_digest,
    _QuerySessionScope,
    _QuerySource,
)

from .ctp_position import (
    CTP_POSITION_ACCOUNT_FIELDS,
    CTP_POSITION_FROZEN_FIELDS,
    CTP_POSITION_IDENTITY_FIELDS,
    CTP_POSITION_QUANTITY_FIELDS,
    ctp_position_field,
)

_REQUIRED_FIELDS = (
    *CTP_POSITION_IDENTITY_FIELDS,
    *CTP_POSITION_QUANTITY_FIELDS,
    "LongFrozen",
    "ShortFrozen",
)
_ALL_FIELDS = (
    *CTP_POSITION_IDENTITY_FIELDS,
    *CTP_POSITION_ACCOUNT_FIELDS,
    *CTP_POSITION_QUANTITY_FIELDS,
    *CTP_POSITION_FROZEN_FIELDS,
)
_INTEGER_FROZEN_FIELDS = {
    "LongFrozen",
    "ShortFrozen",
    "CombLongFrozen",
    "CombShortFrozen",
    "StrikeFrozen",
    "AbandonFrozen",
    "YdStrikeFrozen",
}
_DIRECTION_VALUES = frozenset(("1", "2", "3"))
_HEDGE_VALUES = frozenset(("1", "2", "3"))
_POSITION_DATE_VALUES = frozenset(("1", "2"))


class CtpPositionEvidenceError(ValueError):
    """A strict position query cannot be used as complete evidence."""

    def __init__(
        self,
        code: str,
        message: str | None = None,
        *,
        rows: tuple[CtpPositionRowEvidence, ...] = (),
    ) -> None:
        self.code = code
        self.rows = tuple(rows)
        super().__init__(f"{code}: {message or code}")


@dataclass(frozen=True)
class CtpPositionField:
    """One raw field with an explicit presence/validity state."""

    name: str
    present: bool
    state: str
    raw_value: Any = None
    value: Any = None
    reason: str | None = None

    @property
    def known(self) -> bool:
        return self.state == "value"

    @property
    def is_explicit_zero(self) -> bool:
        return self.known and self.value == 0


@dataclass(frozen=True)
class CtpPositionRowEvidence:
    """Immutable raw identity and quantities for one position row."""

    raw_record: Mapping[str, Any]
    fields: Mapping[str, CtpPositionField]
    errors: tuple[str, ...] = ()

    def field(self, name: str) -> CtpPositionField:
        """Return a field state, including optional fields that were absent."""

        try:
            return self.fields[name]
        except KeyError as exc:
            raise KeyError(f"unknown CTP position field: {name}") from exc

    def _value(self, name: str) -> Any:
        return self.field(name).value

    @property
    def instrument_id(self) -> str | None:
        return self._value("InstrumentID")

    @property
    def exchange_id(self) -> str | None:
        return self._value("ExchangeID")

    @property
    def broker_id(self) -> str | None:
        return self._value("BrokerID")

    @property
    def investor_id(self) -> str | None:
        return self._value("InvestorID")

    @property
    def posi_direction(self) -> str | None:
        return self._value("PosiDirection")

    @property
    def hedge_flag(self) -> str | None:
        return self._value("HedgeFlag")

    @property
    def position_date(self) -> str | None:
        return self._value("PositionDate")

    @property
    def trading_day(self) -> str | None:
        return self._value("TradingDay")

    @property
    def position(self) -> int | None:
        return self._value("Position")

    @property
    def today_position(self) -> int | None:
        return self._value("TodayPosition")

    @property
    def yd_position(self) -> int | None:
        return self._value("YdPosition")

    @property
    def long_frozen(self) -> int | None:
        return self._value("LongFrozen")

    @property
    def short_frozen(self) -> int | None:
        return self._value("ShortFrozen")

    @property
    def complete(self) -> bool:
        return not self.errors

    @property
    def identity(self) -> tuple[Any, ...]:
        return tuple(self._value(name) for name in CTP_POSITION_IDENTITY_FIELDS)


@dataclass(frozen=True)
class CtpPositionEvidence:
    """Frozen evidence for exactly one complete positions query."""

    query_request_id: int
    request_type: str
    account_fingerprint: str
    connection_generation: int
    trading_day: str
    started_at_utc: datetime
    completed_at_utc: datetime
    expires_at_utc: datetime
    completed_monotonic: float
    expires_monotonic: float
    clock_domain_id: str
    query_envelope: Mapping[str, Any]
    rows: tuple[CtpPositionRowEvidence, ...]
    source_hash: str
    complete: bool = True

    @property
    def evidence_complete(self) -> bool:
        return self.complete

    @property
    def is_empty(self) -> bool:
        return not self.rows

    @property
    def records(self) -> tuple[CtpPositionRowEvidence, ...]:
        """Alias for consumers that use the QueryResult vocabulary."""

        return self.rows

    @property
    def offset_policy(self) -> None:
        """No exchange-specific close policy is proved by O3a evidence."""

        return None

    @property
    def monotonic_completed_at(self) -> float:
        return self.completed_monotonic

    @property
    def monotonic_expires_at(self) -> float:
        return self.expires_monotonic

    def as_dict(self, *, include_rows: bool = False) -> dict[str, Any]:
        data: dict[str, Any] = {
            "request_type": self.request_type,
            "request_id": self.query_request_id,
            "account_fingerprint": self.account_fingerprint,
            "connection_generation": self.connection_generation,
            "trading_day": self.trading_day,
            "started_at_utc": self.started_at_utc.isoformat(),
            "completed_at_utc": self.completed_at_utc.isoformat(),
            "expires_at_utc": self.expires_at_utc.isoformat(),
            "completed_monotonic": self.completed_monotonic,
            "expires_monotonic": self.expires_monotonic,
            "clock_domain_id": self.clock_domain_id,
            "complete": self.complete,
            "evidence_complete": self.evidence_complete,
            "is_empty": self.is_empty,
            "record_count": len(self.rows),
            "source_hash": self.source_hash,
            "query_envelope": _json_value(self.query_envelope),
        }
        if include_rows:
            data["rows"] = [
                {
                    "raw_record": _json_value(row.raw_record),
                    "fields": {
                        name: {
                            "present": field.present,
                            "state": field.state,
                            "raw_value": _json_value(field.raw_value),
                            "value": _json_value(field.value),
                            "reason": field.reason,
                        }
                        for name, field in row.fields.items()
                    },
                    "errors": list(row.errors),
                }
                for row in self.rows
            ]
        return data


def _is_aware(value: Any) -> bool:
    return (
        isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None
    )


def _utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc)


def _valid_day(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 8 or not value.isdigit():
        return False
    try:
        parsed = datetime.strptime(value, "%Y%m%d")
    except ValueError:
        return False
    return parsed.strftime("%Y%m%d") == value


def _copy_record(source: Any) -> dict[str, Any]:
    if isinstance(source, Mapping):
        return dict(source)
    result: dict[str, Any] = {}
    for name in _ALL_FIELDS:
        present, value = ctp_position_field(source, name)
        if present:
            result[name] = value
    return result


def _snapshot_query_value(value: Any) -> Any:
    """Copy container structure into immutable values without user callbacks."""

    if isinstance(value, Mapping):
        copied: dict[str, Any] = {}
        for key, item in value.items():
            if type(key) is not str:
                raise TypeError("CTP query snapshot mapping keys must be strings")
            copied[key] = _snapshot_query_value(item)
        return MappingProxyType(copied)
    if isinstance(value, (list, tuple)):
        return tuple(_snapshot_query_value(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_snapshot_query_value(item) for item in value)
    return value


def _snapshot_query_records(records: tuple[Any, ...]) -> tuple[Any, ...]:
    """Take one independent records snapshot before strict validation."""

    try:
        return tuple(_snapshot_query_value(record) for record in records)
    except (TypeError, ValueError) as exc:
        raise CtpPositionEvidenceError("position_query_payload_invalid") from exc


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        frozen: dict[Any, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("CTP position evidence mapping keys must be strings")
            frozen[key] = _freeze(item)
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, set):
        return frozenset(_freeze(item) for item in value)
    return value


def _json_value(value: Any) -> Any:
    """Convert frozen/native scalar values to deterministic JSON values."""

    if isinstance(value, Mapping):
        return {key: _json_value(value[key]) for key in sorted(value)}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted(_json_value(item) for item in value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError("non-finite value cannot be hashed")
        return value
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    raise TypeError(f"unsupported value type in CTP position evidence: {type(value)!r}")


def _field_missing(name: str) -> CtpPositionField:
    return CtpPositionField(name=name, present=False, state="missing", reason="absent")


def _unknown_field(name: str, raw: Any, reason: str) -> CtpPositionField:
    return CtpPositionField(
        name=name,
        present=True,
        state="unknown",
        raw_value=raw,
        reason=reason,
    )


def _text_field(name: str, present: bool, raw: Any) -> CtpPositionField:
    if not present:
        return _field_missing(name)
    if type(raw) is not str or not raw or raw != raw.strip() or "\x00" in raw:
        return _unknown_field(name, raw, "nonempty_exact_text_required")
    if name == "PosiDirection" and raw not in _DIRECTION_VALUES:
        return _unknown_field(name, raw, "unknown_direction")
    if name == "HedgeFlag" and raw not in _HEDGE_VALUES:
        return _unknown_field(name, raw, "unknown_hedge")
    if name == "PositionDate" and raw not in _POSITION_DATE_VALUES:
        return _unknown_field(name, raw, "unknown_position_date")
    if name == "TradingDay" and not _valid_day(raw):
        return _unknown_field(name, raw, "invalid_trading_day")
    return CtpPositionField(name=name, present=True, state="value", raw_value=raw, value=raw)


def _decimal_field(name: str, present: bool, raw: Any, *, integer: bool) -> CtpPositionField:
    if not present:
        return _field_missing(name)
    if type(raw) not in (int, float, str, Decimal):
        return _unknown_field(name, raw, "immutable_native_scalar_required")
    try:
        parsed = Decimal(str(raw))
    except (InvalidOperation, ValueError, TypeError):
        return _unknown_field(name, raw, "quantity_not_numeric")
    if not parsed.is_finite() or parsed < 0:
        return _unknown_field(name, raw, "quantity_not_finite_or_nonnegative")
    if integer and parsed != parsed.to_integral_value():
        return _unknown_field(name, raw, "fractional_contract_quantity")
    value: Any = int(parsed) if integer else parsed
    return CtpPositionField(name=name, present=True, state="value", raw_value=raw, value=value)


def parse_ctp_position_row(source: Any) -> CtpPositionRowEvidence:
    """Snapshot and strictly parse one raw CTP position record."""

    raw_record = _copy_record(source)
    fields: dict[str, CtpPositionField] = {}
    for name in CTP_POSITION_IDENTITY_FIELDS:
        present, raw = ctp_position_field(raw_record, name)
        fields[name] = _text_field(name, present, raw)
    for name in CTP_POSITION_ACCOUNT_FIELDS:
        present, raw = ctp_position_field(raw_record, name)
        fields[name] = _text_field(name, present, raw)
    for name in CTP_POSITION_QUANTITY_FIELDS:
        present, raw = ctp_position_field(raw_record, name)
        fields[name] = _decimal_field(name, present, raw, integer=True)
    for name in CTP_POSITION_FROZEN_FIELDS:
        present, raw = ctp_position_field(raw_record, name)
        fields[name] = _decimal_field(
            name,
            present,
            raw,
            integer=name in _INTEGER_FROZEN_FIELDS,
        )

    errors = tuple(name for name in _REQUIRED_FIELDS if fields[name].state != "value")
    for name in (*CTP_POSITION_ACCOUNT_FIELDS, *CTP_POSITION_FROZEN_FIELDS):
        if fields[name].present and fields[name].state != "value" and name not in errors:
            errors += (name,)
    return CtpPositionRowEvidence(
        raw_record=_freeze(raw_record),
        fields=MappingProxyType(fields),
        errors=errors,
    )


def _invalid_time(code: str, message: str) -> NoReturn:
    raise CtpPositionEvidenceError(code, message)


def _session_scope(session_state: Any) -> _QuerySessionScope:
    if (
        type(session_state) is not _QuerySessionScope
        or session_state._seal is not _QUERY_SCOPE_SEAL
    ):
        raise CtpPositionEvidenceError("position_session_scope_untrusted")
    if session_state.read_only_ready is not True:
        raise CtpPositionEvidenceError("position_session_not_read_only_ready")
    if (
        type(session_state.account_fingerprint) is not str
        or not session_state.account_fingerprint
        or session_state.account_fingerprint != session_state.account_fingerprint.strip()
        or type(session_state.broker_id) is not str
        or not session_state.broker_id
        or session_state.broker_id != session_state.broker_id.strip()
        or type(session_state.investor_id) is not str
        or not session_state.investor_id
        or session_state.investor_id != session_state.investor_id.strip()
    ):
        raise CtpPositionEvidenceError("position_session_scope_missing")
    if (
        type(session_state.connection_generation) is not int
        or session_state.connection_generation <= 0
    ):
        raise CtpPositionEvidenceError("position_session_scope_missing")
    if not _valid_day(session_state.trading_day):
        raise CtpPositionEvidenceError("position_session_trading_day_missing")
    if not _is_aware(session_state.captured_at_utc):
        raise CtpPositionEvidenceError("position_session_clock_invalid")
    if (
        type(session_state.captured_monotonic) not in (int, float)
        or isinstance(session_state.captured_monotonic, bool)
        or not isfinite(session_state.captured_monotonic)
        or session_state.captured_monotonic < 0
    ):
        raise CtpPositionEvidenceError("position_session_clock_invalid")
    return session_state


def _query_source(
    result: QueryResult[Any],
    scope: _QuerySessionScope,
    records_snapshot: tuple[Any, ...],
) -> _QuerySource:
    source = result.query_source
    if type(source) is not _QuerySource or source._seal is not _QUERY_SOURCE_SEAL:
        raise CtpPositionEvidenceError("position_query_source_untrusted")
    if source.issuer is not scope.issuer:
        raise CtpPositionEvidenceError("position_query_scope_mismatch")
    if (
        source.request_type != result.request_type
        or source.request_id != result.request_id
        or source.account_fingerprint != result.account_fingerprint
        or source.connection_generation != result.connection_generation
        or source.request_type != "positions"
    ):
        raise CtpPositionEvidenceError("position_query_source_mismatch")
    if (
        source.account_fingerprint != scope.account_fingerprint
        or source.connection_generation != scope.connection_generation
        or source.trading_day != scope.trading_day
        or source.broker_id != scope.broker_id
        or source.investor_id != scope.investor_id
    ):
        raise CtpPositionEvidenceError("position_query_scope_mismatch")
    if (
        source.started_at_utc != result.started_at_utc
        or source.completed_at_utc != result.completed_at_utc
        or source.clock_domain_id != _QUERY_MONOTONIC_CLOCK_DOMAIN
        or not _is_aware(source.started_at_utc)
        or not _is_aware(source.completed_at_utc)
        or type(source.started_monotonic) not in (int, float)
        or isinstance(source.started_monotonic, bool)
        or not isfinite(source.started_monotonic)
        or source.started_monotonic < 0
        or type(source.completed_monotonic) not in (int, float)
        or isinstance(source.completed_monotonic, bool)
        or not isfinite(source.completed_monotonic)
        or source.completed_monotonic < source.started_monotonic
    ):
        raise CtpPositionEvidenceError("position_query_clock_invalid")
    if (
        type(source.records_sha256) is not str
        or len(source.records_sha256) != 64
        or source.records_sha256 != source.records_sha256.lower()
        or any(char not in "0123456789abcdef" for char in source.records_sha256)
    ):
        raise CtpPositionEvidenceError("position_query_source_untrusted")
    try:
        if _query_records_digest(records_snapshot) != source.records_sha256:
            raise CtpPositionEvidenceError("position_query_payload_mismatch")
    except CtpPositionEvidenceError:
        raise
    except (TypeError, ValueError) as exc:
        raise CtpPositionEvidenceError("position_query_payload_invalid") from exc
    if (
        not _is_aware(source.trusted_expires_at_utc)
        or type(source.trusted_expires_monotonic) not in (int, float)
        or isinstance(source.trusted_expires_monotonic, bool)
        or not isfinite(source.trusted_expires_monotonic)
        or source.trusted_expires_monotonic <= source.completed_monotonic
        or abs(
            (_utc(source.trusted_expires_at_utc) - _utc(source.completed_at_utc)).total_seconds()
            - _QUERY_EVIDENCE_MAX_TTL_SECONDS
        )
        > 1e-6
        or abs(
            source.trusted_expires_monotonic
            - source.completed_monotonic
            - _QUERY_EVIDENCE_MAX_TTL_SECONDS
        )
        > 1e-6
    ):
        raise CtpPositionEvidenceError("position_query_clock_invalid")
    if source.completed_monotonic > scope.captured_monotonic:
        raise CtpPositionEvidenceError("position_query_clock_invalid")
    return source


def _query_envelope(result: QueryResult[Any]) -> dict[str, Any]:
    return {
        "request_type": result.request_type,
        "request_id": result.request_id,
        "connection_generation": result.connection_generation,
        "account_fingerprint": result.account_fingerprint,
        "started_at_utc": result.started_at_utc,
        "completed_at_utc": result.completed_at_utc,
        "is_last_seen": result.is_last_seen,
        "error_code": result.error_code,
        "error_message": result.error_message,
        "timed_out": result.timed_out,
        "complete": result.complete,
        "late_callback_count": result.late_callback_count,
        "unsupported": result.unsupported,
        "submit_code": result.submit_code,
    }


def _validate_result_shape(result: QueryResult[Any]) -> None:
    if type(result.request_type) is not str or not result.request_type:
        raise CtpPositionEvidenceError("position_query_envelope_invalid")
    if type(result.request_id) is not int or result.request_id <= 0:
        raise CtpPositionEvidenceError("position_query_identity_invalid")
    if (
        type(result.connection_generation) is not int
        or result.connection_generation <= 0
        or type(result.account_fingerprint) is not str
        or not result.account_fingerprint
        or result.account_fingerprint != result.account_fingerprint.strip()
    ):
        raise CtpPositionEvidenceError("position_query_identity_invalid")
    if type(result.error_message) is not str:
        raise CtpPositionEvidenceError("position_query_envelope_invalid")
    if any(
        type(flag) is not bool
        for flag in (
            result.is_last_seen,
            result.timed_out,
            result.complete,
            result.unsupported,
        )
    ):
        raise CtpPositionEvidenceError("position_query_envelope_invalid")
    if type(result.records) is not tuple:
        raise CtpPositionEvidenceError("position_query_envelope_invalid")
    for name in ("error_code", "submit_code"):
        value = getattr(result, name)
        if value is not None and type(value) is not int:
            raise CtpPositionEvidenceError("position_query_envelope_invalid")
    if type(result.late_callback_count) is not int or result.late_callback_count < 0:
        raise CtpPositionEvidenceError("position_query_envelope_invalid")


def build_ctp_position_evidence(
    result: QueryResult[Any],
    *,
    session_state: Any,
    now_utc: datetime | None = None,
    expires_at_utc: datetime,
    monotonic_now: float | None = None,
    monotonic_expires_at: float | None = None,
) -> CtpPositionEvidence:
    """Build strict immutable evidence from one public positions ``QueryResult``.

    ``session_state`` is read from the live CTP session by the public feed
    adapter.  There is deliberately no caller supplied account/day override:
    a complete empty result is safe only when that current session scope is
    available and agrees with the query envelope.
    """

    if type(result) is not QueryResult:
        raise CtpPositionEvidenceError("position_query_type_invalid")
    if result.request_type != "positions":
        raise CtpPositionEvidenceError("position_query_scope_mismatch")
    _validate_result_shape(result)
    records_snapshot = _snapshot_query_records(result.records)
    scope = _session_scope(session_state)
    source = _query_source(result, scope, records_snapshot)
    account = scope.account_fingerprint
    generation = scope.connection_generation
    trading_day = source.trading_day
    if result.account_fingerprint != account or result.connection_generation != generation:
        raise CtpPositionEvidenceError("position_query_scope_mismatch")
    if not result.complete:
        raise CtpPositionEvidenceError("position_query_incomplete")
    if not result.is_last_seen:
        raise CtpPositionEvidenceError("position_query_not_terminal")
    if result.timed_out:
        raise CtpPositionEvidenceError("position_query_timed_out")
    if result.unsupported:
        raise CtpPositionEvidenceError("position_query_unsupported")
    if result.error_code not in (None, 0):
        raise CtpPositionEvidenceError("position_query_error")
    if result.submit_code not in (None, 0):
        raise CtpPositionEvidenceError("position_query_submit_failed")

    current = now_utc if now_utc is not None else datetime.now(timezone.utc)
    if not _is_aware(result.started_at_utc) or not _is_aware(result.completed_at_utc):
        _invalid_time("position_query_time_invalid", "query timestamps must be aware")
    if not _is_aware(current) or not _is_aware(expires_at_utc):
        _invalid_time("position_query_time_invalid", "evidence timestamps must be aware")
    started = _utc(result.started_at_utc)
    completed = _utc(result.completed_at_utc)
    current = _utc(current)
    requested_expires = _utc(expires_at_utc)
    if started > completed or completed > current:
        _invalid_time("position_query_time_invalid", "query interval is not current")
    if requested_expires <= completed:
        _invalid_time("position_query_time_invalid", "expiry must follow query completion")
    requested_ttl_seconds = (requested_expires - completed).total_seconds()
    if not isfinite(requested_ttl_seconds) or requested_ttl_seconds <= 0:
        _invalid_time("position_query_time_invalid", "expiry interval is invalid")
    mono_current = time.monotonic() if monotonic_now is None else monotonic_now
    if monotonic_expires_at is None:
        _invalid_time("position_query_clock_invalid", "monotonic expiry is required")
    if (
        type(mono_current) not in (int, float)
        or isinstance(mono_current, bool)
        or not isfinite(mono_current)
        or type(monotonic_expires_at) not in (int, float)
        or isinstance(monotonic_expires_at, bool)
        or not isfinite(monotonic_expires_at)
        or monotonic_expires_at <= source.completed_monotonic
        or abs((monotonic_expires_at - source.completed_monotonic) - requested_ttl_seconds) > 1e-6
    ):
        _invalid_time("position_query_clock_invalid", "monotonic expiry is not bound")
    # The caller may shorten the issuer's deadline, but cannot replace it
    # with a new one.  Clamp both clock domains to the immutable policy-bound
    # deadline captured by the trusted query source.
    position_expires = completed + timedelta(
        seconds=_QUERY_POSITION_EVIDENCE_MAX_TTL_SECONDS
    )
    position_monotonic_expires = (
        source.completed_monotonic + _QUERY_POSITION_EVIDENCE_MAX_TTL_SECONDS
    )
    trusted_expires = min(_utc(source.trusted_expires_at_utc), position_expires)
    expires = min(requested_expires, trusted_expires)
    monotonic_expires = min(
        float(monotonic_expires_at),
        float(source.trusted_expires_monotonic),
        position_monotonic_expires,
    )
    ttl_seconds = (expires - completed).total_seconds()
    if (
        not isfinite(ttl_seconds)
        or ttl_seconds <= 0
        or monotonic_expires <= source.completed_monotonic
        or abs((monotonic_expires - source.completed_monotonic) - ttl_seconds) > 1e-6
    ):
        _invalid_time("position_query_clock_invalid", "monotonic expiry is not bound")
    if mono_current < source.completed_monotonic:
        _invalid_time("position_query_clock_invalid", "monotonic query interval is invalid")
    if current >= expires or mono_current >= monotonic_expires:
        raise CtpPositionEvidenceError("position_query_expired")

    # The local QueryResult view carries the already snapshotted records.  The
    # exact ``result.records`` spelling preserves the public trace/consumer
    # hook while ensuring parsing cannot re-read the caller's mutable tuple.
    result = replace(result, records=records_snapshot)
    try:
        rows = tuple(parse_ctp_position_row(record) for record in result.records)
    except (TypeError, ValueError) as exc:
        raise CtpPositionEvidenceError("position_row_invalid") from exc
    row_errors = [row for row in rows if row.errors]
    row_error_ids = {id(row) for row in row_errors}
    for row in rows:
        day_field = row.field("TradingDay")
        if day_field.state == "value" and day_field.value != trading_day:
            if id(row) not in row_error_ids:
                row_errors.append(row)
                row_error_ids.add(id(row))
        for name, expected in (
            ("BrokerID", source.broker_id),
            ("InvestorID", source.investor_id),
        ):
            field = row.field(name)
            if field.state == "value" and field.value != expected:
                if id(row) not in row_error_ids:
                    row_errors.append(row)
                    row_error_ids.add(id(row))
    if row_errors:
        account_mismatch = any(
            row.field(name).state == "value" and row.field(name).value != expected
            for row in row_errors
            for name, expected in (
                ("BrokerID", source.broker_id),
                ("InvestorID", source.investor_id),
            )
        )
        day_mismatch = any(
            row.field("TradingDay").state == "value"
            and row.field("TradingDay").value != trading_day
            for row in row_errors
        )
        code = (
            "position_row_account_mismatch"
            if account_mismatch
            else ("position_row_scope_mismatch" if day_mismatch else "position_row_incomplete")
        )
        raise CtpPositionEvidenceError(code, rows=tuple(row_errors))

    seen: set[tuple[Any, ...]] = set()
    for row in rows:
        if row.identity in seen:
            raise CtpPositionEvidenceError("position_row_duplicate", rows=rows)
        seen.add(row.identity)

    envelope = _query_envelope(result)
    envelope["session_scope"] = {
        "account_fingerprint": account,
        "connection_generation": generation,
        "trading_day": trading_day,
        "broker_id": scope.broker_id,
        "investor_id": scope.investor_id,
        "read_only_ready": True,
    }
    envelope["query_source"] = {
        "request_type": source.request_type,
        "request_id": source.request_id,
        "account_fingerprint": source.account_fingerprint,
        "connection_generation": source.connection_generation,
        "trading_day": source.trading_day,
        "started_at_utc": source.started_at_utc,
        "completed_at_utc": source.completed_at_utc,
        "started_monotonic": source.started_monotonic,
        "completed_monotonic": source.completed_monotonic,
        "clock_domain_id": source.clock_domain_id,
        "records_sha256": source.records_sha256,
        "trusted_expires_at_utc": source.trusted_expires_at_utc,
        "trusted_expires_monotonic": source.trusted_expires_monotonic,
    }
    frozen_envelope = _freeze(envelope)
    hash_input = {
        "query_envelope": frozen_envelope,
        "rows": tuple(row.raw_record for row in rows),
        "expires_at_utc": expires,
        "expires_monotonic": monotonic_expires,
    }
    try:
        serialized = json.dumps(
            _json_value(hash_input),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise CtpPositionEvidenceError("position_row_value_invalid", rows=rows) from exc
    source_hash = sha256(serialized).hexdigest()
    return CtpPositionEvidence(
        query_request_id=result.request_id,
        request_type=result.request_type,
        account_fingerprint=account,
        connection_generation=generation,
        trading_day=trading_day,
        started_at_utc=started,
        completed_at_utc=completed,
        expires_at_utc=expires,
        completed_monotonic=float(source.completed_monotonic),
        expires_monotonic=monotonic_expires,
        clock_domain_id=source.clock_domain_id,
        query_envelope=frozen_envelope,
        rows=rows,
        source_hash=source_hash,
    )


adapt_ctp_positions_query = build_ctp_position_evidence


__all__ = [
    "CtpPositionEvidence",
    "CtpPositionEvidenceError",
    "CtpPositionField",
    "CtpPositionRowEvidence",
    "adapt_ctp_positions_query",
    "build_ctp_position_evidence",
    "parse_ctp_position_row",
]
