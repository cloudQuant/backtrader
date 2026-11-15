"""Store's local calendar observations never create a trading session."""

import hashlib
import json
import threading
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

import bt_api_py
from backtrader.stores import btapistore as module
from backtrader.stores.btapistore import BtApiStore
from backtrader.live_state.gateway_pending import GatewayPendingHost
from backtrader.service import service_read_proxy as proxy_module
from bt_api_base.gateway_direct_protocol import GatewayCommandBinding
from bt_api_py.bt_api import BtApi
from bt_api_py.service_runtime import ClientCurveKeys
from bt_api_py.trading_calendar_runtime_status import TradingCalendarStatus
from bt_api_py.trading_calendar_store import (
    CurrentPrecondition, PolicyPublication, TradingCalendarStore, calendar_snapshot_digest,
)
from tests.unit.live_state.conftest import state as state, strategy_dir as strategy_dir

ROUTE = "CTP___FUTURE"
OTHER = "OTHER___FUTURE"


def observed_status():
    return TradingCalendarStatus(
        "OBSERVED_UNAUTHENTICATED", "CURRENT_RECEIPTS_CONSISTENT",
        published="CURRENT_OBSERVED", publication_id="p1", version_id="v1",
        publication_sha256="a" * 64, content_sha256="b" * 64, coverage_status="NOT_PRESENT",
    )


def publish(root):
    store = TradingCalendarStore(root)
    policy = store.initialize_review_policy(config_read_succeeded=True)
    content = {"sources": [{"source": 1}], "trading_days": [{"day": 1}],
               "trading_hours": [{"hours": 1}], "exceptions": []}
    difference = {}
    digest = hashlib.sha256(json.dumps(difference, sort_keys=True, separators=(",", ":"),
                                       ensure_ascii=False).encode()).hexdigest()
    claim = PolicyPublication(policy.directory_id, policy.revision, policy.mode,
                              calendar_snapshot_digest(content), difference, digest)
    result = store.publish(content, publication_id="p1", version_id="v1",
                           expected_current=CurrentPrecondition.absent(),
                           policy_publication=claim)
    assert result.visibility == "COMMITTED"


def make_store(monkeypatch, routes=(ROUTE,)):
    api = BtApi(debug=False)
    api.exchange_feeds.update({route: object() for route in routes})
    store = BtApiStore(api=api, config={"exchange_kwargs": {route: {} for route in routes}})
    def start(s, *_args, **_kwargs):
        s._started = s._connected = s._sdk_configured = True
    monkeypatch.setattr(module, "_start_store", start)
    store.start()
    return store, api


def test_real_sdk_reader_on_temporary_published_store(monkeypatch, tmp_path):
    root = tmp_path / "private-location"
    root.mkdir()
    publish(root)
    store, api = make_store(monkeypatch, (ROUTE, OTHER))
    api.configure_trading_calendar_status(route_roots={ROUTE: str(root)})
    def forbidden(*_args, **_kwargs):
        raise AssertionError("status must not start, connect or reconfigure")
    monkeypatch.setattr(store, "_ensure_api_ready", forbidden)
    monkeypatch.setattr(api, "configure_trading_calendar_status", forbidden)
    monkeypatch.setattr(api, "connect", forbidden, raising=False)
    result = store.trading_calendar_status()
    assert result["status"] == "PARTIAL"
    assert result["reason"] == "PARTIAL_ROUTE_RESULTS"
    observed = result["routes"][ROUTE]
    assert (observed.publication_id, observed.version_id) == ("p1", "v1")
    assert (observed.coverage_status, observed.bound, observed.source_authentication) == (
        "NOT_PRESENT", "NOT_BOUND", "NOT_PROVEN")
    assert result["routes"][OTHER].reason == "ROUTE_UNCONFIGURED"
    assert str(root) not in repr(result)
    assert store.trading_calendar_status(ROUTE)["routes"][ROUTE] == observed
    assert store.trading_calendar_status(ROUTE)["status"] == "OBSERVED"


