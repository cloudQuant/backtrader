"""Digest-only certificate for one read-only native CTP query sequence.

The builder accepts each typed ``QueryResult`` immediately after its read-only
query returns.  It verifies and freezes the terminal source and payload digest
while that individual result is inside the issuer's original freshness bound.
The final certificate binds the results to one client/session generation; it
does not claim the seven reads were one atomic exchange snapshot and grants no
execution authority.  Per-query completion and expiry timestamps remain
visible so consumers can assess the age of every read.
"""

from __future__ import annotations

import json
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from math import isfinite
from typing import Any

from bt_api_ctp.query import (
    _QUERY_EVIDENCE_MAX_TTL_SECONDS,
    _QUERY_MONOTONIC_CLOCK_DOMAIN,
    _QUERY_SCOPE_SEAL,
    _QUERY_SOURCE_SEAL,
    QueryResult,
    _query_records_digest,
    _QuerySessionScope,
    _QuerySource,
)

_REQUIRED_QUERY_TYPES = (
    "account",
    "positions",
    "orders",
    "trades",
    "instruments",
    "margin_rate",
    "commission_rate",
)
_CERTIFICATE_SCHEMA = "ctp_native_query_certificate.v4"
_CERTIFICATE_SEAL = object()
_SETTLEMENT_EVIDENCE_SCHEMA = "ctp_settlement_confirmation_evidence.v1"
_SETTLEMENT_EVIDENCE_SEAL = object()
_SETTLEMENT_REQUEST_TYPES = ("settlement_confirmation",)


class CtpNativeQueryCertificateError(ValueError):
    """A native CTP query sequence cannot be certified as complete evidence."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class _QueryDigest:
    request_type: str
    request_id: int
    record_count: int
    records_sha256: str
    request_filters_sha256: str
    request_filter_names: tuple[str, ...]
    explicit_request_filter_names: tuple[str, ...]
    instrument_row_scope: str | None
    instrument_filter_application: str | None
    target_instrument_match_count: int | None
    source_provenance_validated: bool
    complete: bool
    is_last_seen: bool
    timed_out: bool
    unsupported: bool
    error_code: int | None
    error_message_present: bool
    submit_code: int | None
    late_callback_count: int
    started_at_utc: datetime
    completed_at_utc: datetime
    expires_at_utc: datetime
    expires_at_monotonic: float = field(repr=False, compare=False)

    def as_dict(self) -> dict[str, Any]:
        return {
            "request_type": self.request_type,
            "request_id": self.request_id,
            "record_count": self.record_count,
            "records_sha256": self.records_sha256,
            "request_filters_sha256": self.request_filters_sha256,
            "request_filter_names": list(self.request_filter_names),
            "explicit_request_filter_names": list(self.explicit_request_filter_names),
            "instrument_row_scope": self.instrument_row_scope,
            "instrument_filter_application": self.instrument_filter_application,
            "target_instrument_match_count": self.target_instrument_match_count,
            "source_provenance_validated": self.source_provenance_validated,
            "complete": self.complete,
            "is_last_seen": self.is_last_seen,
            "timed_out": self.timed_out,
            "unsupported": self.unsupported,
            "error_code": self.error_code,
            "error_message_present": self.error_message_present,
            "submit_code": self.submit_code,
            "late_callback_count": self.late_callback_count,
            "started_at_utc": self.started_at_utc.isoformat(),
            "completed_at_utc": self.completed_at_utc.isoformat(),
            "expires_at_utc": self.expires_at_utc.isoformat(),
        }


@dataclass(frozen=True)
class CtpNativeQueryCertificate:
    """Immutable, digest-only summary for seven terminal native read queries."""

    account_fingerprint_sha256: str
    broker_id_sha256: str
    investor_id_sha256: str
    instrument_id_sha256: str
    exchange_id_sha256: str
    hedge_flag_sha256: str
    connection_generation: int
    trading_day: str
    queries: tuple[_QueryDigest, ...]
    _certificate_sha256: str = field(repr=False)
    _seal: object = field(default=None, init=False, repr=False, compare=False)

    def _require_trusted(self) -> None:
        if self._seal is not _CERTIFICATE_SEAL:
            raise CtpNativeQueryCertificateError("query_certificate_untrusted")

    @property
    def certificate_sha256(self) -> str:
        """Return the canonical digest for a builder-issued certificate."""

        self._require_trusted()
        return self._certificate_sha256

    @property
    def query_digest(self) -> str:
        """Return the canonical SHA256 digest for this complete query bundle."""

        return self.certificate_sha256

    @property
    def query_digests(self) -> tuple[tuple[str, str], ...]:
        """Return immutable request-type/payload-digest pairs in canonical order."""

        self._require_trusted()
        return tuple((query.request_type, query.records_sha256) for query in self.queries)

    def as_public_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly view containing no raw IDs or query records."""

        self._require_trusted()
        return {
            "schema": _CERTIFICATE_SCHEMA,
            "complete": True,
            "atomic_snapshot": False,
            "execution_authorized": False,
            "scope": {
                "account_fingerprint_sha256": self.account_fingerprint_sha256,
                "broker_id_sha256": self.broker_id_sha256,
                "investor_id_sha256": self.investor_id_sha256,
                "instrument_id_sha256": self.instrument_id_sha256,
                "exchange_id_sha256": self.exchange_id_sha256,
                "hedge_flag_sha256": self.hedge_flag_sha256,
                "connection_generation": self.connection_generation,
                "trading_day": self.trading_day,
            },
            "queries": [query.as_dict() for query in self.queries],
            "query_digest": self.query_digest,
            "certificate_sha256": self.certificate_sha256,
        }


