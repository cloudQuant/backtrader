"""Gateway instrument diagnostics: synthetic DTOs, no network or order actions."""

from dataclasses import replace
import os
from pathlib import Path
import threading
import time
from types import SimpleNamespace

import pytest
import yaml

from backtrader.feeds.btapifeed import BtApiFeed
from backtrader.service.gateway_market_adapter import GatewayMarketAdapter
from backtrader.stores.btapistore import BtApiStore
from bt_api_gateway.instrument_status_forwarding import GatewayInstrumentStatusProjection
from bt_api_py.gateway_api import GatewayBtApi
from bt_api_py.gateway_strategy_config import parse_gateway_strategy_config
from bt_api_py.gateway_strategy_instrument_status import GatewayInstrumentStatusQueryResult

_SDK_QUERY = GatewayBtApi.query_instrument_status


@pytest.fixture
def rig(monkeypatch):
    import bt_api_py

    rel_yaml = "examples/services/gateway-strategy-client.example.yaml"
    root = Path(__file__).resolve().parents[4] / "bt_api_py"
    if not (root / rel_yaml).exists():
        root = Path(bt_api_py.__file__).resolve().parents[1]
    raw = yaml.safe_load(
        (root / rel_yaml).read_text(encoding="utf-8")
    )
    raw["requested_operations"].append("direct.instrument_status")
    config = parse_gateway_strategy_config(raw)
    key = next(iter(config.instruments_by_ref.values()))
    api = object.__new__(GatewayBtApi)
    store = object.__new__(BtApiStore)
    values = {
        "_gateway_mode": True,
        "_service_read_only": False,
        "_started": True,
        "_connected": True,
        "_gateway_closed": False,
        "_gateway_pid": os.getpid(),
        "_gateway_run_lock": SimpleNamespace(held=True),
        "_gateway_strategy_config": config,
        "_api": api,
        "_gateway_session_generation": 1,
        "_calendar_status_generation": 1,
        "_stream_generation": 1,
        "_sdk_exchanges": {config.exchange_name: {}},
        "_calendar_status_transitions": 0,
        "_calendar_status_stopping": False,
        "_calendar_status_lock": threading.Lock(),
    }
    for name, value in values.items():
        setattr(store, name, value)
    state = SimpleNamespace(calls=[], callback=None, response=None, healthy=True)
    monkeypatch.setattr(
        GatewayBtApi, "status", lambda _: SimpleNamespace(state="running", healthy=state.healthy)
    )

    def query(_, route, instrument, *, timeout_seconds):
        state.calls.append((route, instrument, timeout_seconds))
        if state.callback is not None:
            state.callback()
        return state.response

    monkeypatch.setattr(GatewayBtApi, "query_instrument_status", query)
    for method in (
        "reserve_order",
        "dispatch_order",
        "cancel_order",
        "release_order",
        "route_execution_order",
        "cancel_execution_order",
    ):
        if hasattr(GatewayBtApi, method):
            monkeypatch.setattr(
                GatewayBtApi, method, lambda *a, **k: pytest.fail("trade operation")
            )
    client = object()
    monkeypatch.setattr(GatewayBtApi, "market_subscription", lambda *_: client)
    feed = BtApiFeed(
        dataname=key.native_symbol, store=store, provider="btapi", backfill_start=False
    )
    adapter = object.__new__(GatewayMarketAdapter)
    adapter._store, adapter._feed, adapter._api = store, feed, api
    adapter._name, adapter._key = "main", config.market_settings.subscriptions["main"].key
    adapter._lifecycle_lock = threading.RLock()
    adapter._lease_drain_pending = False
    adapter._closed = False
    adapter._lease_mode = False
    adapter._session_generation = 1
    adapter._claim_lock, adapter._claims = threading.Lock(), {"main": adapter}
    store._gateway_market_feed_claims = adapter._claims
    adapter._projector = SimpleNamespace(_client=client)
    feed._gateway_market_adapter = adapter
    feed._session_active = True
    return SimpleNamespace(
        store=store,
        feed=feed,
        api=api,
        config=config,
        raw=raw,
        key=key,
        state=state,
        route=config.exchange_name,
        adapter=adapter,
    )