@pytest.mark.parametrize(
    ("first", "second", "expected", "reason"),
    [
        ("UNKNOWN", "UNKNOWN", "UNKNOWN", "ROUTES_UNAVAILABLE"),
        ("OBSERVED_UNAUTHENTICATED", "OBSERVED_UNAUTHENTICATED", "OBSERVED", "ROUTE_RESULTS"),
        ("OBSERVED_UNAUTHENTICATED", "UNKNOWN", "PARTIAL", "PARTIAL_ROUTE_RESULTS"),
        ("UNKNOWN", "OBSERVED_UNAUTHENTICATED", "PARTIAL", "PARTIAL_ROUTE_RESULTS"),
    ],
)
def test_aggregate_reflects_each_sdk_observation(monkeypatch, first, second, expected, reason):
    store, api = make_store(monkeypatch, (ROUTE, OTHER))
    def observation(status):
        if status == "OBSERVED_UNAUTHENTICATED":
            return observed_status()
        return TradingCalendarStatus("UNKNOWN", "ROUTE_UNCONFIGURED")
    values = {ROUTE: observation(first), OTHER: observation(second)}
    monkeypatch.setattr(api, "trading_calendar_status", values.__getitem__)
    result = store.trading_calendar_status()
    assert (result["status"], result["reason"]) == (expected, reason)
    assert result["routes"] == values
    assert result["routes"][ROUTE] is values[ROUTE]
    assert result["routes"][OTHER] is values[OTHER]


@pytest.mark.parametrize("bad", ["exception", "dto", "missing_route", "invalid_route"])
def test_observation_and_unavailable_route_report_partial_without_leaks(monkeypatch, bad):
    store, api = make_store(monkeypatch, (ROUTE, OTHER))
    good = observed_status()
    if bad == "missing_route":
        api.exchange_feeds.pop(OTHER)
    elif bad == "invalid_route":
        store._sdk_exchanges["/private/config"] = {}
    def read(route):
        if route == OTHER:
            if bad == "exception":
                raise RuntimeError("/private/exception")
            if bad == "dto":
                return replace(good, version_id="/private/dto")
        return good
    monkeypatch.setattr(api, "trading_calendar_status", read)
    result = store.trading_calendar_status()
    assert result["status"] == "PARTIAL"
    assert result["reason"] == (
        "INVALID_CONFIGURED_ROUTE" if bad == "invalid_route" else "PARTIAL_ROUTE_RESULTS"
    )
    assert result["routes"][ROUTE] is good
    if bad != "invalid_route":
        assert result["routes"][OTHER].status == "UNKNOWN"
    assert "/private/" not in repr(result)


@pytest.mark.parametrize("change", ["remove", "add", "exception", "duplicate", "malformed"])
def test_sdk_route_set_change_discards_all_observations(monkeypatch, change):
    store, api = make_store(monkeypatch, (ROUTE, OTHER))
    good = observed_status()
    original_list = api.list_exchanges
    calls = []
    def list_routes():
        calls.append(None)
        if len(calls) == 2:
            if change == "exception":
                raise RuntimeError("/private/exception")
            if change == "duplicate":
                return [ROUTE, ROUTE]
            if change == "malformed":
                return [ROUTE, "/private/route"]
        return original_list()
    def read(route):
        if route == ROUTE:
            if change == "remove":
                api.exchange_feeds.pop(OTHER)
            elif change == "add":
                api.exchange_feeds["THIRD___FUTURE"] = object()
        return good
    monkeypatch.setattr(api, "list_exchanges", list_routes)
    monkeypatch.setattr(api, "trading_calendar_status", read)
    result = store.trading_calendar_status()
    assert len(calls) == 2
    assert (result["status"], result["reason"]) == ("UNKNOWN", "ROUTE_SET_CHANGED")
    assert {value.reason for value in result["routes"].values()} == {"ROUTE_SET_CHANGED"}
    assert "/private/" not in repr(result)


