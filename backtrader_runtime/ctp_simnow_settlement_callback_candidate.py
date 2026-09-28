"""Offline candidate contract joining SimNow settlement query callback shapes.

This module is deliberately unregistered and performs no SDK import, provider
query, session operation, or write. It validates normalized facts from both
native row types: SettlementInfo carries TradingDay and SettlementID, while
SettlementInfoConfirm carries ConfirmDate and SettlementID but has no
TradingDay field. The join uses the exact account and SettlementID, with the
SettlementInfo TradingDay bound to the expected session scope.

A successful result means only that these supplied facts are internally
complete and consistently scoped. The DTO inputs can be caller-created, so
the result never claims provider provenance, settlement readiness, or write
authority.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any


_ACCOUNT_FINGERPRINT_RE = re.compile(r"^[0-9a-f]{16}$", re.ASCII)
_QUERY_KINDS = frozenset(("settlement_info", "settlement_confirmation"))
_CALLBACKS = {
    "settlement_info": "OnRspQrySettlementInfo",
    "settlement_confirmation": "OnRspQrySettlementInfoConfirm",
}


class CtpSimNowSettlementCallbackCandidateError(ValueError):
    """Redacted shape failure from the unregistered offline candidate."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class CtpSimNowSettlementScopeCandidate:
    """Expected TD scope copied from a separately checked session snapshot."""

    broker_id: Any
    investor_id: Any
    account_id: Any
    account_fingerprint: Any
    trading_day: Any
    connection_generation: Any


@dataclass(frozen=True)
class CtpSimNowSettlementInfoRecordCandidate:
    """Relevant fields from native ``CThostFtdcSettlementInfoField``."""

    broker_id: Any
    investor_id: Any
    account_id: Any
    trading_day: Any
    settlement_id: Any


@dataclass(frozen=True)
class CtpSimNowSettlementConfirmationRecordCandidate:
    """Relevant fields from native ``CThostFtdcSettlementInfoConfirmField``."""

    broker_id: Any
    investor_id: Any
    account_id: Any
    confirm_date: Any
    settlement_id: Any


@dataclass(frozen=True)
class CtpSimNowSettlementCallbackEventCandidate:
    """Normalized callback identity retained at the provider callback boundary."""

    callback_name: Any
    request_id: Any
    connection_generation: Any
    account_fingerprint: Any
    session_trading_day: Any
    error_id: Any
    is_last: Any
    record: Any = None


@dataclass(frozen=True)
class CtpSimNowSettlementQueryCandidate:
    """One typed native query attempt and its ordered callback events."""

    query_kind: Any
    request_id: Any
    connection_generation: Any
    account_fingerprint: Any
    session_trading_day: Any
    submit_code: Any
    complete: Any
    timed_out: Any
    unsupported: Any
    late_callback_count: Any
    callbacks: Any


@dataclass(frozen=True)
class CtpSimNowSettlementJoinShapeObservation:
    """Value-free completeness result with no trust or authority."""

    info_request_id: int
    confirmation_request_id: int
    connection_generation: int
    trading_day: str
    settlement_id: int
    confirmation_date: str
    info_callback_count: int
    confirmation_callback_count: int
    info_record_count: int
    confirmation_record_count: int
    shape_complete: bool = True
    provider_source_trusted: bool = False
    settlement_readiness_established: bool = False
    execution_authorized: bool = False


def _reject(reason: str) -> None:
    raise CtpSimNowSettlementCallbackCandidateError(reason)


def _valid_day(value: Any) -> bool:
    if type(value) is not str or len(value) != 8 or not value.isascii() or not value.isdigit():
        return False
    try:
        parsed = time.strptime(value, "%Y%m%d")
    except (OverflowError, ValueError):
        return False
    return time.strftime("%Y%m%d", parsed) == value


def _valid_identity_text(value: Any) -> bool:
    return type(value) is str and bool(value) and value == value.strip()


def _validate_scope(scope: Any) -> CtpSimNowSettlementScopeCandidate:
    if type(scope) is not CtpSimNowSettlementScopeCandidate:
        _reject("settlement_scope_candidate_type_invalid")
    if (
        not _valid_identity_text(scope.broker_id)
        or not _valid_identity_text(scope.investor_id)
        or not _valid_identity_text(scope.account_id)
        or type(scope.account_fingerprint) is not str
        or not _ACCOUNT_FINGERPRINT_RE.fullmatch(scope.account_fingerprint)
        or not _valid_day(scope.trading_day)
        or type(scope.connection_generation) is not int
        or scope.connection_generation <= 0
    ):
        _reject("settlement_scope_candidate_invalid")
    return scope


