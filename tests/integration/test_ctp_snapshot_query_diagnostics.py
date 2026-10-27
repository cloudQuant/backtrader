"""Compose the real installed CTP query client with the public snapshot path.

Only the two native request leaves are synthetic.  The SDK owns request
registration, callback fencing, packet accumulation, completion and timeout;
the Backtrader Store, collector and 028 runner consume its real QueryResult.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.test_utils.optional_sdk import optional_sdk


ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples" / "unified" / "028_alpha003_simnow_minute"
RUNNER_PATH = EXAMPLE / "run.py"
UTC = timezone.utc
NOW = datetime(2026, 10, 27, 1, 5, tzinfo=UTC)
TRADING_DAY = "20261027"
COLLECTION_LIMIT_SECONDS = 1.0
SDK_QUERY_TIMEOUT_SECONDS = 0.05


def _load_runner():
    example_path = str(EXAMPLE)
    if example_path not in sys.path:
        sys.path.insert(0, example_path)
    spec = importlib.util.spec_from_file_location(
        "alpha003_simnow_runner_ctp_query_integration", RUNNER_PATH
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


RUNNER = _load_runner()

_STAGE_FIELDS = frozenset(
    {
        "stage",
        "entered",
        "returned",
        "elapsed_seconds",
        "prior_stage_complete",
        "result_type_matches",
        "request_type_matches",
        "generation_matches",
        "request_id_positive",
        "timed_out",
        "complete",
        "is_last_seen",
        "unsupported",
        "late_callbacks_reported",
        "late_callback_count_valid",
        "record_count",
        "record_count_capped",
        "submit_category",
        "error_code_present",
        "error_code_valid",
        "error_code_nonzero",
        "error_message_present",
        "error_message_valid",
        "error_category",
        "first_completion_origin",
        "completion_origin",
    }
)


class _SyntheticRequestApi:
    """Synthetic CTP Req leaves that return packets through the actual SPI."""

    def __init__(self, scenario: str):
        self.scenario = scenario
        self.spi = None
        self.request_names: list[str] = []
        self.callback_error_messages: list[str] = []
        self._success = SimpleNamespace(ErrorID=0, ErrorMsg="")
        self._connection_lost_text = SimpleNamespace(ErrorID=73, ErrorMsg="connection_lost")
        self._response_error = SimpleNamespace(ErrorID=73, ErrorMsg="synthetic_response_error")

    def ReqQryInstrument(self, field, request_id):
        self.request_names.append("catalog")
        assert field.InstrumentID == ""
        assert field.ExchangeID == ""
        assert field.ProductID == ""
        if self.scenario == "wrong_id_catalog_timeout":
            self.spi.OnRspQryInstrument(_catalog_row(), self._success, request_id + 1, True)
        elif self.scenario == "partial_catalog_timeout":
            self.spi.OnRspQryInstrument(_catalog_row(), self._success, request_id, False)
        elif self.scenario == "empty_nonterminal_catalog_timeout":
            self.spi.OnRspQryInstrument(None, self._success, request_id, False)
        elif self.scenario == "partial_catalog_response_error":
            self.spi.OnRspQryInstrument(_catalog_row(), self._success, request_id, False)
            self.callback_error_messages.append(self._response_error.ErrorMsg)
            self.spi.OnRspError(self._response_error, request_id, False)
        elif self.scenario == "partial_catalog_front_disconnect":
            self.spi.OnRspQryInstrument(_catalog_row(), self._success, request_id, False)
            self.spi.OnFrontDisconnected(100)
        elif self.scenario == "typed_catalog_connection_lost_message":
            self.callback_error_messages.append(self._connection_lost_text.ErrorMsg)
            self.spi.OnRspQryInstrument(
                _catalog_row(), self._connection_lost_text, request_id, True
            )
        else:
            self.spi.OnRspQryInstrument(_catalog_row(), self._success, request_id, True)
        return 0

    def ReqQryDepthMarketData(self, field, request_id):
        self.request_names.append("depth")
        assert field.InstrumentID == ""
        assert field.ExchangeID == ""
        if self.scenario == "valid_catalog_depth_timeout":
            self.spi.OnRspQryDepthMarketData(_quote_row(), self._success, request_id, False)
        else:
            self.spi.OnRspQryDepthMarketData(_quote_row(), self._success, request_id, True)
        return 0


def _catalog_row():
    return SimpleNamespace(
        InstrumentID="M2611",
        ExchangeID="DCE",
        ProductID="m",
        ProductClass="1",
        IsTrading=1,
        ExpireDate="20261116",
    )


def _quote_row():
    return SimpleNamespace(
        InstrumentID="M2611",
        ExchangeID="DCE",
        TradingDay=TRADING_DAY,
        OpenInterest=1000,
        Volume=25,
        ActionDay=TRADING_DAY,
        UpdateTime="09:00:00",
        UpdateMillisec=250,
    )


def _real_read_only_client(monkeypatch, client_module, scenario):
    """Bind a real SDK client and SPI to one synthetic current API session."""

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return NOW.replace(tzinfo=None)
            return NOW.astimezone(tz)

    def unexpected_external_start(*_args, **_kwargs):
        pytest.fail("TraderClient.start must not be called by this synthetic query test")

    def unexpected_native_factory(*_args, **_kwargs):
        pytest.fail("the native API factory must not be called by this synthetic query test")

    monkeypatch.setattr(client_module, "datetime", FrozenDateTime)
    monkeypatch.setattr(client_module.TraderClient, "start", unexpected_external_start)
    # Replace the module lookup rather than mutating an extension/SWIG class.
    # _TraderSpi is already the actual SDK subclass and remains untouched.
    monkeypatch.setattr(
        client_module,
        "CThostFtdcTraderApi",
        SimpleNamespace(CreateFtdcTraderApi=unexpected_native_factory),
    )

    client = client_module.TraderClient(
        "tcp://synthetic.invalid:1",
        "9999",
        "fixture-user",
        "fixture-password",
        auto_settlement_confirm=False,
    )
    request_api = _SyntheticRequestApi(scenario)
    with client._query_state_lock:
        # The public setter creates the SDK's generation and source identities.
        client._api = request_api
        client._session_native_api = request_api
        client._session_native_front = client._bound_front
        client._connected = True
        client._authentication_state = "authenticated"
        client._connection_generation = 1
        client._login_state = "logging_in"
        login_request_id = client._next_request_id()
        client._login_request_id = login_request_id
        client._login_connection_generation = client._connection_generation
        client._query_interval = 0.0

        spi = client_module._TraderSpi(client, request_api)
        spi._native_api_generation = client._native_api_generation
        spi._native_client_epoch = client._native_client_epoch
        spi._native_api_source_id = client._native_api_source_id
        client._spi = spi
        request_api.spi = spi

    # Use the actual SDK login callback to create its current read-only
    # identity; do not fabricate a client-side ready flag or QueryResult.
    spi.OnRspUserLogin(
        SimpleNamespace(
            BrokerID=client._bound_broker_id,
            UserID=client._bound_user_id,
            TradingDay=TRADING_DAY,
            FrontID=7,
            SessionID=19,
            MaxOrderRef="0",
        ),
        SimpleNamespace(ErrorID=0, ErrorMsg=""),
        login_request_id,
        True,
    )
    assert client.is_read_only_ready is True
    state = client.get_session_state()
    assert state["trading_day"] == TRADING_DAY
    assert state["connection_generation"] == 1
    assert state["read_only_ready"] is True
    return client, request_api


def _bound_fixture_query_timeouts(monkeypatch, client):
    """Shorten only SDK timeout arguments while preserving its query engine."""

    bounded_calls = []
    for method_name in ("query_instruments_result", "query_depth_market_data_result"):
        original = getattr(client, method_name)

        def bounded(*args, _original=original, _method_name=method_name, **kwargs):
            kwargs = dict(kwargs)
            kwargs["timeout"] = min(kwargs["timeout"], SDK_QUERY_TIMEOUT_SECONDS)
            if kwargs.get("max_duration") is not None:
                kwargs["max_duration"] = min(
                    kwargs["max_duration"], SDK_QUERY_TIMEOUT_SECONDS
                )
            stage = "catalog" if _method_name == "query_instruments_result" else "depth"
            call = [
                stage,
                kwargs["timeout"],
                kwargs.get("max_duration"),
                kwargs.get("deadline_monotonic"),
                None,
            ]
            bounded_calls.append(call)
            result = _original(*args, **kwargs)
            call[4] = result
            return result

        monkeypatch.setattr(client, method_name, bounded)
    return bounded_calls


@pytest.mark.parametrize(
    ("scenario", "expected_requests", "expected_stages", "expected_detail"),
    [
        pytest.param(
            "partial_catalog_timeout",
            ["catalog"],
            [
                {
                    "stage": "catalog",
                    "record_count": 1,
                    "complete": False,
                    "is_last_seen": False,
                    "timed_out": True,
                    "error_code_present": False,
                    "error_message_present": True,
                    "error_category": "timeout",
                    "origin": "timeout",
                }
            ],
            "QUERY_TIMED_OUT",
            id="partial-catalog-timeout",
        ),
        pytest.param(
            "wrong_id_catalog_timeout",
            ["catalog"],
            [
                {
                    "stage": "catalog",
                    "record_count": 0,
                    "complete": False,
                    "is_last_seen": False,
                    "timed_out": True,
                    "error_code_present": False,
                    "error_message_present": True,
                    "error_category": "timeout",
                    "origin": "timeout",
                }
            ],
            "QUERY_TIMED_OUT",
            id="wrong-request-id-catalog-timeout",
        ),
        pytest.param(
            "empty_nonterminal_catalog_timeout",
            ["catalog"],
            [
                {
                    "stage": "catalog",
                    "record_count": 0,
                    "complete": False,
                    "is_last_seen": False,
                    "timed_out": True,
                    "error_code_present": False,
                    "error_message_present": True,
                    "error_category": "timeout",
                    "origin": "timeout",
                }
            ],
            "QUERY_TIMED_OUT",
            id="empty-nonterminal-catalog-timeout",
        ),
        pytest.param(
            "valid_catalog_depth_timeout",
            ["catalog", "depth"],
            [
                {
                    "stage": "catalog",
                    "record_count": 1,
                    "complete": True,
                    "is_last_seen": True,
                    "timed_out": False,
                    "error_code_present": False,
                    "error_message_present": False,
                    "error_category": "none",
                    "origin": "success",
                },
                {
                    "stage": "depth",
                    "record_count": 1,
                    "complete": False,
                    "is_last_seen": False,
                    "timed_out": True,
                    "error_code_present": False,
                    "error_message_present": True,
                    "error_category": "timeout",
                    "origin": "timeout",
                },
            ],
            "QUERY_TIMED_OUT",
            id="valid-catalog-depth-timeout",
        ),
        pytest.param(
            "partial_catalog_response_error",
            ["catalog"],
            [
                {
                    "stage": "catalog",
                    "record_count": 1,
                    "complete": False,
                    "is_last_seen": False,
                    "timed_out": False,
                    "error_code_present": True,
                    "error_message_present": True,
                    "error_category": "query_error",
                    "origin": "response_error",
                }
            ],
            "QUERY_ERROR",
            id="partial-response-error-origin",
        ),
        pytest.param(
            "partial_catalog_front_disconnect",
            ["catalog"],
            [
                {
                    "stage": "catalog",
                    "record_count": 1,
                    "complete": False,
                    "is_last_seen": False,
                    "timed_out": False,
                    "error_code_present": True,
                    "error_message_present": True,
                    "error_category": "query_error",
                    "origin": "front_disconnected",
                }
            ],
            "QUERY_ERROR",
            id="partial-front-disconnect-origin",
        ),
        pytest.param(
            "typed_catalog_connection_lost_message",
            ["catalog"],
            [
                {
                    "stage": "catalog",
                    "record_count": 1,
                    "complete": False,
                    "is_last_seen": True,
                    "timed_out": False,
                    "error_code_present": True,
                    "error_message_present": True,
                    "error_category": "query_error",
                    "origin": "query_response",
                }
            ],
            "QUERY_ERROR",
            id="typed-response-connection-lost-text-is-not-disconnect-origin",
        ),
    ],
)
def test_real_trader_client_query_diagnostics_are_bounded_and_runner_visible(
    scenario, expected_requests, expected_stages, expected_detail, monkeypatch
):
    """Failures traverse SDK SPI, QueryResult, Store, collector, and runner."""

    client_module = optional_sdk("bt_api_ctp.ctp.client")
    query_result_type = optional_sdk("bt_api_ctp.query").QueryResult
    client, request_api = _real_read_only_client(monkeypatch, client_module, scenario)
    bounded_calls = _bound_fixture_query_timeouts(monkeypatch, client)

    from backtrader.feeds import futures_ctp_snapshot as snapshot_adapter
    from tests.unit.stores.test_btapistore import _registered_sim_snapshot_store

    monkeypatch.setattr(snapshot_adapter, "_now_utc", lambda: NOW)
    store, registered_api, _fake_trader = _registered_sim_snapshot_store(query_result_type)
    registered_api.trader_client = client
    unbounded_collector = store.registered_sim_collect_futures_snapshot

    def bounded_collector(*, max_collection_seconds, max_snapshot_age_seconds):
        return unbounded_collector(
            max_collection_seconds=min(max_collection_seconds, COLLECTION_LIMIT_SECONDS),
            max_snapshot_age_seconds=min(max_snapshot_age_seconds, COLLECTION_LIMIT_SECONDS),
        )

    store.registered_sim_collect_futures_snapshot = bounded_collector
    clock = SimpleNamespace(utc_now=lambda: NOW)

    with pytest.raises(RUNNER.RunnerError) as caught:
        RUNNER.build_ctp_query_market_plan(
            store,
            {"selection": {"authorized_products": None}},
            clock=clock,
        )

    error = caught.value
    assert error.code == "CTP_FUTURES_SNAPSHOT_COLLECTION_FAILED"
    assert error.detail == expected_detail
    diagnostics = error.query_diagnostics
    assert set(diagnostics) == {"status", "stages"}
    assert diagnostics["status"] == "AVAILABLE"
    stages = diagnostics["stages"]
    assert len(stages) == len(expected_stages)

    for index, (stage, expected) in enumerate(zip(stages, expected_stages)):
        assert set(stage) == _STAGE_FIELDS
        assert stage["stage"] == expected["stage"]
        assert stage["entered"] is True
        assert stage["returned"] is True
        assert stage["result_type_matches"] is True
        assert stage["request_type_matches"] is True
        assert stage["generation_matches"] is True
        assert stage["request_id_positive"] is True
        assert stage["complete"] is expected["complete"]
        assert stage["is_last_seen"] is expected["is_last_seen"]
        assert stage["timed_out"] is expected["timed_out"]
        assert stage["record_count"] == expected["record_count"]
        assert stage["record_count_capped"] is False
        assert stage["submit_category"] == "accepted"
        assert stage["unsupported"] is False
        assert stage["late_callbacks_reported"] is False
        assert stage["late_callback_count_valid"] is True
        assert stage["error_code_present"] is expected["error_code_present"]
        assert stage["error_code_valid"] is True
        assert stage["error_code_nonzero"] is expected["error_code_present"]
        assert stage["error_message_valid"] is True
        assert stage["error_message_present"] is expected["error_message_present"]
        assert stage["error_category"] == expected["error_category"]
        assert stage["first_completion_origin"] == expected["origin"]
        assert stage["completion_origin"] == expected["origin"]
        if index:
            assert stage["prior_stage_complete"] is True
        else:
            assert stage["prior_stage_complete"] is None

    # The projection contains only fixed schema facts, never request IDs,
    # provider messages, account identifiers, or market-row contents.
    assert all(
        not {"request_id", "instrument_id", "account_id", "provider_message"}.intersection(stage)
        for stage in stages
    )
    assert [item[0] for item in bounded_calls] == expected_requests
    assert all(item[1] == SDK_QUERY_TIMEOUT_SECONDS for item in bounded_calls)
    assert all(
        max_duration is None or max_duration == SDK_QUERY_TIMEOUT_SECONDS
        for _, _, max_duration, _, _ in bounded_calls
    )
    assert len({item[3] for item in bounded_calls}) == 1
    assert type(bounded_calls[0][3]) is float
    assert request_api.request_names == expected_requests
    if scenario == "typed_catalog_connection_lost_message":
        assert request_api.callback_error_messages == ["connection_lost"]


def test_real_trader_client_valid_two_query_chain_builds_the_live_plan(monkeypatch):
    """A terminal catalog then terminal depth packet restores normal planning."""

    scenario = "valid_two_query_success"
    client_module = optional_sdk("bt_api_ctp.ctp.client")
    query_result_type = optional_sdk("bt_api_ctp.query").QueryResult
    client, request_api = _real_read_only_client(monkeypatch, client_module, scenario)
    bounded_calls = _bound_fixture_query_timeouts(monkeypatch, client)

    from backtrader.feeds import futures_ctp_snapshot as snapshot_adapter
    from tests.unit.stores.test_btapistore import _registered_sim_snapshot_store

    monkeypatch.setattr(snapshot_adapter, "_now_utc", lambda: NOW)
    store, registered_api, _fake_trader = _registered_sim_snapshot_store(query_result_type)
    registered_api.trader_client = client
    unbounded_collector = store.registered_sim_collect_futures_snapshot

    def bounded_collector(*, max_collection_seconds, max_snapshot_age_seconds):
        return unbounded_collector(
            max_collection_seconds=min(max_collection_seconds, COLLECTION_LIMIT_SECONDS),
            max_snapshot_age_seconds=min(max_snapshot_age_seconds, COLLECTION_LIMIT_SECONDS),
        )

    store.registered_sim_collect_futures_snapshot = bounded_collector
    plan = RUNNER.build_ctp_query_market_plan(
        store,
        {"selection": {"authorized_products": None}},
        clock=SimpleNamespace(utc_now=lambda: NOW),
    )

    assert client.is_read_only_ready is True
    assert request_api.request_names == ["catalog", "depth"]
    assert plan["selection_source"] == "ctp_query_snapshot_equal_weight_v1"
    assert plan["manifest"].status == "READY"
    assert plan["targets"] == ("DCE.M",)
    assert tuple(plan["routes"].values()) == ("M2611",)
    assert plan["grid"].status == "READY"
    assert plan["grid"].minutes
    assert [item[0] for item in bounded_calls] == ["catalog", "depth"]
    assert all(item[1] == SDK_QUERY_TIMEOUT_SECONDS for item in bounded_calls)
    assert bounded_calls[0][2] == SDK_QUERY_TIMEOUT_SECONDS
    assert len({item[3] for item in bounded_calls}) == 1
    assert type(bounded_calls[0][3]) is float
    assert [result.first_completion_origin for *_, result in bounded_calls] == [
        "success",
        "success",
    ]
    assert [result.completion_origin for *_, result in bounded_calls] == [
        "success",
        "success",
    ]