def observed(key, state):
    is_current = state == "CURRENT"
    projection = GatewayInstrumentStatusProjection(
        venue=key.venue,
        instrument=key.native_symbol,
        session_generation="generation" if is_current else None,
        trading_day="20261117" if is_current else None,
        state=state,
        status_category="continuous" if is_current else "unknown",
        stale=state == "STALE",
        usable=is_current,
        source_sequence=1 if is_current else None,
        received_at=123 if is_current else None,
        receive_clock_domain="monotonic_ns" if is_current else None,
        reason_code={
            "CURRENT": "instrument_status_continuous",
            "STALE": "instrument_status_stale",
            "UNKNOWN": "instrument_status_unavailable",
            "ABSENT": "instrument_status_absent",
        }[state],
    )
    return GatewayInstrumentStatusQueryResult(
        "OBSERVED",
        key,
        registration_id="reg",
        service_epoch="epoch",
        owner_generation="owner",
        projection=projection,
    )


def assert_unavailable(value, key, code="INSTRUMENT_STATUS_UNAVAILABLE"):
    assert type(value) is GatewayInstrumentStatusQueryResult
    assert value.status == "UNAVAILABLE" and value.code == code and value.instrument == key
    assert value.projection is None
    assert value.decision_eligible is False and value.continuity_proven is False
    assert value.authorizes_trading is False and value.product_mapping == "NOT_PROVEN"


@pytest.mark.parametrize("state", ["CURRENT", "STALE", "UNKNOWN", "ABSENT"])
def test_store_and_feed_preserve_detached_observation_and_negative_proofs(rig, state):
    original = observed(rig.key, state)
    rig.state.response = original
    for result in (
        rig.store.gateway_instrument_status(rig.route, rig.key),
        rig.feed.instrument_status_observation(),
    ):
        assert result == original and result is not original
        assert (
            result.instrument is not original.instrument
            and result.projection is not original.projection
        )
        assert result.projection.state == state
        assert result.decision_eligible is False and result.continuity_proven is False
        assert result.authorizes_trading is False and result.projection.authorizes_trading is False
        assert result.product_mapping == "NOT_PROVEN"
    assert len(rig.state.calls) == 2
    assert all(
        call[0] == rig.route and call[1] == rig.key and 0 < call[2] <= 5 for call in rig.state.calls
    )


@pytest.mark.parametrize(
    "code", ["SCOPE_DENIED", "INVALID_REQUEST", "INSTRUMENT_STATUS_UNAVAILABLE"]
)
def test_sdk_unavailable_code_preserved(rig, code):
    rig.state.response = GatewayInstrumentStatusQueryResult("UNAVAILABLE", rig.key, code=code)
    assert_unavailable(rig.feed.instrument_status_observation(), rig.key, code)


def test_unconfigured_operation_and_wrong_route_or_instrument_do_not_query(rig):
    rig.raw["requested_operations"].remove("direct.instrument_status")
    rig.store._gateway_strategy_config = parse_gateway_strategy_config(rig.raw)
    assert_unavailable(rig.store.gateway_instrument_status(rig.route, rig.key), rig.key)
    rig.store._gateway_strategy_config = rig.config
    assert_unavailable(
        rig.store.gateway_instrument_status("OTHER", rig.key), rig.key, "SCOPE_DENIED"
    )
    other = replace(rig.key, environment="other")
    assert_unavailable(rig.store.gateway_instrument_status(rig.route, other), other, "SCOPE_DENIED")
    assert rig.state.calls == []