def _is_aware(value: Any) -> bool:
    return (
        isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None
    )


def _sha256_text(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _canonical_digest(value: Any) -> str:
    serialized = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return sha256(serialized).hexdigest()


def _scope_for_client(client: Any) -> _QuerySessionScope:
    get_scope = getattr(client, "get_query_session_scope", None)
    if not callable(get_scope):
        raise CtpNativeQueryCertificateError("query_session_scope_unavailable")
    try:
        scope = get_scope()
    except Exception as exc:
        raise CtpNativeQueryCertificateError("query_session_scope_unavailable") from exc
    if type(scope) is not _QuerySessionScope or scope._seal is not _QUERY_SCOPE_SEAL:
        raise CtpNativeQueryCertificateError("query_session_scope_untrusted")
    if (
        not scope.read_only_ready
        or type(scope.issuer) is not object
        or type(scope.account_fingerprint) is not str
        or not scope.account_fingerprint
        or scope.account_fingerprint != scope.account_fingerprint.strip()
        or type(scope.connection_generation) is not int
        or scope.connection_generation <= 0
        or type(scope.trading_day) is not str
        or len(scope.trading_day) != 8
        or not scope.trading_day.isdigit()
        or type(scope.broker_id) is not str
        or not scope.broker_id
        or scope.broker_id != scope.broker_id.strip()
        or type(scope.investor_id) is not str
        or not scope.investor_id
        or scope.investor_id != scope.investor_id.strip()
        or not _is_aware(scope.captured_at_utc)
        or type(scope.captured_monotonic) not in (int, float)
        or isinstance(scope.captured_monotonic, bool)
        or not isfinite(scope.captured_monotonic)
        or scope.captured_monotonic < 0
    ):
        raise CtpNativeQueryCertificateError("query_session_scope_invalid")
    try:
        day = datetime.strptime(scope.trading_day, "%Y%m%d")
    except ValueError as exc:
        raise CtpNativeQueryCertificateError("query_session_scope_invalid") from exc
    if day.strftime("%Y%m%d") != scope.trading_day:
        raise CtpNativeQueryCertificateError("query_session_scope_invalid")
    return scope


def _same_scope(left: _QuerySessionScope, right: _QuerySessionScope) -> bool:
    return (
        left._seal is right._seal
        and left.issuer is right.issuer
        and left.account_fingerprint == right.account_fingerprint
        and left.connection_generation == right.connection_generation
        and left.trading_day == right.trading_day
        and left.broker_id == right.broker_id
        and left.investor_id == right.investor_id
        and right.read_only_ready
    )


def _query_result_shape(
    result: QueryResult[Any], *, accepted_request_types: tuple[str, ...] | None = None
) -> None:
    request_types = _REQUIRED_QUERY_TYPES if accepted_request_types is None else accepted_request_types
    if type(result.request_type) is not str or result.request_type not in request_types:
        raise CtpNativeQueryCertificateError("query_type_invalid")
    if type(result.request_id) is not int or result.request_id <= 0:
        raise CtpNativeQueryCertificateError("query_request_id_invalid")
    if (
        type(result.connection_generation) is not int
        or result.connection_generation <= 0
        or type(result.account_fingerprint) is not str
        or not result.account_fingerprint
    ):
        raise CtpNativeQueryCertificateError("query_identity_invalid")
    if type(result.records) is not tuple:
        raise CtpNativeQueryCertificateError("query_envelope_invalid")
    if any(
        type(value) is not bool
        for value in (
            result.complete,
            result.is_last_seen,
            result.timed_out,
            result.unsupported,
        )
    ):
        raise CtpNativeQueryCertificateError("query_envelope_invalid")
    if type(result.late_callback_count) is not int or result.late_callback_count < 0:
        raise CtpNativeQueryCertificateError("query_envelope_invalid")
    if result.error_code is not None and type(result.error_code) is not int:
        raise CtpNativeQueryCertificateError("query_envelope_invalid")
    if result.submit_code is not None and type(result.submit_code) is not int:
        raise CtpNativeQueryCertificateError("query_envelope_invalid")
    if type(result.error_message) is not str:
        raise CtpNativeQueryCertificateError("query_envelope_invalid")


def _source_for_result(
    result: QueryResult[Any],
    scope: _QuerySessionScope,
    *,
    now_utc: datetime,
    now_monotonic: float,
    expiry_error_code: str = "query_expired_before_capture",
    accepted_request_types: tuple[str, ...] | None = None,
) -> _QuerySource:
    source = result.query_source
    if type(source) is not _QuerySource or source._seal is not _QUERY_SOURCE_SEAL:
        raise CtpNativeQueryCertificateError("query_source_untrusted")
    if source.issuer is not scope.issuer:
        raise CtpNativeQueryCertificateError("query_client_mismatch")
    if (
        source.request_type != result.request_type
        or source.request_id != result.request_id
        or source.account_fingerprint != result.account_fingerprint
        or source.connection_generation != result.connection_generation
        or source.request_type
        not in (_REQUIRED_QUERY_TYPES if accepted_request_types is None else accepted_request_types)
    ):
        raise CtpNativeQueryCertificateError("query_source_mismatch")
    if (
        source.account_fingerprint != scope.account_fingerprint
        or source.connection_generation != scope.connection_generation
        or source.trading_day != scope.trading_day
        or source.broker_id != scope.broker_id
        or source.investor_id != scope.investor_id
    ):
        raise CtpNativeQueryCertificateError("query_session_mismatch")
    if (
        source.started_at_utc != result.started_at_utc
        or source.completed_at_utc != result.completed_at_utc
        or not _is_aware(source.started_at_utc)
        or not _is_aware(source.completed_at_utc)
        or source.started_at_utc > source.completed_at_utc
        or source.clock_domain_id != _QUERY_MONOTONIC_CLOCK_DOMAIN
        or type(source.started_monotonic) not in (int, float)
        or isinstance(source.started_monotonic, bool)
        or not isfinite(source.started_monotonic)
        or type(source.completed_monotonic) not in (int, float)
        or isinstance(source.completed_monotonic, bool)
        or not isfinite(source.completed_monotonic)
        or source.started_monotonic < 0
        or source.completed_monotonic < source.started_monotonic
        or source.completed_monotonic > now_monotonic
    ):
        raise CtpNativeQueryCertificateError("query_clock_invalid")
    if (
        type(source.records_sha256) is not str
        or len(source.records_sha256) != 64
        or source.records_sha256 != source.records_sha256.lower()
        or any(char not in "0123456789abcdef" for char in source.records_sha256)
    ):
        raise CtpNativeQueryCertificateError("query_source_untrusted")
    if (
        not _is_aware(source.trusted_expires_at_utc)
        or type(source.trusted_expires_monotonic) not in (int, float)
        or isinstance(source.trusted_expires_monotonic, bool)
        or not isfinite(source.trusted_expires_monotonic)
        or source.trusted_expires_monotonic <= source.completed_monotonic
        or abs(
            (source.trusted_expires_at_utc - source.completed_at_utc).total_seconds()
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
        raise CtpNativeQueryCertificateError("query_clock_invalid")
    if (
        now_utc >= source.trusted_expires_at_utc
        or now_monotonic >= source.trusted_expires_monotonic
    ):
        raise CtpNativeQueryCertificateError(expiry_error_code)
    if not isinstance(source.request_filters, tuple) or any(
        type(item) is not tuple
        or len(item) != 2
        or type(item[0]) is not str
        or type(item[1]) is not str
        for item in source.request_filters
    ):
        raise CtpNativeQueryCertificateError("query_filter_provenance_invalid")
    names = tuple(item[0] for item in source.request_filters)
    if len(names) != len(set(names)) or names != tuple(sorted(names)):
        raise CtpNativeQueryCertificateError("query_filter_provenance_invalid")
    explicit_names = source.explicit_request_filters
    if (
        not isinstance(explicit_names, tuple)
        or any(type(name) is not str for name in explicit_names)
        or len(explicit_names) != len(set(explicit_names))
        or explicit_names != tuple(sorted(explicit_names))
        or any(name not in names for name in explicit_names)
    ):
        raise CtpNativeQueryCertificateError("query_filter_provenance_invalid")
    try:
        payload_digest = _query_records_digest(result.records)
    except (TypeError, ValueError) as exc:
        raise CtpNativeQueryCertificateError("query_payload_invalid") from exc
    if payload_digest != source.records_sha256:
        raise CtpNativeQueryCertificateError("query_payload_mismatch")
    return source


def _record_value(record: Any, name: str) -> tuple[bool, Any]:
    if isinstance(record, Mapping):
        return (name in record, record.get(name))
    try:
        return (hasattr(record, name), getattr(record, name, None))
    except Exception as exc:
        raise CtpNativeQueryCertificateError("query_record_invalid") from exc


def _validate_returned_rows(
    result: QueryResult[Any],
    scope: _QuerySessionScope,
    instrument_id: str,
    exchange_id: str,
    hedge_flag: str,
) -> int | None:
    if result.request_type == "account" and len(result.records) != 1:
        raise CtpNativeQueryCertificateError("query_account_row_count_invalid")
    if (
        result.request_type in ("instruments", "margin_rate", "commission_rate")
        and not result.records
    ):
        raise CtpNativeQueryCertificateError("query_required_rows_missing")
    target_instrument_match_count = 0
    for record in result.records:
        for name, expected in (
            ("BrokerID", scope.broker_id),
            ("InvestorID", scope.investor_id),
            ("TradingDay", scope.trading_day),
        ):
            present, value = _record_value(record, name)
            if present and value != expected:
                raise CtpNativeQueryCertificateError("query_row_scope_mismatch")
        if result.request_type == "account":
            broker_present, row_broker = _record_value(record, "BrokerID")
            if not broker_present or row_broker != scope.broker_id:
                raise CtpNativeQueryCertificateError("query_account_row_mismatch")
            investor_present, row_investor = _record_value(record, "InvestorID")
            account_present, row_account = _record_value(record, "AccountID")
            if investor_present and row_investor != scope.investor_id:
                raise CtpNativeQueryCertificateError("query_account_row_mismatch")
            if account_present and row_account != scope.investor_id:
                raise CtpNativeQueryCertificateError("query_account_row_mismatch")
            if not investor_present and (not account_present or row_account != scope.investor_id):
                raise CtpNativeQueryCertificateError("query_account_identity_missing")
        if result.request_type == "instruments":
            present, value = _record_value(record, "InstrumentID")
            if not present or type(value) is not str or not value or value != value.strip():
                raise CtpNativeQueryCertificateError("query_row_instrument_invalid")
            exchange_present, row_exchange = _record_value(record, "ExchangeID")
            if not exchange_present or type(row_exchange) is not str or row_exchange != exchange_id:
                raise CtpNativeQueryCertificateError("query_row_exchange_mismatch")
            if value == instrument_id:
                target_instrument_match_count += 1
        elif result.request_type in ("margin_rate", "commission_rate"):
            present, value = _record_value(record, "InstrumentID")
            if not present or value != instrument_id:
                raise CtpNativeQueryCertificateError("query_row_instrument_mismatch")
            exchange_present, row_exchange = _record_value(record, "ExchangeID")
            if exchange_present and row_exchange != exchange_id:
                raise CtpNativeQueryCertificateError("query_row_exchange_mismatch")
        if result.request_type == "margin_rate":
            hedge_present, row_hedge = _record_value(record, "HedgeFlag")
            if hedge_present and row_hedge != hedge_flag:
                raise CtpNativeQueryCertificateError("query_row_hedge_mismatch")
    if result.request_type == "instruments":
        if target_instrument_match_count == 0:
            raise CtpNativeQueryCertificateError("query_target_instrument_missing")
        if target_instrument_match_count != 1:
            raise CtpNativeQueryCertificateError("query_target_instrument_duplicate")
        return target_instrument_match_count
    return None


def _validate_bound_filters(
    result: QueryResult[Any],
    scope: _QuerySessionScope,
    instrument_id: str,
    exchange_id: str,
    hedge_flag: str,
) -> tuple[tuple[str, str], ...]:
    source = result.query_source
    if type(source) is not _QuerySource:
        raise CtpNativeQueryCertificateError("query_source_untrusted")
    filters = dict(source.request_filters)
    if result.request_type in (
        "account",
        "positions",
        "orders",
        "trades",
        "margin_rate",
        "commission_rate",
    ):
        if (
            filters.get("BrokerID") != scope.broker_id
            or filters.get("InvestorID") != scope.investor_id
        ):
            raise CtpNativeQueryCertificateError("query_filter_scope_mismatch")
    if result.request_type in ("margin_rate", "commission_rate"):
        if filters.get("InstrumentID") != instrument_id or filters.get("ExchangeID") != exchange_id:
            raise CtpNativeQueryCertificateError("query_filter_instrument_mismatch")
    if result.request_type == "instruments":
        if filters.get("InstrumentID") != instrument_id or filters.get("ExchangeID") != exchange_id:
            raise CtpNativeQueryCertificateError("query_filter_instrument_mismatch")
    if result.request_type == "margin_rate" and filters.get("HedgeFlag") != hedge_flag:
        raise CtpNativeQueryCertificateError("query_filter_hedge_mismatch")
    if result.request_type == "margin_rate" and "HedgeFlag" not in source.explicit_request_filters:
        raise CtpNativeQueryCertificateError("query_filter_hedge_not_explicit")
    return source.request_filters


@dataclass(frozen=True)
class CtpSettlementConfirmationEvidence:
    """Source-sealed evidence for one terminal settlement-confirmation query.

    This read-only observation binds one SDK query to a session generation,
    account, trading day, exact request filters and terminal callback record
    digest. It is not a settlement write authorization or a provider receipt.
    """

    request_type: str
    request_id: int
    complete: bool
    is_last_seen: bool
    timed_out: bool
    unsupported: bool
    error_code: int | None
    submit_code: int | None
    late_callback_count: int
    account_fingerprint_sha256: str
    broker_id_sha256: str
    investor_id_sha256: str
    connection_generation: int
    trading_day: str
    request_filter_names: tuple[str, ...]
    request_filters_sha256: str
    terminal_callback_records_sha256: str
    terminal_callback_history_sha256: str
    record_count: int
    confirmed_date: str
    started_at_utc: datetime
    completed_at_utc: datetime
    expires_at_utc: datetime
    expires_at_monotonic: float = field(repr=False, compare=False)
    _evidence_sha256: str = field(repr=False)
    _seal: object = field(default=None, init=False, repr=False, compare=False)

    def _require_trusted(self) -> None:
        if self._seal is not _SETTLEMENT_EVIDENCE_SEAL:
            raise CtpNativeQueryCertificateError("settlement_evidence_untrusted")

    @property
    def evidence_sha256(self) -> str:
        self._require_trusted()
        return self._evidence_sha256

    def as_public_dict(self) -> dict[str, Any]:
        """Return a digest-only view, with no raw account identifiers or rows."""

        self._require_trusted()
        return {
            "schema": _SETTLEMENT_EVIDENCE_SCHEMA,
            "request_type": self.request_type,
            "request_id": self.request_id,
            "complete": self.complete,
            "is_last_seen": self.is_last_seen,
            "timed_out": self.timed_out,
            "unsupported": self.unsupported,
            "error_code": self.error_code,
            "submit_code": self.submit_code,
            "late_callback_count": self.late_callback_count,
            "account_fingerprint_sha256": self.account_fingerprint_sha256,
            "broker_id_sha256": self.broker_id_sha256,
            "investor_id_sha256": self.investor_id_sha256,
            "connection_generation": self.connection_generation,
            "trading_day": self.trading_day,
            "request_filter_names": list(self.request_filter_names),
            "request_filters_sha256": self.request_filters_sha256,
            "terminal_callback_records_sha256": self.terminal_callback_records_sha256,
            "terminal_callback_history_sha256": self.terminal_callback_history_sha256,
            "record_count": self.record_count,
            "confirmed_date": self.confirmed_date,
            "started_at_utc": self.started_at_utc.isoformat(),
            "completed_at_utc": self.completed_at_utc.isoformat(),
            "expires_at_utc": self.expires_at_utc.isoformat(),
            "execution_authorized": False,
            "evidence_sha256": self.evidence_sha256,
        }


class CtpSettlementConfirmationEvidenceBuilder:
    """Validate one settlement query against its current sealed client history."""

    def __init__(self, client: Any) -> None:
        self._client = client

    @staticmethod
    def _require_terminal_query(result: QueryResult[Any]) -> None:
        _query_result_shape(result, accepted_request_types=_SETTLEMENT_REQUEST_TYPES)
        if (
            result.request_type != "settlement_confirmation"
            or result.complete is not True
            or result.is_last_seen is not True
            or result.timed_out is not False
            or result.unsupported is not False
            or result.error_code not in (None, 0)
            or result.error_message != ""
            or result.submit_code not in (None, 0)
            or result.late_callback_count != 0
        ):
            raise CtpNativeQueryCertificateError("settlement_query_incomplete")

    @staticmethod
    def _require_exact_source(
        result: QueryResult[Any],
        scope: _QuerySessionScope,
        *,
        now_utc: datetime,
        now_monotonic: float,
    ) -> _QuerySource:
        CtpSettlementConfirmationEvidenceBuilder._require_terminal_query(result)
        source = _source_for_result(
            result,
            scope,
            now_utc=now_utc,
            now_monotonic=now_monotonic,
            accepted_request_types=_SETTLEMENT_REQUEST_TYPES,
        )
        expected_filters = (
            ("BrokerID", scope.broker_id),
            ("InvestorID", scope.investor_id),
        )
        if (
            source.request_intent_filters != expected_filters
            or source.request_filters != expected_filters
            or source.explicit_request_filters != ()
            or source.request_intent_parameters != ()
            or source.request_parameters != ()
        ):
            raise CtpNativeQueryCertificateError("settlement_query_filter_scope_mismatch")
        if len(result.records) != 1:
            raise CtpNativeQueryCertificateError("settlement_query_row_count_invalid")
        record = result.records[0]
        broker_present, row_broker = _record_value(record, "BrokerID")
        investor_present, row_investor = _record_value(record, "InvestorID")
        confirm_date_present, confirm_date = _record_value(record, "ConfirmDate")
        trading_day_present, row_trading_day = _record_value(record, "TradingDay")
        if (
            not broker_present
            or type(row_broker) is not str
            or row_broker != scope.broker_id
            or not investor_present
            or type(row_investor) is not str
            or row_investor != scope.investor_id
            or not confirm_date_present
            or type(confirm_date) is not str
            or len(confirm_date) != 8
            or not confirm_date.isdigit()
            or confirm_date != scope.trading_day
            or (trading_day_present and (
                type(row_trading_day) is not str or row_trading_day != scope.trading_day
            ))
        ):
            raise CtpNativeQueryCertificateError("settlement_query_row_scope_mismatch")
        return source

    @staticmethod
    def _same_source(left: _QuerySource, right: _QuerySource) -> bool:
        names = (
            "issuer",
            "request_type",
            "request_id",
            "account_fingerprint",
            "connection_generation",
            "trading_day",
            "broker_id",
            "investor_id",
            "request_intent_filters",
            "request_filters",
            "request_intent_parameters",
            "request_parameters",
            "explicit_request_filters",
            "started_at_utc",
            "completed_at_utc",
            "started_monotonic",
            "completed_monotonic",
            "clock_domain_id",
            "records_sha256",
            "trusted_expires_at_utc",
            "trusted_expires_monotonic",
        )
        return all(
            (getattr(left, name) is getattr(right, name))
            if name == "issuer"
            else (getattr(left, name) == getattr(right, name))
            for name in names
        )

    def build(self, result: QueryResult[Any]) -> CtpSettlementConfirmationEvidence:
        """Build evidence only from a fresh, current terminal callback readback."""

        initial_scope = _scope_for_client(self._client)
        now_utc = datetime.now(timezone.utc)
        now_monotonic = time.monotonic()
        source = self._require_exact_source(
            result,
            initial_scope,
            now_utc=now_utc,
            now_monotonic=now_monotonic,
        )
        get_current_result = getattr(self._client, "get_query_result", None)
        if not callable(get_current_result):
            raise CtpNativeQueryCertificateError("settlement_query_current_result_unavailable")
        try:
            current_result = get_current_result(result.request_id)
        except Exception as exc:
            raise CtpNativeQueryCertificateError(
                "settlement_query_current_result_unavailable"
            ) from exc
        if (
            type(current_result) is not QueryResult
            or current_result.request_type != result.request_type
            or current_result.request_id != result.request_id
            or current_result.connection_generation != result.connection_generation
            or current_result.account_fingerprint != result.account_fingerprint
            or current_result.records != result.records
        ):
            raise CtpNativeQueryCertificateError("settlement_query_current_result_mismatch")
        current_source = self._require_exact_source(
            current_result,
            initial_scope,
            now_utc=now_utc,
            now_monotonic=now_monotonic,
        )
        if not self._same_source(source, current_source):
            raise CtpNativeQueryCertificateError("settlement_query_current_result_mismatch")

        filters_payload = {
            "filters": list(source.request_filters),
            "explicit_filters": list(source.explicit_request_filters),
        }
        request_filters_sha256 = _canonical_digest(filters_payload)
        callback_history_payload = {
            "schema": "ctp_settlement_confirmation_terminal_history.v1",
            "callback_name": "OnRspQrySettlementInfoConfirm",
            "request_type": result.request_type,
            "request_id": result.request_id,
            "connection_generation": result.connection_generation,
            "trading_day": source.trading_day,
            "request_intent_filters": list(source.request_intent_filters),
            "request_filters": list(source.request_filters),
            "explicit_request_filters": list(source.explicit_request_filters),
            "terminal": result.is_last_seen,
            "complete": result.complete,
            "late_callback_count": result.late_callback_count,
            "error_code": result.error_code,
            "submit_code": result.submit_code,
            "records_sha256": source.records_sha256,
            "started_at_utc": source.started_at_utc.isoformat(),
            "completed_at_utc": source.completed_at_utc.isoformat(),
        }
        callback_history_sha256 = _canonical_digest(callback_history_payload)
        confirmed_date = _record_value(result.records[0], "ConfirmDate")[1]
        evidence_payload = {
            "schema": _SETTLEMENT_EVIDENCE_SCHEMA,
            "request_type": result.request_type,
            "request_id": result.request_id,
            "complete": result.complete,
            "is_last_seen": result.is_last_seen,
            "timed_out": result.timed_out,
            "unsupported": result.unsupported,
            "error_code": result.error_code,
            "submit_code": result.submit_code,
            "late_callback_count": result.late_callback_count,
            "account_fingerprint_sha256": _sha256_text(source.account_fingerprint),
            "broker_id_sha256": _sha256_text(source.broker_id),
            "investor_id_sha256": _sha256_text(source.investor_id),
            "connection_generation": result.connection_generation,
            "trading_day": source.trading_day,
            "request_filter_names": ["BrokerID", "InvestorID"],
            "request_filters_sha256": request_filters_sha256,
            "terminal_callback_records_sha256": source.records_sha256,
            "terminal_callback_history_sha256": callback_history_sha256,
            "record_count": 1,
            "confirmed_date": confirmed_date,
            "started_at_utc": source.started_at_utc.isoformat(),
            "completed_at_utc": source.completed_at_utc.isoformat(),
            "expires_at_utc": source.trusted_expires_at_utc.isoformat(),
            "execution_authorized": False,
        }
        evidence = CtpSettlementConfirmationEvidence(
            request_type=result.request_type,
            request_id=result.request_id,
            complete=True,
            is_last_seen=True,
            timed_out=False,
            unsupported=False,
            error_code=result.error_code,
            submit_code=result.submit_code,
            late_callback_count=0,
            account_fingerprint_sha256=evidence_payload["account_fingerprint_sha256"],
            broker_id_sha256=evidence_payload["broker_id_sha256"],
            investor_id_sha256=evidence_payload["investor_id_sha256"],
            connection_generation=result.connection_generation,
            trading_day=source.trading_day,
            request_filter_names=("BrokerID", "InvestorID"),
            request_filters_sha256=request_filters_sha256,
            terminal_callback_records_sha256=source.records_sha256,
            terminal_callback_history_sha256=callback_history_sha256,
            record_count=1,
            confirmed_date=confirmed_date,
            started_at_utc=source.started_at_utc,
            completed_at_utc=source.completed_at_utc,
            expires_at_utc=source.trusted_expires_at_utc,
            expires_at_monotonic=source.trusted_expires_monotonic,
            _evidence_sha256=_canonical_digest(evidence_payload),
        )
        latest_scope = _scope_for_client(self._client)
        if not _same_scope(initial_scope, latest_scope):
            raise CtpNativeQueryCertificateError("settlement_query_session_changed")
        finalized_result = get_current_result(result.request_id)
        if type(finalized_result) is not QueryResult:
            raise CtpNativeQueryCertificateError("settlement_query_current_result_mismatch")
        finalized_source = self._require_exact_source(
            finalized_result,
            latest_scope,
            now_utc=datetime.now(timezone.utc),
            now_monotonic=time.monotonic(),
        )
        if not self._same_source(source, finalized_source):
            raise CtpNativeQueryCertificateError("settlement_query_current_result_mismatch")
        if (
            datetime.now(timezone.utc) >= evidence.expires_at_utc
            or time.monotonic() >= evidence.expires_at_monotonic
        ):
            raise CtpNativeQueryCertificateError("query_expired_before_certificate")
        object.__setattr__(evidence, "_seal", _SETTLEMENT_EVIDENCE_SEAL)
        return evidence


class CtpNativeQueryCertificateBuilder:
    """Verify and summarize one same-client sequence of seven native reads.

    Construct this immediately before beginning the query sequence.  Call
    :meth:`add` immediately after each query returns, then call :meth:`finish`
    after all seven required request types have been added.
    """

    def __init__(
        self,
        client: Any,
        *,
        instrument_id: str,
        exchange_id: str,
        hedge_flag: str,
    ) -> None:
        for name, value in (
            ("instrument_id", instrument_id),
            ("exchange_id", exchange_id),
            ("hedge_flag", hedge_flag),
        ):
            if type(value) is not str or not value or value != value.strip():
                raise CtpNativeQueryCertificateError(f"query_{name}_invalid")
        self._client = client
        self._instrument_id = instrument_id
        self._exchange_id = exchange_id
        self._hedge_flag = hedge_flag
        self._initial_scope = _scope_for_client(client)
        self._queries: dict[str, _QueryDigest] = {}
        self._request_ids: set[int] = set()
        self._finished = False

    def add(self, result: QueryResult[Any]) -> None:
        """Verify one result while its issuer-bound TTL is still current."""

        if self._finished:
            raise CtpNativeQueryCertificateError("query_certificate_already_finished")
        if type(result) is not QueryResult:
            raise CtpNativeQueryCertificateError("query_result_type_invalid")
        _query_result_shape(result)
        request_type = result.request_type
        if request_type in self._queries:
            raise CtpNativeQueryCertificateError("query_type_duplicate")
        if result.request_id in self._request_ids:
            raise CtpNativeQueryCertificateError("query_request_id_duplicate")
        if not result.complete:
            raise CtpNativeQueryCertificateError("query_incomplete")
        if not result.is_last_seen:
            raise CtpNativeQueryCertificateError("query_not_terminal")
        if result.timed_out:
            raise CtpNativeQueryCertificateError("query_timed_out")
        if result.unsupported:
            raise CtpNativeQueryCertificateError("query_unsupported")
        if result.error_code not in (None, 0):
            raise CtpNativeQueryCertificateError("query_error")
        if result.error_message:
            raise CtpNativeQueryCertificateError("query_error_message_present")
        if result.submit_code not in (None, 0):
            raise CtpNativeQueryCertificateError("query_submit_failed")
        if result.late_callback_count != 0:
            raise CtpNativeQueryCertificateError("query_late_callback")

        scope = _scope_for_client(self._client)
        if not _same_scope(self._initial_scope, scope):
            raise CtpNativeQueryCertificateError("query_session_changed")
        if (
            result.account_fingerprint != scope.account_fingerprint
            or result.connection_generation != scope.connection_generation
        ):
            raise CtpNativeQueryCertificateError("query_session_mismatch")
        now_utc = datetime.now(timezone.utc)
        now_monotonic = time.monotonic()
        source = _source_for_result(
            result,
            scope,
            now_utc=now_utc,
            now_monotonic=now_monotonic,
        )
        if source.started_monotonic < self._initial_scope.captured_monotonic:
            raise CtpNativeQueryCertificateError("query_started_before_certificate")
        get_current_result = getattr(self._client, "get_query_result", None)
        if not callable(get_current_result):
            raise CtpNativeQueryCertificateError("query_current_result_unavailable")
        try:
            current_result = get_current_result(result.request_id)
        except Exception as exc:
            raise CtpNativeQueryCertificateError("query_current_result_unavailable") from exc
        if (
            type(current_result) is not QueryResult
            or current_result.request_type != result.request_type
            or current_result.request_id != result.request_id
        ):
            raise CtpNativeQueryCertificateError("query_current_result_mismatch")
        current_source = current_result.query_source
        if (
            type(current_source) is not _QuerySource
            or current_source.issuer is not source.issuer
            or current_source.request_type != source.request_type
            or current_source.request_id != source.request_id
            or current_source.records_sha256 != source.records_sha256
            or current_source.request_filters != source.request_filters
            or current_source.explicit_request_filters != source.explicit_request_filters
        ):
            raise CtpNativeQueryCertificateError("query_current_result_mismatch")
        if current_result.late_callback_count != 0:
            raise CtpNativeQueryCertificateError("query_late_callback")
        filters = _validate_bound_filters(
            result,
            scope,
            self._instrument_id,
            self._exchange_id,
            self._hedge_flag,
        )
        target_instrument_match_count = _validate_returned_rows(
            result,
            scope,
            self._instrument_id,
            self._exchange_id,
            self._hedge_flag,
        )
        self._queries[request_type] = _QueryDigest(
            request_type=request_type,
            request_id=result.request_id,
            record_count=len(result.records),
            records_sha256=source.records_sha256,
            request_filters_sha256=_canonical_digest(
                {
                    "filters": list(filters),
                    "explicit_filters": list(source.explicit_request_filters),
                }
            ),
            request_filter_names=tuple(name for name, _value in filters),
            explicit_request_filter_names=source.explicit_request_filters,
            instrument_row_scope=("same_exchange" if request_type == "instruments" else None),
            instrument_filter_application=("unverified" if request_type == "instruments" else None),
            target_instrument_match_count=target_instrument_match_count,
            source_provenance_validated=True,
            complete=result.complete,
            is_last_seen=result.is_last_seen,
            timed_out=result.timed_out,
            unsupported=result.unsupported,
            error_code=result.error_code,
            error_message_present=bool(result.error_message),
            submit_code=result.submit_code,
            late_callback_count=result.late_callback_count,
            started_at_utc=source.started_at_utc,
            completed_at_utc=source.completed_at_utc,
            expires_at_utc=source.trusted_expires_at_utc,
            expires_at_monotonic=source.trusted_expires_monotonic,
        )
        self._request_ids.add(result.request_id)

    def finish(self) -> CtpNativeQueryCertificate:
        """Return a digest-only certificate after final same-session readback."""

        if self._finished:
            raise CtpNativeQueryCertificateError("query_certificate_already_finished")
        missing = set(_REQUIRED_QUERY_TYPES) - set(self._queries)
        if missing:
            raise CtpNativeQueryCertificateError("query_bundle_incomplete")
        final_scope = _scope_for_client(self._client)
        if not _same_scope(self._initial_scope, final_scope):
            raise CtpNativeQueryCertificateError("query_session_changed")
        ordered_queries = tuple(self._queries[name] for name in _REQUIRED_QUERY_TYPES)
        get_current_result = getattr(self._client, "get_query_result", None)
        if not callable(get_current_result):
            raise CtpNativeQueryCertificateError("query_current_result_unavailable")
        # Earlier queries can receive a late callback while later queries are
        # still running.  Their result must remain unchanged and inside the
        # issuer TTL through certificate finalization; otherwise the complete
        # bundle would combine expired evidence with fresh evidence.
        for query in ordered_queries:
            try:
                current_result = get_current_result(query.request_id)
            except Exception as exc:
                raise CtpNativeQueryCertificateError("query_current_result_unavailable") from exc
            if type(current_result) is not QueryResult:
                raise CtpNativeQueryCertificateError("query_current_result_mismatch")
            _query_result_shape(current_result)
            if current_result.late_callback_count != 0:
                raise CtpNativeQueryCertificateError("query_late_callback")
            if (
                current_result.request_type != query.request_type
                or current_result.request_id != query.request_id
                or current_result.account_fingerprint != final_scope.account_fingerprint
                or current_result.connection_generation != final_scope.connection_generation
                or current_result.complete is not True
                or current_result.is_last_seen is not True
                or current_result.timed_out is not False
                or current_result.unsupported is not False
                or current_result.error_code not in (None, 0)
                or current_result.error_message
                or current_result.submit_code not in (None, 0)
            ):
                raise CtpNativeQueryCertificateError("query_current_result_mismatch")
            source = current_result.query_source
            if (
                type(source) is not _QuerySource
                or source._seal is not _QUERY_SOURCE_SEAL
                or source.issuer is not final_scope.issuer
                or source.request_type != query.request_type
                or source.request_id != query.request_id
                or source.account_fingerprint != final_scope.account_fingerprint
                or source.connection_generation != final_scope.connection_generation
                or source.trading_day != final_scope.trading_day
                or source.broker_id != final_scope.broker_id
                or source.investor_id != final_scope.investor_id
                or source.started_at_utc != query.started_at_utc
                or source.completed_at_utc != query.completed_at_utc
                or source.trusted_expires_at_utc != query.expires_at_utc
                or source.trusted_expires_monotonic != query.expires_at_monotonic
                or source.records_sha256 != query.records_sha256
            ):
                raise CtpNativeQueryCertificateError("query_current_result_mismatch")
            try:
                filters_sha256 = _canonical_digest(
                    {
                        "filters": list(source.request_filters),
                        "explicit_filters": list(source.explicit_request_filters),
                    }
                )
                records_sha256 = _query_records_digest(current_result.records)
            except (TypeError, ValueError) as exc:
                raise CtpNativeQueryCertificateError("query_current_result_mismatch") from exc
            if (
                filters_sha256 != query.request_filters_sha256
                or records_sha256 != query.records_sha256
                or len(current_result.records) != query.record_count
            ):
                raise CtpNativeQueryCertificateError("query_current_result_mismatch")
            _source_for_result(
                current_result,
                final_scope,
                now_utc=datetime.now(timezone.utc),
                now_monotonic=time.monotonic(),
                expiry_error_code="query_expired_before_certificate",
            )
        payload = {
            "schema": _CERTIFICATE_SCHEMA,
            "complete": True,
            "atomic_snapshot": False,
            "execution_authorized": False,
            "account_fingerprint_sha256": _sha256_text(final_scope.account_fingerprint),
            "broker_id_sha256": _sha256_text(final_scope.broker_id),
            "investor_id_sha256": _sha256_text(final_scope.investor_id),
            "instrument_id_sha256": _sha256_text(self._instrument_id),
            "exchange_id_sha256": _sha256_text(self._exchange_id),
            "hedge_flag_sha256": _sha256_text(self._hedge_flag),
            "connection_generation": final_scope.connection_generation,
            "trading_day": final_scope.trading_day,
            "queries": [query.as_dict() for query in ordered_queries],
        }
        certificate = CtpNativeQueryCertificate(
            account_fingerprint_sha256=payload["account_fingerprint_sha256"],
            broker_id_sha256=payload["broker_id_sha256"],
            investor_id_sha256=payload["investor_id_sha256"],
            instrument_id_sha256=payload["instrument_id_sha256"],
            exchange_id_sha256=payload["exchange_id_sha256"],
            hedge_flag_sha256=payload["hedge_flag_sha256"],
            connection_generation=final_scope.connection_generation,
            trading_day=final_scope.trading_day,
            queries=ordered_queries,
            _certificate_sha256=_canonical_digest(payload),
        )
        # Recheck after the readback and digest work as well.  This keeps the
        # certificate's complete claim bounded by the earliest issuer expiry,
        # even if validation itself took long enough to cross that deadline.
        latest_scope = _scope_for_client(self._client)
        if not _same_scope(final_scope, latest_scope):
            raise CtpNativeQueryCertificateError("query_session_changed")
        finalized_at_utc = datetime.now(timezone.utc)
        finalized_at_monotonic = time.monotonic()
        if any(
            finalized_at_utc >= query.expires_at_utc
            or finalized_at_monotonic >= query.expires_at_monotonic
            for query in ordered_queries
        ):
            raise CtpNativeQueryCertificateError("query_expired_before_certificate")
        object.__setattr__(certificate, "_seal", _CERTIFICATE_SEAL)
        self._finished = True
        return certificate


__all__ = [
    "CtpNativeQueryCertificate",
    "CtpSettlementConfirmationEvidence",
    "CtpSettlementConfirmationEvidenceBuilder",
    "CtpNativeQueryCertificateBuilder",
    "CtpNativeQueryCertificateError",
]
