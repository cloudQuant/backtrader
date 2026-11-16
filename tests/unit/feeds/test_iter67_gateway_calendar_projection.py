"""Gateway calendar projections using bounded, synthetic SDK DTOs only."""

import datetime as dt
import os
import threading
from types import SimpleNamespace

import pytest

from backtrader.feeds.btapifeed import BtApiFeed
from backtrader.stores.btapistore import BtApiStore
from bt_api_py.gateway_api import GatewayBtApi
from bt_api_py.gateway_strategy_calendar import GatewayCalendarQueryResult
from bt_api_py.gateway_strategy_config import GatewayStrategyConfig
from tests.unit.live_state.conftest import state, strategy_dir  # noqa: F401
from tests.unit.stores.test_iter63_gateway_store_config import (
    make_store,
    setup_gateway,
)

ROUTE = "CTP___FUTURE"
MONDAY = dt.date(2026, 10, 12)
TUESDAY = dt.date(2026, 10, 13)
UTC = dt.timezone.utc


def wire(day, contract="cu2601", *, generation="g1", registration="r1", epoch="e1",
         version="v1", bound=MONDAY, load="CURRENT", empty=False):
    scope = {"mode": "SIMULATION_ONLY", "route": ROUTE, "venue": "XSH", "kind": "future",
             "product": "cu", "contract": contract, "trading_day": day.isoformat()}
    morning = dt.datetime.combine(day, dt.time(1), UTC)
    stamp = lambda value: value.isoformat().replace("+00:00", "Z")
    windows = [] if empty else [
        {"window_id": "day", "phase": "continuous", "start_utc": stamp(morning),
         "end_utc": stamp(morning + dt.timedelta(hours=2))}
    ]
    if day == MONDAY and not empty:
        windows.insert(0, {"window_id": "night", "phase": "continuous",
                           "start_utc": "2026-10-09T13:00:00Z",
                           "end_utc": "2026-10-09T17:00:00Z"})
    return {
        "schema": "sdk.gateway.calendar.query/1", "scope": scope,
        "registration_id": registration, "service_epoch": epoch,
        "status": "COMPLETE", "reason": "OK",
        "binding": {
            "route": ROUTE, "source_generation": generation, "bound_trading_day": bound.isoformat(),
            "calendar_ref": version, "publication_id": "p" + version,
            "content_sha256": "a" * 64, "coverage_manifest_sha256": "b" * 64,
            "binding_sha256": "c" * 64, "version_sha256": "d" * 64,
            "coverage_status": "DECLARED_UNVERIFIED", "coverage_start": "2026-10-01",
            "coverage_end": "2026-12-31", "load_status": load, "data_origin": "UNSPECIFIED",
        },
        "venue_day": {"status": "COMPLETE", "day_status": "open"}, "windows": windows,
        "source_authentication": "NOT_PROVEN", "trade_authorization": "NONE",
    }


@pytest.fixture
def gateway(monkeypatch):
    api = object.__new__(GatewayBtApi)
    config = SimpleNamespace(calendar_settings=object())
    lock = SimpleNamespace(held=True)
    store = object.__new__(BtApiStore)
    for name, value in {
        "_gateway_mode": True, "_service_read_only": False, "_started": True,
        "_connected": True, "_gateway_closed": False, "_gateway_pid": os.getpid(),
        "_gateway_run_lock": lock, "_gateway_strategy_config": config, "_api": api,
        "_gateway_session_generation": 0, "_calendar_status_generation": 0,
        "_stream_generation": 0, "_sdk_exchanges": {ROUTE: {}},
        "_calendar_status_transitions": False, "_calendar_status_stopping": False,
        "_calendar_status_lock": threading.RLock(),
    }.items():
        setattr(store, name, value)
    monkeypatch.setattr(GatewayBtApi, "status", lambda self: SimpleNamespace(state="running", healthy=True))
    state = {"generation": "g1", "registration": "r1", "epoch": "e1", "version": "v1",
             "bound": MONDAY, "load": "CURRENT", "empty": False, "calls": [], "fail": False}

    def query(self, exchange_name, **kwargs):
        state["calls"].append(kwargs)
        assert exchange_name == ROUTE and kwargs["timeout_seconds"] == 5.0
        if state["fail"]:
            raise RuntimeError("offline")
        return GatewayCalendarQueryResult.from_wire(wire(
            dt.date.fromisoformat(kwargs["trading_day"]), kwargs["contract"],
            **{key: state[key] for key in ("generation", "registration", "epoch", "version", "bound", "load", "empty")}
        ))

    monkeypatch.setattr(GatewayBtApi, "trading_calendar_query", query)
    return store, state