@pytest.mark.parametrize(
    "name,value",
    [
        ("_api", None),
        ("_gateway_strategy_config", None),
        ("_gateway_run_lock", None),
        ("_gateway_pid", -1),
        ("_gateway_closed", True),
        ("_connected", False),
        ("_started", False),
        ("_calendar_status_transitions", 1),
        ("_calendar_status_stopping", True),
        ("_gateway_mode", False),
        ("_service_read_only", True),
    ],
)
def test_unready_store_never_queries(rig, name, value):
    setattr(rig.store, name, value)
    assert_unavailable(rig.store.gateway_instrument_status(rig.route, rig.key), rig.key)
    assert not rig.state.calls


@pytest.mark.parametrize(
    "name,value",
    [
        ("_api", None),
        ("_gateway_strategy_config", None),
        ("_gateway_run_lock", None),
        ("_gateway_pid", -1),
        ("_gateway_closed", True),
        ("_connected", False),
        ("_started", False),
        ("_gateway_session_generation", 2),
        ("_calendar_status_generation", 2),
        ("_stream_generation", 2),
        ("_calendar_status_transitions", 1),
        ("_calendar_status_stopping", True),
        ("_sdk_exchanges", {"OTHER": {}}),
    ],
)
def test_lifecycle_change_during_rpc_discards_observation(rig, name, value):
    rig.state.response = observed(rig.key, "CURRENT")
    rig.state.callback = lambda: setattr(rig.store, name, value)
    assert_unavailable(rig.store.gateway_instrument_status(rig.route, rig.key), rig.key)
    assert len(rig.state.calls) == 1


def test_lost_lock_or_unhealthy_session_after_rpc_discard(rig):
    rig.state.response = observed(rig.key, "CURRENT")
    rig.state.callback = lambda: setattr(rig.store._gateway_run_lock, "held", False)
    assert_unavailable(rig.store.gateway_instrument_status(rig.route, rig.key), rig.key)
    rig.store._gateway_run_lock.held = True
    rig.state.callback = lambda: setattr(rig.state, "healthy", False)
    assert_unavailable(rig.store.gateway_instrument_status(rig.route, rig.key), rig.key)


def test_lifecycle_change_before_rpc_does_not_call_original_api(rig, monkeypatch):
    def status(_):
        rig.store._stream_generation += 1
        return SimpleNamespace(state="running", healthy=True)

    monkeypatch.setattr(GatewayBtApi, "status", status)
    assert_unavailable(rig.store.gateway_instrument_status(rig.route, rig.key), rig.key)
    assert not rig.state.calls


@pytest.mark.parametrize(
    "damage",
    [
        "wrong_type",
        "wrong_instrument",
        "decision",
        "continuity",
        "authority",
        "mapping",
        "projection_authority",
        "projection_scope",
        "projection_state",
        "bad_code",
    ],
)
def test_forged_or_wrong_sdk_results_are_rejected(rig, damage):
    result = observed(rig.key, "CURRENT")
    if damage == "wrong_type":
        result = {"status": "OBSERVED"}
    elif damage == "wrong_instrument":
        object.__setattr__(result, "instrument", replace(rig.key, venue="OTHER"))
    elif damage == "decision":
        object.__setattr__(result, "decision_eligible", True)
    elif damage == "continuity":
        object.__setattr__(result, "continuity_proven", True)
    elif damage == "authority":
        object.__setattr__(result, "authorizes_trading", True)
    elif damage == "mapping":
        object.__setattr__(result, "product_mapping", "PROVEN")
    elif damage == "projection_authority":
        object.__setattr__(result.projection, "authorizes_trading", True)
    elif damage == "projection_scope":
        object.__setattr__(result.projection, "instrument", "OTHER")
    elif damage == "projection_state":
        object.__setattr__(result.projection, "stale", True)
    else:
        result = GatewayInstrumentStatusQueryResult("UNAVAILABLE", rig.key, code="SCOPE_DENIED")
        object.__setattr__(result, "code", "SECRET")
    rig.state.response = result
    assert_unavailable(rig.store.gateway_instrument_status(rig.route, rig.key), rig.key)


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf"), True, "1"])
def test_invalid_timeout_is_explicit_and_no_query(rig, timeout):
    with pytest.raises(ValueError, match="INVALID_INSTRUMENT_STATUS_TIMEOUT"):
        rig.store.gateway_instrument_status(rig.route, rig.key, timeout_seconds=timeout)
    with pytest.raises(ValueError, match="INVALID_INSTRUMENT_STATUS_TIMEOUT"):
        rig.feed.instrument_status_observation(timeout_seconds=timeout)
    assert not rig.state.calls


