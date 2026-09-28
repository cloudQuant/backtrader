"""Offline shape tests for joining settlement rows to session TradingDay."""

from __future__ import annotations

from dataclasses import replace

import pytest

from backtrader_runtime.ctp_simnow_settlement_callback_candidate import (
    CtpSimNowSettlementCallbackCandidateError,
    CtpSimNowSettlementCallbackEventCandidate,
    CtpSimNowSettlementConfirmationRecordCandidate,
    CtpSimNowSettlementInfoRecordCandidate,
    CtpSimNowSettlementQueryCandidate,
    CtpSimNowSettlementScopeCandidate,
    join_ctp_simnow_settlement_queries_candidate,
)


BROKER = "9999"
INVESTOR = "offline-callback-contract"
ACCOUNT_ID = "offline-account-17"
ACCOUNT_FINGERPRINT = "0123456789abcdef"
TRADING_DAY = "20260924"
CONFIRM_DATE = "20260923"
GENERATION = 3
INFO_REQUEST_ID = 73
CONFIRM_REQUEST_ID = 74
SETTLEMENT_ID = 812


def _scope(**overrides: object) -> CtpSimNowSettlementScopeCandidate:
    fields = {
        "broker_id": BROKER,
        "investor_id": INVESTOR,
        "account_id": ACCOUNT_ID,
        "account_fingerprint": ACCOUNT_FINGERPRINT,
        "trading_day": TRADING_DAY,
        "connection_generation": GENERATION,
    }
    fields.update(overrides)
    return CtpSimNowSettlementScopeCandidate(**fields)


def _info_row(**overrides: object) -> CtpSimNowSettlementInfoRecordCandidate:
    fields = {
        "broker_id": BROKER,
        "investor_id": INVESTOR,
        "account_id": ACCOUNT_ID,
        "trading_day": TRADING_DAY,
        "settlement_id": SETTLEMENT_ID,
    }
    fields.update(overrides)
    return CtpSimNowSettlementInfoRecordCandidate(**fields)


def _confirmation_row(
    **overrides: object,
) -> CtpSimNowSettlementConfirmationRecordCandidate:
    fields = {
        "broker_id": BROKER,
        "investor_id": INVESTOR,
        "account_id": ACCOUNT_ID,
        "confirm_date": CONFIRM_DATE,
        "settlement_id": SETTLEMENT_ID,
    }
    fields.update(overrides)
    return CtpSimNowSettlementConfirmationRecordCandidate(**fields)


def _event(
    query_kind: str,
    request_id: int,
    record: object = None,
    **overrides: object,
) -> CtpSimNowSettlementCallbackEventCandidate:
    callback_name = (
        "OnRspQrySettlementInfo"
        if query_kind == "settlement_info"
        else "OnRspQrySettlementInfoConfirm"
    )
    fields = {
        "callback_name": callback_name,
        "request_id": request_id,
        "connection_generation": GENERATION,
        "account_fingerprint": ACCOUNT_FINGERPRINT,
        "session_trading_day": TRADING_DAY,
        "error_id": 0,
        "is_last": True,
        "record": record,
    }
    fields.update(overrides)
    return CtpSimNowSettlementCallbackEventCandidate(**fields)


def _query(
    query_kind: str,
    request_id: int,
    records: tuple[object, ...],
    *,
    terminal_without_record: bool = False,
    **overrides: object,
) -> CtpSimNowSettlementQueryCandidate:
    callbacks = tuple(
        _event(
            query_kind,
            request_id,
            record,
            is_last=not terminal_without_record and index == len(records) - 1,
        )
        for index, record in enumerate(records)
    )
    if terminal_without_record:
        callbacks += (_event(query_kind, request_id, is_last=True, record=None),)
    fields = {
        "query_kind": query_kind,
        "request_id": request_id,
        "connection_generation": GENERATION,
        "account_fingerprint": ACCOUNT_FINGERPRINT,
        "session_trading_day": TRADING_DAY,
        "submit_code": 0,
        "complete": True,
        "timed_out": False,
        "unsupported": False,
        "late_callback_count": 0,
        "callbacks": callbacks,
    }
    fields.update(overrides)
    return CtpSimNowSettlementQueryCandidate(**fields)