def feed(store, contract="cu2601"):
    return BtApiFeed(dataname=contract, store=store, provider="btapi", calendar_route=ROUTE,
                     calendar_venue="XSH", calendar_kind="future", calendar_product="cu",
                     calendar_contract=contract)


def test_two_feeds_fixed_version_night_future_and_generations(gateway):
    store, state = gateway
    first, second = feed(store), feed(store, "cu2602")
    a = first.trading_session(trading_day=MONDAY, at=dt.datetime(2026, 10, 9, 14, tzinfo=UTC))
    b = second.trading_session(trading_day=MONDAY)
    assert (a.status, a.phase, a.active, a.active_window.window_id) == ("COMPLETE", "continuous", True, "night")
    assert a.gateway_binding == b.gateway_binding and a.gateway_binding.calendar_ref == "v1"
    assert (a.gateway_binding.source_authentication, a.gateway_binding.trade_authorization) == (
        "NOT_PROVEN", "NONE"
    )
    assert a.source_ids == () and a.source_classification == "UNVERIFIED" and a.account_use == "NOT_AUTHORIZED"
    assert first.trading_calendar_binding().reason == "FRESH_QUERY_REQUIRED"
    future = first.trading_windows(dt.datetime(2026, 10, 13, 1, tzinfo=UTC),
                                   dt.datetime(2026, 10, 13, 2, tzinfo=UTC))
    assert future.status == "COMPLETE" and future.windows[0].trading_day == TUESDAY
    assert future.gateway_binding == a.gateway_binding
    assert first.trading_session(trading_day=MONDAY).calendar_ref == "v1"
    state["registration"] = "r2"
    assert first.trading_session(trading_day=MONDAY).gateway_binding.registration_id == "r2"
    state.update(generation="g2", epoch="e2", version="v2", bound=TUESDAY)
    store._gateway_session_generation += 1
    updated = first.trading_session(trading_day=TUESDAY)
    assert updated.calendar_ref == "v2" and updated.gateway_binding.registration_id == "r2"
    assert second.trading_session(trading_day=TUESDAY).gateway_binding == updated.gateway_binding
    assert len(state["calls"]) == 7


def test_gateway_empty_failure_and_stale_never_invent_active(gateway):
    store, state = gateway
    value = feed(store)
    state["empty"] = True
    empty = value.trading_session(trading_day=MONDAY, at=dt.datetime(2026, 10, 12, 1, tzinfo=UTC))
    assert (empty.status, empty.reason, empty.phase, empty.active) == ("COMPLETE", "NO_WINDOWS_RETURNED", "unknown", None)
    state.update(empty=False, load="STALE")
    stale = value.trading_session(trading_day=MONDAY, at=dt.datetime(2026, 10, 12, 1, tzinfo=UTC))
    assert (stale.status, stale.reason, stale.phase, stale.active) == ("STALE", "GATEWAY_BINDING_STALE", "unknown", None)
    assert stale.windows and stale.gateway_binding.load_status == "STALE"
    stale_windows = value.trading_windows(dt.datetime(2026, 10, 12, 1, tzinfo=UTC),
                                          dt.datetime(2026, 10, 12, 2, tzinfo=UTC))
    assert (stale_windows.status, stale_windows.reason, stale_windows.stale) == (
        "STALE", "GATEWAY_BINDING_STALE", True
    )
    state["fail"] = True
    failed = value.trading_session(trading_day=MONDAY)
    assert (failed.status, failed.reason, failed.phase, failed.active, failed.windows) == ("UNKNOWN", "READ_UNAVAILABLE", "unknown", None, ())