def test_not_started_and_missing_route_never_create_or_connect(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("unexpected startup or network activity")
    store = BtApiStore(config={"exchange_kwargs": {ROUTE: {}}}, api_cls=forbidden)
    monkeypatch.setattr(store, "_ensure_api_ready", forbidden)
    assert store.trading_calendar_status()["routes"][ROUTE].reason == "STORE_UNAVAILABLE"
    assert store.trading_calendar_status("MISSING")["reason"] == "ROUTE_UNCONFIGURED"
    assert store._api is None


def test_partial_failures_and_exact_live_routes(monkeypatch):
    store, api = make_store(monkeypatch, (ROUTE, OTHER))
    calls = []
    def read(route):
        calls.append(route)
        if route == OTHER:
            raise RuntimeError("/private/password")
        return TradingCalendarStatus("UNKNOWN", "ROUTE_UNCONFIGURED")
    monkeypatch.setattr(api, "trading_calendar_status", read)
    result = store.trading_calendar_status()
    assert result["status"] == "UNKNOWN"
    assert result["routes"][ROUTE].reason == "ROUTE_UNCONFIGURED"
    assert result["routes"][OTHER].reason == "READ_UNAVAILABLE"
    assert "/private/password" not in repr(result)
    api.exchange_feeds.pop(OTHER)
    calls.clear()
    result = store.trading_calendar_status()
    assert result["routes"][OTHER].reason == "ROUTE_UNAVAILABLE"
    assert calls == [ROUTE]
    monkeypatch.setattr(api, "trading_calendar_status", None)
    assert store.trading_calendar_status()["reason"] == "CAPABILITY_UNAVAILABLE"


def test_untrusted_status_never_discloses_path(monkeypatch):
    store, api = make_store(monkeypatch)
    forged = replace(TradingCalendarStatus("UNKNOWN", "ROUTE_UNCONFIGURED"),
                     version_id="/private/secret")
    monkeypatch.setattr(api, "trading_calendar_status", lambda _route: forged)
    result = store.trading_calendar_status()
    assert result["routes"][ROUTE].reason == "READ_UNAVAILABLE"
    assert "/private/secret" not in repr(result)
    monkeypatch.setattr(api, "trading_calendar_status", lambda _route: {"path": "/private"})
    assert store.trading_calendar_status()["routes"][ROUTE].reason == "READ_UNAVAILABLE"


@pytest.mark.parametrize("changes", [
    {"reason": "ROUTE_UNCONFIGURED"},
    {"published": "UNKNOWN"},
    {"publication_id": None},
    {"version_id": None},
    {"publication_sha256": None},
    {"content_sha256": None},
    {"coverage_status": "UNKNOWN"},
])
def test_contradictory_observed_status_is_unavailable(monkeypatch, changes):
    store, api = make_store(monkeypatch)
    forged = replace(observed_status(), **changes)
    monkeypatch.setattr(api, "trading_calendar_status", lambda _route: forged)
    result = store.trading_calendar_status()
    assert result["status"] == "UNKNOWN"
    assert result["routes"][ROUTE].reason == "READ_UNAVAILABLE"


@pytest.mark.parametrize("changes", [
    {"reason": "CURRENT_RECEIPTS_CONSISTENT"},
    {"published": "CURRENT_OBSERVED"},
    {"publication_id": "p1"},
    {"version_id": "v1"},
    {"publication_sha256": "a" * 64},
    {"content_sha256": "b" * 64},
    {"coverage_status": "NOT_PRESENT"},
])
def test_contradictory_unknown_status_is_unavailable(monkeypatch, changes):
    store, api = make_store(monkeypatch)
    forged = replace(TradingCalendarStatus("UNKNOWN", "ROUTE_UNCONFIGURED"), **changes)
    monkeypatch.setattr(api, "trading_calendar_status", lambda _route: forged)
    result = store.trading_calendar_status()
    assert result["status"] == "UNKNOWN"
    assert result["routes"][ROUTE].reason == "READ_UNAVAILABLE"


def test_invalid_route_is_not_disclosed_or_used(monkeypatch):
    store, api = make_store(monkeypatch)
    store._sdk_exchanges["/private/path"] = {}
    monkeypatch.setattr(api, "trading_calendar_status",
                        lambda _route: TradingCalendarStatus("UNKNOWN", "ROUTE_UNCONFIGURED"))
    result = store.trading_calendar_status()
    assert result["status"] == "UNKNOWN"
    assert result["reason"] == "INVALID_CONFIGURED_ROUTE"
    assert list(result["routes"]) == [ROUTE]
    assert "/private/path" not in repr(result)


def test_no_configured_routes_is_explicitly_unknown(monkeypatch):
    store, _ = make_store(monkeypatch)
    store._sdk_exchanges.clear()
    assert store.trading_calendar_status() == {
        "status": "UNKNOWN", "reason": "ROUTE_UNAVAILABLE", "routes": {},
    }


def test_gateway_constructed_store_does_not_start_a_session(state, monkeypatch):
    example = (Path(bt_api_py.__file__).resolve().parent.parent / "examples/services"
               / "gateway-strategy-client.example.yaml")
    config = yaml.safe_load(example.read_text(encoding="utf-8"))
    binding = GatewayCommandBinding(**config["binding"])
    GatewayPendingHost.upgrade_for_gateway(state.strategy_dir, state.strategy_uuid, binding)
    GatewayPendingHost.upgrade_for_cancellation(state.strategy_dir, state.strategy_uuid, binding)
    GatewayPendingHost.upgrade_for_execution(
        state.strategy_dir, state.strategy_uuid, binding, consumer_ref="gexec:" + "a" * 64
    )
    host = GatewayPendingHost.upgrade_for_order_state(state.strategy_dir, state.strategy_uuid, binding)
    keys = {"security": ClientCurveKeys(b"a" * 40, b"b" * 40, b"c" * 40)}
    store = BtApiStore(config={"gateway_strategy": config}, gateway_host=host,
                       gateway_security_profiles=keys)
    def forbidden(*_args, **_kwargs):
        raise AssertionError("calendar status must not start gateway")
    monkeypatch.setattr(store, "_ensure_api_ready", forbidden)
    result = store.trading_calendar_status()
    assert result["reason"] == "STORE_UNAVAILABLE"
    assert list(result["routes"]) == [ROUTE]
    assert store.gateway_api is None


def test_constructed_read_only_service_does_not_connect(monkeypatch):
    monkeypatch.setattr(proxy_module, "validate_service_account_client",
                        lambda _client: (object(), (object(),)))
    monkeypatch.setattr(proxy_module, "validate_service_market_bindings",
                        lambda *_args, **_kwargs: {})
    proxy = proxy_module.ServiceReadProxy(SimpleNamespace(), {}, valuation_currency="USD",
                                         position_mode="net")
    store = BtApiStore(api=proxy, config={"exchange_kwargs": {ROUTE: {}}})
    def forbidden(*_args, **_kwargs):
        raise AssertionError("calendar status must not connect service")
    monkeypatch.setattr(proxy, "connect", forbidden)
    monkeypatch.setattr(store, "_ensure_api_ready", forbidden)
    assert store.trading_calendar_status()["routes"][ROUTE].reason == "STORE_UNAVAILABLE"


@pytest.mark.parametrize("change", ["stop", "restart", "stream", "api"])
def test_lifecycle_fences_inflight_results(monkeypatch, change):
    store, api = make_store(monkeypatch)
    entered, release = threading.Event(), threading.Event()
    def read(_route):
        entered.set()
        assert release.wait(5)
        return TradingCalendarStatus("UNKNOWN", "ROUTE_UNCONFIGURED")
    monkeypatch.setattr(api, "trading_calendar_status", read)
    result = []
    thread = threading.Thread(target=lambda: result.append(store.trading_calendar_status()))
    thread.start()
    assert entered.wait(5)
    if change == "stop":
        monkeypatch.setattr(module, "_stop_store", lambda *_args, **_kwargs: None)
        store.stop()
        assert store.trading_calendar_status()["reason"] == "STORE_UNAVAILABLE"
    elif change == "restart":
        store.start()
    elif change == "stream":
        store._stream_generation += 1
    else:
        store._api = object()
    release.set()
    thread.join(5)
    assert not thread.is_alive()
    assert result[0]["reason"] == "STORE_CHANGED"
    assert result[0]["routes"][ROUTE].reason == "STORE_CHANGED"


@pytest.mark.parametrize("failure", [False, True])
def test_lifecycle_wrappers_preserve_calls_results_and_exceptions(monkeypatch, failure):
    store, _ = make_store(monkeypatch)
    calls = []
    marker = object()
    error = RuntimeError("lifecycle failure")
    data, broker = object(), object()
    def check_lock():
        acquired = store._calendar_status_lock.acquire(blocking=False)
        assert acquired
        store._calendar_status_lock.release()
    def start(s, actual_data, actual_broker, **kwargs):
        check_lock()
        assert (s, actual_data, actual_broker) == (store, data, broker)
        calls.append("start")
        if failure:
            raise error
        return marker
    def stop(s, timeout, **kwargs):
        check_lock()
        assert s is store and timeout == 2.5
        calls.append("stop")
        if failure:
            raise error
        return marker
    def fence():
        check_lock()
        calls.append("fence")
    monkeypatch.setattr(module, "_start_store", start)
    monkeypatch.setattr(module, "_stop_store", stop)
    store._tick_stream_resync = SimpleNamespace(fence=fence)
    if failure:
        with pytest.raises(RuntimeError) as start_error:
            store.start(data, broker)
        assert start_error.value is error
        with pytest.raises(RuntimeError) as stop_error:
            store.stop(2.5)
        assert stop_error.value is error
    else:
        assert store.start(data, broker) is marker
        assert store.stop(2.5) is marker
    assert calls == ["start", "fence", "stop"]
    assert store._calendar_status_transitions == 0


@pytest.mark.parametrize("mode", ["gateway", "service", "unconfigured", "disconnected"])
def test_unsupported_or_unready_does_not_call_sdk(monkeypatch, mode):
    store, api = make_store(monkeypatch)
    def forbidden(*_args, **_kwargs):
        raise AssertionError("unexpected SDK call")
    monkeypatch.setattr(api, "trading_calendar_status", forbidden)
    monkeypatch.setattr(api, "list_exchanges", forbidden)
    if mode == "gateway":
        store._gateway_mode = True
    elif mode == "service":
        store._service_read_only = True
    elif mode == "unconfigured":
        store._sdk_configured = False
    else:
        store._connected = False
    assert store.trading_calendar_status()["reason"] == "STORE_UNAVAILABLE"
