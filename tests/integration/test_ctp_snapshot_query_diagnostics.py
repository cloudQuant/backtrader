"""Compose the real installed CTP query client with the public snapshot path.

The native request leaves are synthetic. The SDK owns request registration,
callback fencing, packet accumulation, completion and timeout; the Backtrader
Store, collector and 028 runner consume its real QueryResult.
"""

from __future__ import annotations

import heapq
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


class _ManualQueryClock:
    """Deterministic monotonic time for the real SDK's progressive waiter."""

    def __init__(self, start=100.0):
        self.now = float(start)
        self._sequence = 0
        self._scheduled = []

    def monotonic(self):
        return self.now

    def monotonic_ns(self):
        return int(self.now * 1_000_000_000)

    def schedule(self, delay, callback):
        self._sequence += 1
        heapq.heappush(
            self._scheduled,
            (self.now + float(delay), self._sequence, callback),
        )

    def advance(self, seconds):
        target = self.now + max(float(seconds), 0.0)
        while self._scheduled and self._scheduled[0][0] <= target:
            at, _sequence, callback = heapq.heappop(self._scheduled)
            self.now = at
            callback()
        self.now = max(self.now, target)

    def event(self):
        return _ManualQueryEvent(self)


class _ManualQueryEvent:
    """Event-compatible wait that advances monotonic time and dispatches SPI."""

    def __init__(self, clock):
        self.clock = clock
        self._set = False

    def set(self):
        self._set = True

    def is_set(self):
        return self._set

    def wait(self, timeout=None):
        if not self._set:
            self.clock.advance(0.0 if timeout is None else timeout)
        return self._set


class _StagedSyntheticRequestApi:
    """Synthetic Req leaves; the installed TraderClient owns result semantics."""

    def __init__(self, clock, product_ids, *, mode="heterogeneous"):
        self.clock = clock
        self.product_ids = tuple(product_ids)
        self.mode = mode
        self.spi = None
        self.request_names = []
        self._success = SimpleNamespace(ErrorID=0, ErrorMsg="")

    def _schedule(self, callback_name, record, request_id, delay, is_last):
        callback = getattr(self.spi, callback_name)
        self.clock.schedule(
            delay,
            lambda: callback(record, self._success, request_id, is_last),
        )

    def ReqQryProduct(self, field, request_id):
        self.request_names.append("products")
        assert field.ProductClass == "1"
        assert field.ExchangeID == field.ProductID == ""
        for index, product_id in enumerate(self.product_ids):
            record = {
                "ExchangeID": "DCE",
                "ProductID": product_id,
                "ProductClass": "1",
            }
            self._schedule(
                "OnRspQryProduct",
                record,
                request_id,
                0.01 * (index + 1),
                index == len(self.product_ids) - 1,
            )
        return 0

    def ReqQryInstrument(self, field, request_id):
        self.request_names.append("instruments")
        product_id = field.ProductID
        assert field.InstrumentID == ""
        assert field.ExchangeID == "DCE"
        record = {
            "ExchangeID": "DCE",
            "ProductID": product_id,
            "ProductClass": "1",
            "InstrumentID": product_id + "2611",
            "IsTrading": 1,
            "ExpireDate": "20261218",
        }
        if self.mode == "deadline" and product_id == self.product_ids[0]:
            # Keep the SDK's idle timer alive while the single caller-owned
            # deadline expires without a terminal packet.
            for elapsed in range(4, 300, 4):
                self._schedule(
                    "OnRspQryInstrument",
                    None,
                    request_id,
                    float(elapsed),
                    False,
                )
        elif self.mode == "missing_terminal" and product_id == self.product_ids[0]:
            self._schedule("OnRspQryInstrument", record, request_id, 0.01, False)
        else:
            delay = 2.0 if self.mode == "heterogeneous" and product_id == "p0" else 0.01
            self._schedule("OnRspQryInstrument", record, request_id, delay, True)
        return 0

    def ReqQryDepthMarketData(self, field, request_id):
        self.request_names.append("depth")
        assert field.InstrumentID == field.ExchangeID == ""
        self._schedule("OnRspQryDepthMarketData", None, request_id, 0.01, True)
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


def _real_read_only_client(monkeypatch, client_module, scenario, *, request_api=None):
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
    request_api = request_api or _SyntheticRequestApi(scenario)
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


def _staged_real_protocol_client(monkeypatch, clock, request_api):
    """Use the installed SDK client/SPI/result contract with synthetic Req leaves."""

    from backtrader.feeds import futures_ctp_snapshot as snapshot_adapter

    client_module = optional_sdk("bt_api_ctp.ctp.client")
    query_module = optional_sdk("bt_api_ctp.query")
    instrument_module = optional_sdk("bt_api_ctp.instrument")
    client, request_api = _real_read_only_client(
        monkeypatch,
        client_module,
        "staged_synthetic",
        request_api=request_api,
    )
    monkeypatch.setattr(
        client_module,
        "time",
        SimpleNamespace(monotonic=clock.monotonic, monotonic_ns=clock.monotonic_ns),
    )
    monkeypatch.setattr(snapshot_adapter, "time", SimpleNamespace(monotonic=clock.monotonic))
    monkeypatch.setattr(snapshot_adapter, "_now_utc", lambda: NOW)
    monkeypatch.setattr(
        snapshot_adapter,
        "_load_sdk_contract",
        lambda: (query_module.QueryResult, instrument_module.normalize_ctp_instrument),
    )

    original_new_accumulator = client._new_query_accumulator

    def controlled_accumulator(*args, **kwargs):
        accumulator = original_new_accumulator(*args, **kwargs)
        accumulator.event = clock.event()
        return accumulator

    monkeypatch.setattr(client, "_new_query_accumulator", controlled_accumulator)

    budgets = []
    for method_name in (
        "query_products_result",
        "query_instruments_result",
        "query_depth_market_data_result",
    ):
        original_method = getattr(client, method_name)

        def observed(*args, _method=original_method, _name=method_name, **kwargs):
            budgets.append((_name, dict(kwargs)))
            return _method(*args, **kwargs)

        monkeypatch.setattr(client, method_name, observed)
    return client, request_api, snapshot_adapter, budgets


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