def test_gateway_stale_binding_survives_an_unanswered_day(gateway, monkeypatch):
    store, _ = gateway

    def unanswered(_self, _exchange, **kwargs):
        response = wire(dt.date.fromisoformat(kwargs["trading_day"]), load="STALE")
        response.update(status="UNKNOWN", reason="QUERY_UNAVAILABLE", windows=[])
        response["venue_day"] = {"status": "UNKNOWN", "day_status": None}
        return GatewayCalendarQueryResult.from_wire(response)

    monkeypatch.setattr(GatewayBtApi, "trading_calendar_query", unanswered)
    value = feed(store)
    session = value.trading_session(trading_day=MONDAY)
    assert (session.status, session.reason, session.phase, session.active) == (
        "STALE", "GATEWAY_BINDING_STALE", "unknown", None
    )
    assert session.windows == () and session.gateway_binding.calendar_ref == "v1"
    windows = value.trading_windows(dt.datetime(2026, 10, 12, 1, tzinfo=UTC),
                                    dt.datetime(2026, 10, 12, 2, tzinfo=UTC))
    assert (windows.status, windows.reason, windows.stale) == ("UNKNOWN", "QUERY_UNAVAILABLE", True)
    assert windows.incomplete is True and windows.windows == ()
    assert len(windows.gaps) == 1
    assert (windows.gaps[0].trading_day, windows.gaps[0].reason) == (MONDAY, "QUERY_UNAVAILABLE")
    assert (windows.calendar_ref, windows.publication_id, windows.content_sha256) == (
        "v1", "pv1", "a" * 64
    )
    assert windows.coverage_status == "DECLARED_UNVERIFIED"
    assert windows.gateway_binding.calendar_ref == "v1"