def _validate_query(
    scope: CtpSimNowSettlementScopeCandidate,
    query: Any,
    *,
    query_kind: str,
) -> tuple[Any, ...]:
    if query_kind not in _QUERY_KINDS:
        _reject("settlement_query_kind_unsupported")
    if type(query) is not CtpSimNowSettlementQueryCandidate:
        _reject("settlement_query_candidate_type_invalid")
    callback_name = _CALLBACKS[query_kind]
    if (
        type(query.query_kind) is not str
        or query.query_kind != query_kind
        or type(query.request_id) is not int
        or query.request_id <= 0
        or type(query.connection_generation) is not int
        or query.connection_generation != scope.connection_generation
        or type(query.account_fingerprint) is not str
        or query.account_fingerprint != scope.account_fingerprint
        or type(query.session_trading_day) is not str
        or query.session_trading_day != scope.trading_day
        or type(query.submit_code) is not int
        or query.submit_code != 0
        or type(query.complete) is not bool
        or query.complete is not True
        or type(query.timed_out) is not bool
        or query.timed_out is not False
        or type(query.unsupported) is not bool
        or query.unsupported is not False
        or type(query.late_callback_count) is not int
        or query.late_callback_count != 0
        or type(query.callbacks) is not tuple
        or not query.callbacks
    ):
        _reject("settlement_query_candidate_scope_or_submit_invalid")

    terminal_indexes: list[int] = []
    records: list[Any] = []
    for index, event in enumerate(query.callbacks):
        if type(event) is not CtpSimNowSettlementCallbackEventCandidate:
            _reject("settlement_callback_candidate_type_invalid")
        if (
            type(event.callback_name) is not str
            or event.callback_name != callback_name
            or type(event.request_id) is not int
            or event.request_id != query.request_id
            or type(event.connection_generation) is not int
            or event.connection_generation != scope.connection_generation
            or type(event.account_fingerprint) is not str
            or event.account_fingerprint != scope.account_fingerprint
            or type(event.session_trading_day) is not str
            or event.session_trading_day != scope.trading_day
            or type(event.error_id) is not int
            or event.error_id != 0
            or type(event.is_last) is not bool
        ):
            _reject("settlement_callback_candidate_scope_or_status_invalid")
        if event.is_last:
            terminal_indexes.append(index)
        if event.record is not None:
            expected_type = (
                CtpSimNowSettlementInfoRecordCandidate
                if query_kind == "settlement_info"
                else CtpSimNowSettlementConfirmationRecordCandidate
            )
            if type(event.record) is not expected_type:
                _reject("settlement_record_candidate_type_invalid")
            records.append(event.record)
    if terminal_indexes != [len(query.callbacks) - 1] or not records:
        _reject("settlement_callback_candidate_terminal_or_record_count_invalid")
    return tuple(records)


def join_ctp_simnow_settlement_queries_candidate(
    scope: CtpSimNowSettlementScopeCandidate,
    settlement_info_query: CtpSimNowSettlementQueryCandidate,
    confirmation_query: CtpSimNowSettlementQueryCandidate,
) -> CtpSimNowSettlementJoinShapeObservation:
    """Validate a same-session pair and join on account plus SettlementID.

    ``ConfirmDate`` is validated as its own row field and is never compared to
    or substituted for the session ``TradingDay``. The matching SettlementID
    must occur in exactly one account-scoped confirmation row and in all
    current-day SettlementInfo rows.
    """

    scope = _validate_scope(scope)
    info_rows = _validate_query(scope, settlement_info_query, query_kind="settlement_info")
    confirmation_rows = _validate_query(
        scope,
        confirmation_query,
        query_kind="settlement_confirmation",
    )
    if settlement_info_query.request_id == confirmation_query.request_id:
        _reject("settlement_query_request_ids_not_distinct")

    settlement_ids: set[int] = set()
    for row in info_rows:
        if (
            type(row.broker_id) is not str
            or row.broker_id != scope.broker_id
            or type(row.investor_id) is not str
            or row.investor_id != scope.investor_id
            or type(row.account_id) is not str
            or row.account_id != scope.account_id
            or type(row.trading_day) is not str
            or row.trading_day != scope.trading_day
            or not _valid_day(row.trading_day)
            or type(row.settlement_id) is not int
            or row.settlement_id <= 0
        ):
            _reject("settlement_info_record_scope_incomplete_or_mismatched")
        settlement_ids.add(row.settlement_id)
    if len(settlement_ids) != 1:
        _reject("settlement_info_record_id_ambiguous")
    settlement_id = next(iter(settlement_ids))

    matched_confirmations: list[CtpSimNowSettlementConfirmationRecordCandidate] = []
    for row in confirmation_rows:
        if (
            type(row.broker_id) is not str
            or row.broker_id != scope.broker_id
            or type(row.investor_id) is not str
            or row.investor_id != scope.investor_id
            or type(row.account_id) is not str
            or row.account_id != scope.account_id
            or type(row.settlement_id) is not int
            or row.settlement_id <= 0
            or not _valid_day(row.confirm_date)
        ):
            _reject("settlement_confirmation_record_scope_incomplete_or_mismatched")
        if row.settlement_id == settlement_id:
            matched_confirmations.append(row)
    if len(matched_confirmations) != 1:
        _reject("settlement_confirmation_record_join_missing_or_ambiguous")

    return CtpSimNowSettlementJoinShapeObservation(
        info_request_id=settlement_info_query.request_id,
        confirmation_request_id=confirmation_query.request_id,
        connection_generation=scope.connection_generation,
        trading_day=scope.trading_day,
        settlement_id=settlement_id,
        confirmation_date=matched_confirmations[0].confirm_date,
        info_callback_count=len(settlement_info_query.callbacks),
        confirmation_callback_count=len(confirmation_query.callbacks),
        info_record_count=len(info_rows),
        confirmation_record_count=len(confirmation_rows),
    )


__all__ = [
    "CtpSimNowSettlementCallbackCandidateError",
    "CtpSimNowSettlementCallbackEventCandidate",
    "CtpSimNowSettlementConfirmationRecordCandidate",
    "CtpSimNowSettlementInfoRecordCandidate",
    "CtpSimNowSettlementJoinShapeObservation",
    "CtpSimNowSettlementQueryCandidate",
    "CtpSimNowSettlementScopeCandidate",
    "join_ctp_simnow_settlement_queries_candidate",
]
