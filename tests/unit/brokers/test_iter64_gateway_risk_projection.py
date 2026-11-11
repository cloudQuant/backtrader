"""Iteration 64: Backtrader side of the Risk selection (D64-01, D64-02, U64-5).

UNIT/FAKE: real BT broker, real pending host and real SDK facade; the Risk
client's runtime is never started (its status/call are replaced). No Risk
host, Gateway or socket exists. Nothing here is account or venue evidence.
"""
from types import SimpleNamespace

import pytest
from bt_api_base.risk_service_protocol import RiskOrderResult
from bt_api_py.gateway_api import GatewayBtApi, GatewayRiskRoutedResult
from bt_api_py.gateway_direct_client import GatewayClientResult
from bt_api_py.gateway_execution_time import GatewayExecutionTimePolicy
from bt_api_py.risk_service_client import RiskClientRoute, RiskServiceClient
from bt_api_py.service_runtime_thread import (
    BindingSnapshot,
    RuntimeSnapshot,
    ThreadedServiceClientRuntime,
)

from backtrader.stores.btapistore import BtApiStore, BtApiStoreError
from tests.unit.brokers.test_iter63_gateway_stream_consumer import (
    INSTRUMENT,
    SYNTHETIC_MARKET_REF,
    _limit_order,
    api_for,
    deliver,
    framework,
)
from tests.unit.live_state.conftest import state as state, strategy_dir as strategy_dir
from tests.unit.live_state.test_gateway_execution_checkpoint import ready as ready
from tests.unit.live_state.test_gateway_pending import inputs as inputs
from tests.unit.stores.test_iter63_gateway_store_config import setup_gateway as setup_gateway

OPS = frozenset({"risk.order.reserve", "risk.order.dispatch", "risk.order.release",
                 "risk.order.status"})


# --- Store: a risk key without the Gateway is refused (U64-5) -----------------------------


@pytest.mark.parametrize("value", ["none", {"client_config": {}}, None])
def test_top_level_risk_without_gateway_refuses_to_start(value):
    with pytest.raises(BtApiStoreError) as error:
        BtApiStore(config={"risk": value})
    assert str(error.value) == "risk_requires_gateway" and error.value.code == "risk_requires_gateway"


def test_risk_key_in_direct_sdk_options_refuses_to_start():
    with pytest.raises(BtApiStoreError, match="^risk_requires_gateway$"):
        BtApiStore(config={"exchange_kwargs": {"CTP___FUTURE": {}}, "risk": "none"})
    with pytest.raises(BtApiStoreError, match="^risk_requires_gateway$"):
        BtApiStore(api_kwargs={"risk": "none"})
    with pytest.raises(BtApiStoreError, match="^risk_requires_gateway$"):
        BtApiStore(risk={"connection_file": "state/risk.json"})


def test_store_without_risk_key_is_unchanged():
    store = BtApiStore(config={"exchange_kwargs": {"CTP___FUTURE": {}}}, autostart=False)
    assert store.backend == "direct"


def test_gateway_store_refuses_misplaced_or_missing_risk_selection(setup_gateway):
    from bt_api_py.gateway_strategy_config import GatewayStrategyConfigError

    config, host, keys = setup_gateway
    with pytest.raises(BtApiStoreError, match="^risk_selection_invalid$"):
        BtApiStore(config={"gateway_strategy": config, "risk": "none"}, gateway_host=host,
                   gateway_security_profiles=keys)
    missing = dict(config)
    missing.pop("risk")
    with pytest.raises(GatewayStrategyConfigError, match="^risk_selection_missing$"):
        BtApiStore(config={"gateway_strategy": missing}, gateway_host=host,
                   gateway_security_profiles=keys)
    assert BtApiStore(config={"gateway_strategy": config}, gateway_host=host,
                      gateway_security_profiles=keys).gateway_strategy_config.risk_selection is None


# --- Broker projection of results routed through Risk ------------------------------------


def _risk_api(host, route):
    """A real risk-selected facade whose Risk runtime is never started."""
    plain = api_for(host, route)
    risk = RiskServiceClient(ThreadedServiceClientRuntime(lambda: None), route=RiskClientRoute(
        "broker.risk_order", "risk", "risk-a", "risk-scope", route.scope, route.identity))
    return GatewayBtApi(plain._session, exchange_name="CTP___FUTURE", risk_client=risk)


def _bound(state, ready, inputs, monkeypatch):
    from backtrader.live_state.gateway_pending import GatewayPendingHost

    _, binding, _ = ready
    host = GatewayPendingHost.upgrade_for_order_state(state.strategy_dir, state.strategy_uuid, binding)
    state.sequence.allocate()  # the fixture's key-a owns local sequence 1
    api = _risk_api(host, inputs[1])
    data, broker, strategy = framework()
    monkeypatch.setattr(broker, "_gateway_require_trade_qualification", lambda *_: SYNTHETIC_MARKET_REF)
    broker.bind_gateway_execution_stream(strategy, api=api, host=host, data_by_ref={"rb": data},
        orders_by_key={}, instrument_by_ref={"rb": INSTRUMENT},
        time_policy=GatewayExecutionTimePolicy("CTP___FUTURE", "UTC"), sequence=state.sequence)
    return host, api, data, broker, strategy