def _valid_pair(
    *,
    info_rows: tuple[object, ...] | None = None,
    confirmation_rows: tuple[object, ...] | None = None,
) -> tuple[CtpSimNowSettlementQueryCandidate, CtpSimNowSettlementQueryCandidate]:
    info = _query(
        "settlement_info",
        INFO_REQUEST_ID,
        info_rows or (_info_row(),),
        terminal_without_record=True,
    )
    confirmation = _query(
        "settlement_confirmation",
        CONFIRM_REQUEST_ID,
        confirmation_rows or (_confirmation_row(),),
    )
    return info, confirmation


def test_join_uses_settlement_id_and_session_trading_day_not_confirm_date() -> None:
    info, confirmation = _valid_pair()

    result = join_ctp_simnow_settlement_queries_candidate(_scope(), info, confirmation)

    assert result.shape_complete is True
    assert result.info_request_id == INFO_REQUEST_ID
    assert result.confirmation_request_id == CONFIRM_REQUEST_ID
    assert result.connection_generation == GENERATION
    assert result.trading_day == TRADING_DAY
    assert result.confirmation_date == CONFIRM_DATE
    assert result.settlement_id == SETTLEMENT_ID
    assert result.info_callback_count == 2
    assert result.confirmation_callback_count == 1
    assert result.info_record_count == 1
    assert result.confirmation_record_count == 1
    assert result.provider_source_trusted is False
    assert result.settlement_readiness_established is False
    assert result.execution_authorized is False


def test_confirm_date_match_cannot_replace_settlement_id_join() -> None:
    info, _confirmation = _valid_pair()
    confirmation = _query(
        "settlement_confirmation",
        CONFIRM_REQUEST_ID,
        (_confirmation_row(confirm_date=TRADING_DAY, settlement_id=SETTLEMENT_ID + 1),),
    )

    with pytest.raises(CtpSimNowSettlementCallbackCandidateError) as raised:
        join_ctp_simnow_settlement_queries_candidate(_scope(), info, confirmation)

    assert raised.value.reason == "settlement_confirmation_record_join_missing_or_ambiguous"


@pytest.mark.parametrize(
    "bad_info_row",
    (
        _info_row(trading_day=None),
        _info_row(trading_day="20260923"),
        _info_row(settlement_id=True),
        _info_row(account_id="other-account"),
        _info_row(broker_id="other-broker"),
        _info_row(investor_id="other-investor"),
    ),
)
def test_settlement_info_requires_native_scope_and_session_day(
    bad_info_row: CtpSimNowSettlementInfoRecordCandidate,
) -> None:
    info, confirmation = _valid_pair(info_rows=(bad_info_row,))

    with pytest.raises(CtpSimNowSettlementCallbackCandidateError) as raised:
        join_ctp_simnow_settlement_queries_candidate(_scope(), info, confirmation)

    assert raised.value.reason == "settlement_info_record_scope_incomplete_or_mismatched"


@pytest.mark.parametrize(
    "bad_confirmation_row",
    (
        _confirmation_row(confirm_date=None),
        _confirmation_row(confirm_date="20260230"),
        _confirmation_row(settlement_id=True),
        _confirmation_row(account_id="other-account"),
        _confirmation_row(broker_id="other-broker"),
        _confirmation_row(investor_id="other-investor"),
    ),
)
def test_confirmation_requires_native_account_settlement_id_and_confirm_date(
    bad_confirmation_row: CtpSimNowSettlementConfirmationRecordCandidate,
) -> None:
    info, confirmation = _valid_pair(confirmation_rows=(bad_confirmation_row,))

    with pytest.raises(CtpSimNowSettlementCallbackCandidateError) as raised:
        join_ctp_simnow_settlement_queries_candidate(_scope(), info, confirmation)

    assert raised.value.reason == "settlement_confirmation_record_scope_incomplete_or_mismatched"


