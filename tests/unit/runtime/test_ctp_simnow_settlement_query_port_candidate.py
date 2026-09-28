"""Offline typed-port contract tests; no SDK or native call is used."""

from __future__ import annotations

from dataclasses import replace

import pytest

from backtrader_runtime.ctp_simnow_settlement_callback_candidate import (
    CtpSimNowSettlementCallbackEventCandidate,
    CtpSimNowSettlementConfirmationRecordCandidate,
    CtpSimNowSettlementInfoRecordCandidate,
    CtpSimNowSettlementQueryCandidate,
    CtpSimNowSettlementScopeCandidate,
)
from backtrader_runtime.ctp_simnow_settlement_query_port_candidate import (
    CtpSimNowSettlementQueryPairPortObservationCandidate,
    CtpSimNowSettlementQueryPortAdapterCandidate,
    CtpSimNowSettlementQueryPortCandidateError,
    CtpSimNowSettlementQueryPortCloseCandidate,
    validate_ctp_simnow_settlement_query_port_candidate,
)


BROKER = "9999"
INVESTOR = "offline-port-contract"
ACCOUNT_ID = "offline-account-22"
ACCOUNT_FINGERPRINT = "0123456789abcdef"
TRADING_DAY = "20260924"
CONFIRM_DATE = "20260923"
GENERATION = 5
INFO_REQUEST_ID = 81
CONFIRM_REQUEST_ID = 82
SETTLEMENT_ID = 913


def _scope() -> CtpSimNowSettlementScopeCandidate:
    return CtpSimNowSettlementScopeCandidate(
        broker_id=BROKER,
        investor_id=INVESTOR,
        account_id=ACCOUNT_ID,
        account_fingerprint=ACCOUNT_FINGERPRINT,
        trading_day=TRADING_DAY,
        connection_generation=GENERATION,
    )


def _query(query_kind: str, request_id: int) -> CtpSimNowSettlementQueryCandidate:
    if query_kind == "settlement_info":
        record = CtpSimNowSettlementInfoRecordCandidate(
            broker_id=BROKER,
            investor_id=INVESTOR,
            account_id=ACCOUNT_ID,
            trading_day=TRADING_DAY,
            settlement_id=SETTLEMENT_ID,
        )
        callback_name = "OnRspQrySettlementInfo"
    else:
        # The native confirmation row intentionally has no TradingDay field.
        record = CtpSimNowSettlementConfirmationRecordCandidate(
            broker_id=BROKER,
            investor_id=INVESTOR,
            account_id=ACCOUNT_ID,
            confirm_date=CONFIRM_DATE,
            settlement_id=SETTLEMENT_ID,
        )
        callback_name = "OnRspQrySettlementInfoConfirm"
    callback = CtpSimNowSettlementCallbackEventCandidate(
        callback_name=callback_name,
        request_id=request_id,
        connection_generation=GENERATION,
        account_fingerprint=ACCOUNT_FINGERPRINT,
        session_trading_day=TRADING_DAY,
        error_id=0,
        is_last=True,
        record=record,
    )
    return CtpSimNowSettlementQueryCandidate(
        query_kind=query_kind,
        request_id=request_id,
        connection_generation=GENERATION,
        account_fingerprint=ACCOUNT_FINGERPRINT,
        session_trading_day=TRADING_DAY,
        submit_code=0,
        complete=True,
        timed_out=False,
        unsupported=False,
        late_callback_count=0,
        callbacks=(callback,),
    )


def _close(**overrides: object) -> CtpSimNowSettlementQueryPortCloseCandidate:
    fields = {
        "connection_generation": GENERATION,
        "native_released": True,
        "join_required": True,
        "join_completed": True,
        "thread_alive": False,
        "timed_out": False,
        "callbacks_quiescent": True,
    }
    fields.update(overrides)
    return CtpSimNowSettlementQueryPortCloseCandidate(**fields)


class _FakeTypedPort:
    """Structural fake; methods return supplied data and perform no I/O."""

    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []
        self.info = _query("settlement_info", INFO_REQUEST_ID)
        self.confirmation = _query("settlement_confirmation", CONFIRM_REQUEST_ID)
        self.close = _close()

    def query_settlement_info_result(self, timeout: float = 5.0):
        self.calls.append(("query_settlement_info_result", timeout))
        return self.info

    def query_settlement_confirmation_result(self, timeout: float = 5.0):
        self.calls.append(("query_settlement_confirmation_result", timeout))
        return self.confirmation

    def get_query_result(self, request_id: int):
        self.calls.append(("get_query_result", request_id))
        return {
            INFO_REQUEST_ID: self.info,
            CONFIRM_REQUEST_ID: self.confirmation,
        }.get(request_id)

    def stop_and_wait(self, timeout: float = 2.0):
        self.calls.append(("stop_and_wait", timeout))
        return self.close