def _risk_wire(api, monkeypatch, replies, *, registered=True):
    route = api._risk.route
    binding = BindingSnapshot("reg-1", "epoch-1", True, route.mount, route.service_id,
                              route.instance_id, route.scope_ref, route.scope, OPS, True)
    snap = RuntimeSnapshot("running" if registered else "failed", registered, registered, None,
                           (binding,), 0, 0, route.identity, route.scope.run_id)
    calls = []
    runtime = api._risk._runtime
    monkeypatch.setattr(runtime, "status", lambda: snap)

    def call(mount, operation, arguments, **kwargs):
        calls.append((operation, dict(arguments)))
        return replies.pop(0)

    monkeypatch.setattr(runtime, "call", call)
    return calls


def _no_gateway_place(api, monkeypatch):
    for name in ("reserve", "dispatch", "cancel"):
        monkeypatch.setattr(api._command, name,
                            lambda *a, _n=name, **kw: pytest.fail("Gateway " + _n + " called"))


def test_risk_refusal_rejects_with_lowercase_info_and_upper_case_notice(state, ready, inputs,
                                                                         monkeypatch):
    host, api, data, broker, strategy = _bound(state, ready, inputs, monkeypatch)
    _no_gateway_place(api, monkeypatch)
    order = _limit_order(strategy, data)
    key_holder = {}

    def denied():
        return RiskOrderResult(key_holder["key"], "DENIED", state="DENIED",
                               code="risk_order_quantity_exceeds_cap").to_mapping()

    replies = []
    calls = _risk_wire(api, monkeypatch, replies)
    original = api._risk.reserve

    def reserve(request, *, request_key, **kw):
        key_holder["key"] = request_key
        replies.append(denied())
        return original(request, request_key=request_key, **kw)

    monkeypatch.setattr(api._risk, "reserve", reserve)
    broker.submit(order)
    key = order.info.gateway_request_key
    assert [c[0] for c in calls] == ["risk.order.reserve"] and calls[0][1]["request_key"] == key
    assert order.status == order.Rejected and not order.executed.size
    assert order.info.risk_denied == "risk_order_quantity_exceeds_cap"
    assert order.info.get("gateway_request_denied") is None
    assert host.local_order_notifications()["reject:" + key]["code"] == "RISK_ORDER_QUANTITY_EXCEEDS_CAP"
    assert broker.gateway_risk_summary()["refusals"] == {"risk_order_quantity_exceeds_cap": 1}


def test_unavailable_risk_rejects_and_never_reaches_the_gateway(state, ready, inputs, monkeypatch):
    host, api, data, broker, strategy = _bound(state, ready, inputs, monkeypatch)
    _no_gateway_place(api, monkeypatch)
    calls = _risk_wire(api, monkeypatch, [], registered=False)
    order = _limit_order(strategy, data)
    broker.submit(order)
    key = order.info.gateway_request_key
    assert calls == []  # the request never left the process
    assert order.status == order.Rejected and order.info.risk_denied == "risk_unavailable"
    assert host.local_order_notifications()["reject:" + key]["code"] == "RISK_UNAVAILABLE"
    assert host.load_intent(key) is not None  # durable before any attempt


def test_gateway_refusal_through_risk_keeps_the_gateway_projection(state, ready, inputs, monkeypatch):
    host, api, data, broker, strategy = _bound(state, ready, inputs, monkeypatch)
    monkeypatch.setattr(api, "reserve_order", lambda route, request, **kw: GatewayRiskRoutedResult(
        "REQUEST_DENIED", code="CONTROL_STOP_NEW", risk_code="risk_gateway_refused"))
    order = _limit_order(strategy, data)
    broker.submit(order)
    key = order.info.gateway_request_key
    assert order.status == order.Rejected
    assert order.info.gateway_request_denied == "CONTROL_STOP_NEW"
    assert order.info.get("risk_denied") is None
    assert host.local_order_notifications()["reject:" + key]["code"] == "CONTROL_STOP_NEW"
    assert broker.gateway_risk_summary()["refusals"] == {"risk_gateway_refused": 1}