def test_join_rejects_ambiguous_current_day_settlement_ids_and_duplicate_confirmation() -> None:
    info = _query(
        "settlement_info",
        INFO_REQUEST_ID,
        (_info_row(), _info_row(settlement_id=SETTLEMENT_ID + 1)),
    )
    confirmation = _query(
        "settlement_confirmation",
        CONFIRM_REQUEST_ID,
        (_confirmation_row(),),
    )
    with pytest.raises(CtpSimNowSettlementCallbackCandidateError) as raised_info:
        join_ctp_simnow_settlement_queries_candidate(_scope(), info, confirmation)
    assert raised_info.value.reason == "settlement_info_record_id_ambiguous"

    info, _confirmation = _valid_pair()
    confirmation = _query(
        "settlement_confirmation",
        CONFIRM_REQUEST_ID,
        (_confirmation_row(), _confirmation_row()),
    )
    with pytest.raises(CtpSimNowSettlementCallbackCandidateError) as raised_confirmation:
        join_ctp_simnow_settlement_queries_candidate(_scope(), info, confirmation)
    assert (
        raised_confirmation.value.reason
        == "settlement_confirmation_record_join_missing_or_ambiguous"
    )


@pytest.mark.parametrize(
    "query_field,value",
    (
        ("request_id", True),
        ("connection_generation", GENERATION + 1),
        ("account_fingerprint", "fedcba9876543210"),
        ("session_trading_day", "20260925"),
        ("submit_code", False),
        ("complete", 1),
        ("timed_out", 0),
        ("unsupported", 0),
        ("late_callback_count", True),
        ("query_kind", "settlement_confirmation"),
    ),
)
def test_each_query_requires_exact_type_and_session_provenance(
    query_field: str,
    value: object,
) -> None:
    info, confirmation = _valid_pair()
    bad_info = replace(info, **{query_field: value})

    with pytest.raises(CtpSimNowSettlementCallbackCandidateError):
        join_ctp_simnow_settlement_queries_candidate(_scope(), bad_info, confirmation)


def test_callback_request_session_terminal_and_error_facts_must_match() -> None:
    info, confirmation = _valid_pair()
    event = info.callbacks[0]
    bad_events = (
        replace(event, request_id=INFO_REQUEST_ID + 1),
        replace(event, connection_generation=GENERATION + 1),
        replace(event, account_fingerprint="fedcba9876543210"),
        replace(event, session_trading_day="20260925"),
        replace(event, callback_name="OnRspQrySettlementInfoConfirm"),
        replace(event, error_id=False),
        replace(event, is_last=1),
    )

    for bad_event in bad_events:
        bad_info = replace(info, callbacks=(bad_event,))
        with pytest.raises(CtpSimNowSettlementCallbackCandidateError):
            join_ctp_simnow_settlement_queries_candidate(_scope(), bad_info, confirmation)

    extra_after_terminal = _query(
        "settlement_info", INFO_REQUEST_ID, (_info_row(),), terminal_without_record=True
    ).callbacks + (_event("settlement_info", INFO_REQUEST_ID, _info_row()),)
    with pytest.raises(CtpSimNowSettlementCallbackCandidateError):
        join_ctp_simnow_settlement_queries_candidate(
            _scope(),
            replace(info, callbacks=extra_after_terminal),
            confirmation,
        )


def test_query_request_ids_must_be_distinct() -> None:
    info, confirmation = _valid_pair()
    confirmation = replace(confirmation, request_id=INFO_REQUEST_ID)
    confirmation_event = replace(confirmation.callbacks[0], request_id=INFO_REQUEST_ID)
    confirmation = replace(confirmation, callbacks=(confirmation_event,))

    with pytest.raises(CtpSimNowSettlementCallbackCandidateError) as raised:
        join_ctp_simnow_settlement_queries_candidate(_scope(), info, confirmation)

    assert raised.value.reason == "settlement_query_request_ids_not_distinct"
