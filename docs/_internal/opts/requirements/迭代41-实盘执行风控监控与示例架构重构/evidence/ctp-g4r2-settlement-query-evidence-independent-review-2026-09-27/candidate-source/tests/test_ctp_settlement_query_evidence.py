"""Fake-only contracts for terminal settlement confirmation query evidence."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import bt_api_ctp.ctp.client as client_module
from bt_api_ctp import CtpSettlementConfirmationEvidenceBuilder
from bt_api_ctp.containers.ctp.ctp_native_query_certificate import (
    CtpNativeQueryCertificateError,
)
from bt_api_ctp.ctp.client import TraderClient, _TraderSpi
from bt_api_ctp.query import QueryResult

BROKER_ID = "settlement-fixture-broker"
INVESTOR_ID = "settlement-fixture-investor"
TRADING_DAY = "20260923"


class FakeSettlementQueryField:
    def __init__(self, *, normalize_broker=False):
        self._broker_id = ""
        self._investor_id = ""
        self.AccountID = ""
        self.CurrencyID = ""
        self.normalize_broker = normalize_broker

    @property
    def BrokerID(self):
        return self._broker_id

    @BrokerID.setter
    def BrokerID(self, value):
        self._broker_id = value[:10] if self.normalize_broker else value

    @property
    def InvestorID(self):
        return self._investor_id

    @InvestorID.setter
    def InvestorID(self, value):
        self._investor_id = value


class GetterFailureSettlementQueryField(FakeSettlementQueryField):
    @property
    def BrokerID(self):
        raise AttributeError("native getter unavailable")

    @BrokerID.setter
    def BrokerID(self, value):
        self._broker_id = value


class FakeSettlementApi:
    def __init__(
        self,
        client,
        *,
        rows=None,
        callback_request_id_delta=0,
        terminal=True,
        return_code=0,
    ):
        self.client = client
        self.rows = (
            [
                SimpleNamespace(
                    BrokerID=BROKER_ID,
                    InvestorID=INVESTOR_ID,
                    ConfirmDate=TRADING_DAY,
                    ConfirmTime="15:30:00",
                    SettlementID=1,
                    AccountID=INVESTOR_ID,
                    CurrencyID="CNY",
                )
            ]
            if rows is None
            else rows
        )
        self.callback_request_id_delta = callback_request_id_delta
        self.terminal = terminal
        self.return_code = return_code
        self.calls = []

    def ReqQrySettlementInfoConfirm(self, field, request_id):
        self.calls.append(
            {
                "BrokerID": field.BrokerID,
                "InvestorID": field.InvestorID,
                "request_id": request_id,
            }
        )
        for row in self.rows:
            self.client._spi.OnRspQrySettlementInfoConfirm(
                row,
                SimpleNamespace(ErrorID=0, ErrorMsg=""),
                request_id + self.callback_request_id_delta,
                False,
            )
        self.client._spi.OnRspQrySettlementInfoConfirm(
            None,
            SimpleNamespace(ErrorID=0, ErrorMsg=""),
            request_id + self.callback_request_id_delta,
            self.terminal,
        )
        return self.return_code


def make_logged_in_client(
    monkeypatch, *, field_type=FakeSettlementQueryField, **api_options
):
    client = TraderClient(
        "tcp://offline.invalid:0",
        BROKER_ID,
        INVESTOR_ID,
        "",
        auto_settlement_confirm=False,
    )
    client._connected = True
    client._authentication_state = "authenticated"
    client._login_state = "logging_in"
    client._connection_generation = 7
    client._req_id = 30
    client._login_request_id = 30
    client._login_connection_generation = 7
    client._query_interval = 0.0
    _TraderSpi(client).OnRspUserLogin(
        SimpleNamespace(
            BrokerID=BROKER_ID,
            UserID=INVESTOR_ID,
            TradingDay=TRADING_DAY,
            FrontID=0,
            SessionID=0,
            MaxOrderRef="",
        ),
        SimpleNamespace(ErrorID=0, ErrorMsg=""),
        30,
        True,
    )
    monkeypatch.setattr(
        client_module, "CThostFtdcQrySettlementInfoConfirmField", field_type
    )
    api = FakeSettlementApi(client, **api_options)
    spi = _TraderSpi(client, native_api=api)
    client._api = api
    client._spi = spi
    return client, api


def test_vendor_settlement_struct_surface_has_filter_and_confirmation_date_getters():
    request_type = client_module.CThostFtdcQrySettlementInfoConfirmField
    response_type = client_module.CThostFtdcSettlementInfoConfirmField

    assert {"BrokerID", "InvestorID"} <= set(dir(request_type))
    assert {"BrokerID", "InvestorID", "ConfirmDate"} <= set(dir(response_type))
    assert "TradingDay" not in set(dir(response_type))


def test_settlement_query_seals_exact_native_filters_and_terminal_history(monkeypatch):
    client, api = make_logged_in_client(monkeypatch)

    result = client.query_settlement_confirmation_result(timeout=0.2)

    assert type(result) is QueryResult
    assert result.complete is True
    assert result.is_last_seen is True
    assert result.request_type == "settlement_confirmation"
    assert result.request_id > 0
    assert result.connection_generation == 7
    assert len(api.calls) == 1
    assert api.calls[0]["BrokerID"] == BROKER_ID
    assert api.calls[0]["InvestorID"] == INVESTOR_ID
    source = result.query_source
    assert source is not None
    assert source.request_intent_filters == (
        ("BrokerID", BROKER_ID),
        ("InvestorID", INVESTOR_ID),
    )
    assert source.request_filters == source.request_intent_filters
    assert source.explicit_request_filters == ()

    evidence = CtpSettlementConfirmationEvidenceBuilder(client).build(result)
    public = evidence.as_public_dict()
    assert evidence.request_type == "settlement_confirmation"
    assert evidence.request_id == result.request_id
    assert evidence.connection_generation == 7
    assert evidence.trading_day == TRADING_DAY
    assert evidence.complete is True
    assert evidence.is_last_seen is True
    assert evidence.timed_out is False
    assert evidence.late_callback_count == 0
    assert evidence.request_filter_names == ("BrokerID", "InvestorID")
    assert evidence.terminal_callback_records_sha256 == source.records_sha256
    assert len(evidence.terminal_callback_history_sha256) == 64
    assert public["execution_authorized"] is False
    assert public["confirmed_date"] == TRADING_DAY
    assert BROKER_ID not in repr(public)
    assert INVESTOR_ID not in repr(public)
    assert client._settlement_state == "not_requested"


@pytest.mark.parametrize(
    "field_type",
    [
        lambda: FakeSettlementQueryField(normalize_broker=True),
        GetterFailureSettlementQueryField,
    ],
)
def test_settlement_query_filter_readback_failure_has_no_native_call_or_source(
    monkeypatch, field_type
):
    client, api = make_logged_in_client(monkeypatch, field_type=field_type)

    result = client.query_settlement_confirmation_result(timeout=0.01)

    assert result.unsupported is True
    assert result.query_source is None
    assert api.calls == []


@pytest.mark.parametrize(
    "rows, expected_code",
    [
        ([], "settlement_query_row_count_invalid"),
        (
            [
                SimpleNamespace(
                    BrokerID=BROKER_ID,
                    InvestorID=INVESTOR_ID,
                    ConfirmDate=TRADING_DAY,
                ),
                SimpleNamespace(
                    BrokerID=BROKER_ID,
                    InvestorID=INVESTOR_ID,
                    ConfirmDate=TRADING_DAY,
                ),
            ],
            "settlement_query_row_count_invalid",
        ),
        (
            [
                SimpleNamespace(
                    BrokerID="other-broker",
                    InvestorID=INVESTOR_ID,
                    ConfirmDate=TRADING_DAY,
                )
            ],
            "settlement_query_row_scope_mismatch",
        ),
        (
            [
                SimpleNamespace(
                    BrokerID=BROKER_ID,
                    InvestorID="other-investor",
                    ConfirmDate=TRADING_DAY,
                )
            ],
            "settlement_query_row_scope_mismatch",
        ),
        (
            [
                SimpleNamespace(
                    BrokerID=BROKER_ID,
                    InvestorID=INVESTOR_ID,
                    ConfirmDate="20260922",
                )
            ],
            "settlement_query_row_scope_mismatch",
        ),
        (
            [
                SimpleNamespace(
                    BrokerID=BROKER_ID,
                    InvestorID=INVESTOR_ID,
                    ConfirmDate=TRADING_DAY,
                    TradingDay="20260922",
                )
            ],
            "settlement_query_row_scope_mismatch",
        ),
        (
            [
                SimpleNamespace(
                    BrokerID=BROKER_ID,
                    InvestorID=INVESTOR_ID,
                    TradingDay=TRADING_DAY,
                )
            ],
            "settlement_query_row_scope_mismatch",
        ),
    ],
)
def test_settlement_evidence_requires_one_exact_native_scope_row(
    monkeypatch, rows, expected_code
):
    client, _api = make_logged_in_client(monkeypatch, rows=rows)
    result = client.query_settlement_confirmation_result(timeout=0.2)

    with pytest.raises(CtpNativeQueryCertificateError) as exc:
        CtpSettlementConfirmationEvidenceBuilder(client).build(result)

    assert exc.value.code == expected_code


def test_settlement_evidence_rejects_nonterminal_wrong_request_id_and_submit_failure(
    monkeypatch,
):
    client, _api = make_logged_in_client(monkeypatch, terminal=False)
    incomplete = client.query_settlement_confirmation_result(timeout=0.001)
    with pytest.raises(
        CtpNativeQueryCertificateError, match="settlement_query_incomplete"
    ):
        CtpSettlementConfirmationEvidenceBuilder(client).build(incomplete)

    client, _api = make_logged_in_client(monkeypatch, callback_request_id_delta=1)
    wrong_request = client.query_settlement_confirmation_result(timeout=0.001)
    assert wrong_request.timed_out is True
    with pytest.raises(
        CtpNativeQueryCertificateError, match="settlement_query_incomplete"
    ):
        CtpSettlementConfirmationEvidenceBuilder(client).build(wrong_request)

    client, _api = make_logged_in_client(monkeypatch, return_code=-1)
    rejected = client.query_settlement_confirmation_result(timeout=0.001)
    assert rejected.submit_code == -1
    with pytest.raises(
        CtpNativeQueryCertificateError, match="settlement_query_incomplete"
    ):
        CtpSettlementConfirmationEvidenceBuilder(client).build(rejected)


def test_settlement_evidence_binds_terminal_payload_and_current_session(monkeypatch):
    client, _api = make_logged_in_client(monkeypatch)
    result = client.query_settlement_confirmation_result(timeout=0.2)
    result.records[0]["ConfirmDate"] = "20260922"

    with pytest.raises(CtpNativeQueryCertificateError, match="query_payload_mismatch"):
        CtpSettlementConfirmationEvidenceBuilder(client).build(result)

    client, _api = make_logged_in_client(monkeypatch)
    result = client.query_settlement_confirmation_result(timeout=0.2)
    client._connection_generation += 1

    with pytest.raises(CtpNativeQueryCertificateError):
        CtpSettlementConfirmationEvidenceBuilder(client).build(result)