def test_staged_real_sdk_budget_accepts_heterogeneous_terminal_responses(monkeypatch):
    """A slow early product can borrow time that faster later calls leave unused."""

    clock = _ManualQueryClock()
    request_api = _StagedSyntheticRequestApi(clock, ("p0", "p1", "p2", "p3"), mode="heterogeneous")
    client, request_api, snapshot_adapter, budgets = _staged_real_protocol_client(
        monkeypatch, clock, request_api
    )

    snapshot = snapshot_adapter.collect_ctp_futures_snapshot(
        client,
        max_collection_seconds=6.0,
        max_snapshot_age_seconds=6.0,
        query_mode="staged_product_set",
    )

    assert request_api.request_names == [
        "products",
        "instruments",
        "instruments",
        "instruments",
        "instruments",
        "depth",
    ]
    assert budgets[0][0] == "query_products_result"
    assert budgets[0][1]["max_duration"] == pytest.approx(0.6)
    assert budgets[1][0] == "query_instruments_result"
    assert budgets[1][1]["max_duration"] == pytest.approx(5.9)
    assert budgets[1][1]["timeout"] == 5.0
    assert budgets[1][1]["deadline_monotonic"] == pytest.approx(106.0)
    assert budgets[-1][0] == "query_depth_market_data_result"
    assert clock.monotonic() - 100.0 < 6.0

    query_set = snapshot.query_set
    assert query_set is not None
    assert len(query_set.products) == 4
    assert len(query_set.requests) == 6
    assert all(
        source.complete is True and source.is_last_seen is True for source in query_set.requests
    )
    results = tuple(client.get_query_result(source.request_id) for source in query_set.requests)
    assert all(result is not None and result.complete and result.is_last_seen for result in results)
    assert [result.request_type for result in results] == [
        "products",
        "instruments",
        "instruments",
        "instruments",
        "instruments",
        "depth_market_data",
    ]
    assert snapshot.session_trading_day_before == snapshot.session_trading_day_after
    assert snapshot.session_generation_before == snapshot.session_generation_after == 1


def test_staged_real_sdk_global_deadline_still_fails_closed_without_terminal(monkeypatch):
    """Progress can extend idle time but cannot extend the caller's 300s deadline."""

    clock = _ManualQueryClock()
    request_api = _StagedSyntheticRequestApi(clock, ("p0",), mode="deadline")
    client, request_api, snapshot_adapter, budgets = _staged_real_protocol_client(
        monkeypatch, clock, request_api
    )

    with pytest.raises(snapshot_adapter.CtpFuturesSnapshotError) as caught:
        snapshot_adapter.collect_ctp_futures_snapshot(
            client,
            max_collection_seconds=300.0,
            max_snapshot_age_seconds=300.0,
            query_mode="staged_product_set",
        )

    assert caught.value.code == "QUERY_TIMED_OUT"
    assert request_api.request_names == ["products", "instruments"]
    assert [name for name, _ in budgets] == [
        "query_products_result",
        "query_instruments_result",
    ]
    observation = caught.value.query_observations[-1]
    assert observation.stage == "instruments_001"
    assert observation.timed_out is True
    assert observation.complete is False
    assert observation.is_last_seen is False
    assert observation.completion_origin == "deadline"
    assert clock.monotonic() == pytest.approx(400.0)


def test_staged_real_sdk_missing_terminal_packet_remains_incomplete(monkeypatch):
    """A nonterminal instrument packet cannot authorize later stages."""

    clock = _ManualQueryClock()
    request_api = _StagedSyntheticRequestApi(clock, ("p0", "p1"), mode="missing_terminal")
    client, request_api, snapshot_adapter, budgets = _staged_real_protocol_client(
        monkeypatch, clock, request_api
    )

    with pytest.raises(snapshot_adapter.CtpFuturesSnapshotError) as caught:
        snapshot_adapter.collect_ctp_futures_snapshot(
            client,
            max_collection_seconds=30.0,
            max_snapshot_age_seconds=30.0,
            query_mode="staged_product_set",
        )

    assert caught.value.code == "QUERY_TIMED_OUT"
    assert request_api.request_names == ["products", "instruments"]
    assert [name for name, _ in budgets] == [
        "query_products_result",
        "query_instruments_result",
    ]
    observation = caught.value.query_observations[-1]
    assert observation.stage == "instruments_001"
    assert observation.timed_out is True
    assert observation.complete is False
    assert observation.is_last_seen is False
    assert observation.completion_origin == "timeout"