@pytest.mark.parametrize("result", [
    GatewayRiskRoutedResult("UNKNOWN", code="RISK_OUTCOME_UNKNOWN"),
    GatewayRiskRoutedResult("TRANSPORT_NOT_STARTED", code="INTENT_NOT_DURABLE"),
])
def test_risk_unknown_keeps_the_order_pending_without_a_fake_rejection(state, ready, inputs,
                                                                       monkeypatch, result):
    host, api, data, broker, strategy = _bound(state, ready, inputs, monkeypatch)
    monkeypatch.setattr(api, "reserve_order", lambda route, request, **kw: result)
    monkeypatch.setattr(api, "dispatch_order", lambda *a, **kw: pytest.fail("dispatched"))
    order = _limit_order(strategy, data)
    broker.submit(order)
    key = order.info.gateway_request_key
    assert order.status == order.Submitted
    assert broker._gateway_stream_binding.state == "SUBMIT_UNKNOWN"
    assert "reject:" + key not in host.local_order_notifications()
    assert order.info.get("risk_denied") is None
    assert broker.gateway_risk_summary()["refusals"] == {}


def test_risk_refusal_survives_restart_replay(state, ready, inputs, monkeypatch):
    host, api, data, broker, strategy = _bound(state, ready, inputs, monkeypatch)
    monkeypatch.setattr(api, "reserve_order", lambda route, request, **kw: GatewayRiskRoutedResult(
        "REQUEST_DENIED", code="RISK_DUPLICATE_ORDER", risk_code="risk_duplicate_order",
        risk_denied="risk_duplicate_order"))
    order = _limit_order(strategy, data)
    broker.submit(order)
    key = order.info.gateway_request_key
    # Restart before the strategy saw the notification: the same notice replays.
    data2, broker2, strategy2 = framework()
    broker2.bind_gateway_execution_stream(strategy2, api=api, host=host, data_by_ref={"rb": data2},
        orders_by_key={}, instrument_by_ref={"rb": INSTRUMENT},
        time_policy=GatewayExecutionTimePolicy("CTP___FUTURE", "UTC"), sequence=state.sequence)
    replayed = [n for n in (broker2.get_notification(), broker2.get_notification()) if n is not None]
    rejected = [n for n in replayed if n.status == n.Rejected]
    assert len(rejected) == 1 and rejected[0].info.risk_denied == "risk_duplicate_order"
    assert host.local_order_notifications()["reject:" + key]["code"] == "RISK_DUPLICATE_ORDER"


def test_none_selection_still_dispatches_through_the_gateway(state, ready, inputs, monkeypatch):
    from backtrader.live_state.gateway_pending import GatewayPendingHost
    from tests.unit.live_state.test_gateway_pending import observe

    _, binding, _ = ready
    host = GatewayPendingHost.upgrade_for_order_state(state.strategy_dir, state.strategy_uuid, binding)
    state.sequence.allocate()
    api = api_for(host, inputs[1])
    assert api.risk_selected is False
    data, broker, strategy = framework()
    monkeypatch.setattr(broker, "_gateway_require_trade_qualification", lambda *_: SYNTHETIC_MARKET_REF)
    broker.bind_gateway_execution_stream(strategy, api=api, host=host, data_by_ref={"rb": data},
        orders_by_key={}, instrument_by_ref={"rb": INSTRUMENT},
        time_policy=GatewayExecutionTimePolicy("CTP___FUTURE", "UTC"), sequence=state.sequence)
    calls = []

    def reserve(route, request, *, timeout_seconds):
        record = observe(host.load_intent(request.idempotency_key))
        host.save_record(request.idempotency_key, record)
        calls.append("reserve")
        return GatewayClientResult("OBSERVED", record)

    monkeypatch.setattr(api, "reserve_order", reserve)
    monkeypatch.setattr(api, "dispatch_order", lambda route, key, **kw: (
        calls.append("dispatch") or GatewayClientResult("QUEUED", host.load_record(key))))
    order = _limit_order(strategy, data)
    broker.submit(order)
    assert calls == ["reserve", "dispatch"] and order.status == order.Submitted
    deliver(broker, strategy)


# --- Gateway execution summary -------------------------------------------------------------


@pytest.mark.parametrize("selected,available", [(True, False), (True, True), (False, None)])
def test_gateway_execution_summary_reports_risk(selected, available):
    from backtrader.brokers.btapibroker import BtApiBroker

    broker = BtApiBroker()
    broker.store = SimpleNamespace(
        _gateway_mode=True,
        gateway_strategy_config=SimpleNamespace(risk_selection=object() if selected else None),
        gateway_api=SimpleNamespace(risk_available=available),
    )
    broker._gateway_risk_refusals = {"risk_unavailable": 2}
    summary = broker.get_execution_summary()
    assert summary["risk"] == {"selected": selected, "available": available,
                               "refusals": {"risk_unavailable": 2}}
    assert summary["trading_blocked"] is True  # the rest of the view is unchanged


def test_non_gateway_summary_has_no_risk_section():
    from backtrader.brokers.btapibroker import BtApiBroker

    broker = BtApiBroker()
    broker.store = SimpleNamespace(_gateway_mode=False)
    assert "risk" not in broker.get_execution_summary()