def _post_close_observation(
    port: _FakeTypedPort,
) -> CtpSimNowSettlementQueryPairPortObservationCandidate:
    first_info = port.query_settlement_info_result()
    first_confirmation = port.query_settlement_confirmation_result()
    close_receipt = port.stop_and_wait()
    info_after_close = port.get_query_result(first_info.request_id)
    confirmation_after_close = port.get_query_result(first_confirmation.request_id)
    refreshed = (
        info_after_close is not None
        and confirmation_after_close is not None
        and info_after_close.request_id == first_info.request_id
        and confirmation_after_close.request_id == first_confirmation.request_id
    )
    return CtpSimNowSettlementQueryPairPortObservationCandidate(
        settlement_info_result=info_after_close,
        settlement_confirmation_result=confirmation_after_close,
        close_receipt=close_receipt,
        results_refreshed_after_close=refreshed,
    )


def test_typed_pair_port_requires_two_post_close_request_results_and_safe_close() -> None:
    port = _FakeTypedPort()
    assert isinstance(port, CtpSimNowSettlementQueryPortAdapterCandidate)
    observation = _post_close_observation(port)
    calls_before_validation = tuple(port.calls)

    result = validate_ctp_simnow_settlement_query_port_candidate(
        port,
        _scope(),
        observation,
    )

    assert result.joined_query_shape.info_request_id == INFO_REQUEST_ID
    assert result.joined_query_shape.confirmation_request_id == CONFIRM_REQUEST_ID
    assert result.joined_query_shape.trading_day == TRADING_DAY
    assert result.joined_query_shape.confirmation_date == CONFIRM_DATE
    assert result.native_close_complete is True
    assert result.callbacks_quiescent is True
    assert result.provider_source_trusted is False
    assert result.settlement_readiness_established is False
    assert result.execution_authorized is False
    assert tuple(port.calls) == calls_before_validation


@pytest.mark.parametrize(
    "close_change",
    (
        {"connection_generation": GENERATION + 1},
        {"native_released": False},
        {"join_required": 1},
        {"join_completed": False},
        {"thread_alive": True},
        {"timed_out": True},
        {"callbacks_quiescent": False},
    ),
)
def test_port_pair_rejects_unproven_close_or_late_callback_quiescence(
    close_change: dict[str, object],
) -> None:
    port = _FakeTypedPort()
    observation = _post_close_observation(port)
    bad_close = replace(observation.close_receipt, **close_change)
    observation = replace(observation, close_receipt=bad_close)

    with pytest.raises(CtpSimNowSettlementQueryPortCandidateError) as raised:
        validate_ctp_simnow_settlement_query_port_candidate(port, _scope(), observation)

    assert raised.value.reason == "settlement_port_close_incomplete_or_mismatched"


def test_port_pair_requires_results_refreshed_after_close() -> None:
    port = _FakeTypedPort()
    observation = replace(_post_close_observation(port), results_refreshed_after_close=False)

    with pytest.raises(CtpSimNowSettlementQueryPortCandidateError) as raised:
        validate_ctp_simnow_settlement_query_port_candidate(port, _scope(), observation)

    assert raised.value.reason == "settlement_port_results_not_refreshed_after_close"


def test_port_pair_rejects_late_callbacks_in_final_request_snapshot() -> None:
    port = _FakeTypedPort()
    observation = _post_close_observation(port)
    late_info = replace(observation.settlement_info_result, late_callback_count=1)
    observation = replace(observation, settlement_info_result=late_info)

    with pytest.raises(ValueError, match="settlement_query_candidate_scope_or_submit_invalid"):
        validate_ctp_simnow_settlement_query_port_candidate(port, _scope(), observation)


def test_incomplete_adapter_surface_is_rejected_without_calling_it() -> None:
    class MissingSettlementInfoMethod:
        def query_settlement_confirmation_result(self, timeout: float = 5.0):
            raise AssertionError("validator must not call query methods")

        def get_query_result(self, request_id: int):
            raise AssertionError("validator must not call query methods")

        def stop_and_wait(self, timeout: float = 2.0):
            raise AssertionError("validator must not call close methods")

    with pytest.raises(CtpSimNowSettlementQueryPortCandidateError) as raised:
        validate_ctp_simnow_settlement_query_port_candidate(
            MissingSettlementInfoMethod(),
            _scope(),
            _post_close_observation(_FakeTypedPort()),
        )

    assert raised.value.reason == "settlement_port_candidate_surface_incomplete"