def test_exception_and_elapsed_timeout_return_unavailable(rig):
    rig.state.response = observed(rig.key, "CURRENT")

    def fail():
        raise RuntimeError("private exception")

    rig.state.callback = fail
    assert_unavailable(rig.feed.instrument_status_observation(), rig.key)
    rig.state.callback = lambda: time.sleep(0.02)
    assert_unavailable(rig.feed.instrument_status_observation(timeout_seconds=0.005), rig.key)


@pytest.mark.parametrize("mutation", ["store", "adapter", "session", "symbol", "claim"])
def test_feed_binding_change_discards_result(rig, mutation):
    rig.state.response = observed(rig.key, "CURRENT")

    def change():
        if mutation == "store":
            rig.feed.store = None
        elif mutation == "adapter":
            rig.feed._gateway_market_adapter = None
        elif mutation == "session":
            rig.feed._session_active = False
        elif mutation == "symbol":
            rig.feed._dataname = "OTHER"
        else:
            rig.adapter._claims.clear()

    rig.state.callback = change
    assert_unavailable(rig.feed.instrument_status_observation(), rig.key)


def test_unbound_feed_never_infers_instrument_from_symbol(rig):
    rig.feed._gateway_market_adapter = None
    with pytest.raises(ValueError, match="GATEWAY_INSTRUMENT_BINDING_UNAVAILABLE"):
        rig.feed.instrument_status_observation()
    assert not rig.state.calls


def test_invalid_input_cannot_reach_gateway(rig):
    with pytest.raises(ValueError, match="INVALID_INSTRUMENT_STATUS_INSTRUMENT"):
        rig.store.gateway_instrument_status(rig.route, {"native_symbol": rig.key.native_symbol})
    with pytest.raises(ValueError, match="INVALID_INSTRUMENT_STATUS_ROUTE"):
        rig.store.gateway_instrument_status("", rig.key)
    assert not rig.state.calls


@pytest.mark.parametrize(
    "field", ["provider", "venue", "environment", "product_type", "instrument_id", "native_symbol"]
)
def test_all_instrument_dimensions_are_required_for_scope(rig, field):
    other = replace(rig.key, **{field: "other"})
    assert_unavailable(rig.store.gateway_instrument_status(rig.route, other), other, "SCOPE_DENIED")
    assert not rig.state.calls


def test_query_does_not_hold_lifecycle_lock_or_use_order_ports(rig):
    rig.state.response = observed(rig.key, "ABSENT")

    def check_unlocked():
        assert rig.store._calendar_status_lock.acquire(blocking=False)
        rig.store._calendar_status_lock.release()

    rig.state.callback = check_unlocked
    result = rig.feed.instrument_status_observation()
    assert result.status == "OBSERVED" and result.projection.state == "ABSENT"
    assert len(rig.state.calls) == 1


def test_gateway_api_without_enabled_status_client_is_unavailable(rig, monkeypatch):
    # Exercise the SDK's real optional-client branch without connecting it.
    rig.api._instrument_status = None
    monkeypatch.setattr(GatewayBtApi, "_check", lambda _self, route: None)
    monkeypatch.setattr(GatewayBtApi, "query_instrument_status", _SDK_QUERY)
    assert_unavailable(rig.store.gateway_instrument_status(rig.route, rig.key), rig.key)