def test_store_rejects_mode_scope_and_changed_session(gateway, monkeypatch):
    store, state = gateway
    fields = dict(venue="XSH", kind="future", product="cu", contract="cu2601", trading_day=MONDAY)
    assert store.trading_calendar_query(ROUTE, **fields).reason == "SIMULATION_MODE_REQUIRED"
    assert store.trading_calendar_query("OTHER", mode="SIMULATION_ONLY", **fields).reason == "ROUTE_UNCONFIGURED"
    original = GatewayBtApi.trading_calendar_query

    def replace_session(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        store._gateway_session_generation += 1
        return result

    monkeypatch.setattr(GatewayBtApi, "trading_calendar_query", replace_session)
    assert store.trading_calendar_query(ROUTE, mode="SIMULATION_ONLY", **fields).reason == "STORE_CHANGED"


def test_gateway_does_not_mix_generation_across_days(gateway, monkeypatch):
    store, state = gateway
    value = feed(store)
    original = GatewayBtApi.trading_calendar_query
    calls = []

    def change_generation(self, *args, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            state["generation"] = "g2"
        return original(self, *args, **kwargs)

    monkeypatch.setattr(GatewayBtApi, "trading_calendar_query", change_generation)
    result = value.trading_windows(dt.datetime(2026, 10, 12, 1, tzinfo=UTC),
                                   dt.datetime(2026, 10, 13, 2, tzinfo=UTC))
    assert (result.status, result.reason, result.windows) == ("UNKNOWN", "CONFIGURATION_CHANGED", ())
    assert len(calls) == 2


def test_gateway_friday_night_range_is_unknown_without_day_owner_index(gateway, monkeypatch):
    store, _ = gateway
    original = GatewayBtApi.trading_calendar_query

    def bounded(self, *args, **kwargs):
        if kwargs["trading_day"] == "2026-10-09":
            response = wire(MONDAY)
            response["scope"]["trading_day"] = "2026-10-09"
            response.update(status="OUT_OF_SCOPE", reason="DAY_OUT_OF_RANGE", windows=[])
            response["venue_day"] = {"status": "UNKNOWN", "day_status": None}
            return GatewayCalendarQueryResult.from_wire(response)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(GatewayBtApi, "trading_calendar_query", bounded)
    value = feed(store)
    assert value.trading_session(trading_day=MONDAY, at=dt.datetime(2026, 10, 9, 14, tzinfo=UTC)).active is True
    windows = value.trading_windows(dt.datetime(2026, 10, 9, 13, tzinfo=UTC),
                                    dt.datetime(2026, 10, 9, 14, tzinfo=UTC))
    assert (windows.status, windows.reason, windows.windows) == ("UNKNOWN", "DAY_OUT_OF_RANGE", ())


def test_gateway_missing_config_and_changed_scope_are_unavailable(gateway, monkeypatch):
    store, state = gateway
    fields = dict(venue="XSH", kind="future", product="cu", contract="cu2601", trading_day=MONDAY)
    store._gateway_strategy_config.calendar_settings = None
    store._calendar_local_reader = SimpleNamespace(query=lambda *_a, **_k: pytest.fail("local fallback"))
    assert store.trading_calendar_query(ROUTE, mode="SIMULATION_ONLY", **fields).reason == "CAPABILITY_UNAVAILABLE"
    assert not state["calls"]
    store._gateway_strategy_config.calendar_settings = object()
    original = GatewayBtApi.trading_calendar_query

    def wrong_scope(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        changed = wire(MONDAY, "cu2602")
        return GatewayCalendarQueryResult.from_wire(changed)

    monkeypatch.setattr(GatewayBtApi, "trading_calendar_query", wrong_scope)
    assert store.trading_calendar_query(ROUTE, mode="SIMULATION_ONLY", **fields).reason == "READ_UNAVAILABLE"

    def changed_config(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        store._gateway_strategy_config.calendar_settings = object()
        return result

    monkeypatch.setattr(GatewayBtApi, "trading_calendar_query", changed_config)
    assert store.trading_calendar_query(ROUTE, mode="SIMULATION_ONLY", **fields).reason == "STORE_CHANGED"


def test_real_store_gateway_lifecycle_closes_original_fake_facade(setup_gateway, monkeypatch):
    config, host, keys = setup_gateway
    bindings = config["client_config"]["clients"]["gateway"]["settings"]["bindings"]
    direct = next(row for row in bindings if row["mount"] == "broker.direct_write")
    bindings.append({**direct, "mount": "store.calendar"})
    config["calendar_settings"] = {
        "mode": "SIMULATION_ONLY",
        "scopes": [{"route": ROUTE, "venue": "XSH", "kind": "future", "product": "cu",
                    "contract": "cu2601"}],
    }
    facade = object.__new__(GatewayBtApi)
    state = {"running": False, "closes": 0}

    def status(_self):
        return SimpleNamespace(state="running" if state["running"] else "closed",
                               healthy=state["running"], thread_alive=state["running"],
                               cleanup_failures=0, unregister_uncertainties=0,
                               owner_cleanup_uncertainties=0)

    def start(_self, *, timeout_seconds):
        state["running"] = True
        return status(_self)

    def close(_self, *, timeout_seconds):
        state.update(running=False, closes=state["closes"] + 1)
        return status(_self)

    monkeypatch.setattr(GatewayStrategyConfig, "create_api", lambda *_a, **_k: facade)
    monkeypatch.setattr(GatewayBtApi, "start", start)
    monkeypatch.setattr(GatewayBtApi, "status", status)
    monkeypatch.setattr(GatewayBtApi, "close", close)
    monkeypatch.setattr(GatewayBtApi, "trading_calendar_query", lambda _self, _route, **kw:
                        GatewayCalendarQueryResult.from_wire(wire(dt.date.fromisoformat(kw["trading_day"]))))
    store = make_store((config, host, keys))
    store.start()
    assert feed(store).trading_session(trading_day=MONDAY).status == "COMPLETE"
    store.stop()
    assert store.gateway_api is None and state["closes"] == 1
    assert not state["running"] and host.list_intents() == ()
