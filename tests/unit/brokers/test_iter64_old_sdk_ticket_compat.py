"""Ticket-call preflight with temporary BT state, not real SDK/venue evidence.

The old-signature substitute matches GatewayBtApi.reserve_order at SDK commit
0fa0754264c41c03ea6209bb6fe2824d36d441a0. It is not an installed old wheel.
"""

from types import MethodType, SimpleNamespace

import pytest
from bt_api_py._contracts.models import OrderRequest
from bt_api_py.gateway_api import GatewayRiskRoutedResult

from backtrader.brokers._btapi_gateway_stream import GatewayExecutionStreamError
from tests.unit.brokers.test_iter63_gateway_stream_consumer import _limit_order
from tests.unit.brokers.test_iter64_gateway_risk_projection import (
    _bound,
    inputs as inputs,
    ready as ready,
    state as state,
    strategy_dir as strategy_dir,
)

CONTRACT = "local-first-send-ticket-v1"


def _deny_writes(api, monkeypatch):
    calls = []
    for label, client, names in (
        ("gateway", api._command, ("reserve", "dispatch", "release", "cancel")),
        ("risk", api._risk, ("reserve", "dispatch", "release")),
        ("delegated", api._delegated, ("cancel",)),
    ):
        if client is None:
            continue
        for name in names:
            monkeypatch.setattr(client, name,
                                lambda *a, _label=label, _name=name, **kw: calls.append((_label, _name)))
    return calls


def test_write_spies_cover_real_fake_client_methods(state, ready, inputs, monkeypatch):
    _host, api, _data, _broker, _strategy = _bound(state, ready, inputs, monkeypatch)
    calls = _deny_writes(api, monkeypatch)
    for client, names in ((api._command, ("reserve", "dispatch", "release", "cancel")),
                          (api._risk, ("reserve", "dispatch", "release")),
                          (api._delegated, ("cancel",))):
        for name in names:
            getattr(client, name)()
    assert calls == [("gateway", "reserve"), ("gateway", "dispatch"), ("gateway", "release"),
                     ("gateway", "cancel"), ("risk", "reserve"), ("risk", "dispatch"),
                     ("risk", "release"), ("delegated", "cancel")]


def _assert_preflight_refusal(host, api, data, broker, strategy, monkeypatch, order=None):
    calls = _deny_writes(api, monkeypatch)
    # A failed preflight must precede even a market-qualification callback.
    monkeypatch.setattr(broker, "_gateway_require_trade_qualification",
                        lambda *_: pytest.fail("qualification called"))
    monkeypatch.setattr(broker, "_gateway_strategy_position_observation",
                        lambda *_a, **_kw: pytest.fail("position RPC called"))
    before_seq = broker._gateway_stream_binding.sequence.read()
    before_intents = tuple(host.list_intents())
    before_local = host.local_order_notifications()
    before_orders = dict(broker.orders)
    before_notifications = list(broker.notifs)
    if order is None:
        order = _limit_order(strategy, data)
    before_info = dict(order.info)
    with pytest.raises(GatewayExecutionStreamError, match="^GATEWAY_STREAM_RISK_TICKET_CONTRACT_UNSUPPORTED$"):
        broker.submit(order)
    assert order.status == order.Created and order.executed.size == 0
    assert dict(order.info) == before_info
    assert broker._gateway_stream_binding.sequence.read() == before_seq
    assert tuple(host.list_intents()) == before_intents
    assert host.local_order_notifications() == before_local
    assert broker.orders == before_orders
    assert list(broker.notifs) == before_notifications
    assert calls == []


def test_old_sdk_signature_is_refused_before_new_intent(state, ready, inputs, monkeypatch):
    host, api, data, broker, strategy = _bound(state, ready, inputs, monkeypatch)

    def old_reserve_order(self, exchange_name, request: OrderRequest, *, ttl_seconds=10.0,
                          timeout_seconds=5.0):
        pytest.fail("old SDK body must not run")

    monkeypatch.setattr(api, "reserve_order", MethodType(old_reserve_order, api))
    _assert_preflight_refusal(host, api, data, broker, strategy, monkeypatch)


@pytest.mark.parametrize("invalid", [
    None,
    "local-first-send-ticket-v1",
    (),
    ("unknown", lambda: None),
    (CONTRACT, lambda: None),
    (CONTRACT, object()),
])
def test_missing_or_invalid_contract_is_refused(state, ready, inputs, monkeypatch, invalid):
    host, api, data, broker, strategy = _bound(state, ready, inputs, monkeypatch)
    monkeypatch.setattr(api, "risk_first_send_reserve_contract", lambda: invalid)
    _assert_preflight_refusal(host, api, data, broker, strategy, monkeypatch)


def test_contract_attribute_exception_is_refused(state, ready, inputs, monkeypatch):
    host, api, data, broker, strategy = _bound(state, ready, inputs, monkeypatch)

    def unavailable(_self):
        raise RuntimeError("private failure")

    monkeypatch.setattr(type(api), "risk_first_send_reserve_contract", property(unavailable))
    _assert_preflight_refusal(host, api, data, broker, strategy, monkeypatch)


def test_missing_contract_method_is_refused(state, ready, inputs, monkeypatch):
    host, api, data, broker, strategy = _bound(state, ready, inputs, monkeypatch)
    monkeypatch.delattr(type(api), "risk_first_send_reserve_contract")
    _assert_preflight_refusal(host, api, data, broker, strategy, monkeypatch)


def test_unsupported_close_fails_before_position_read(state, ready, inputs, monkeypatch):
    host, api, data, broker, strategy = _bound(state, ready, inputs, monkeypatch)
    monkeypatch.setattr(api, "risk_first_send_reserve_contract", lambda: None)
    order = _limit_order(strategy, data)
    order.addinfo(offset="close")
    _assert_preflight_refusal(host, api, data, broker, strategy, monkeypatch, order=order)


@pytest.mark.parametrize("selected", [None, 1, "true"])
def test_non_boolean_risk_selection_is_refused(state, ready, inputs, monkeypatch, selected):
    host, api, data, broker, strategy = _bound(state, ready, inputs, monkeypatch)
    monkeypatch.setattr(type(api), "risk_selected", property(lambda _self: selected))
    _assert_preflight_refusal(host, api, data, broker, strategy, monkeypatch)


def test_missing_selection_cannot_hide_a_selected_risk_client(state, ready, inputs, monkeypatch):
    host, api, data, broker, strategy = _bound(state, ready, inputs, monkeypatch)
    monkeypatch.delattr(type(api), "risk_selected")
    _assert_preflight_refusal(host, api, data, broker, strategy, monkeypatch)


def test_gateway_without_selection_property_is_refused_even_for_nonrisk_config(state, ready, inputs, monkeypatch):
    host, api, data, broker, strategy = _bound(state, ready, inputs, monkeypatch)
    monkeypatch.setattr(api, "_risk", None)
    monkeypatch.delattr(type(api), "risk_selected")
    broker.store.gateway_strategy_config = SimpleNamespace(risk_selection=None)
    broker.store._gateway_mode = True
    monkeypatch.setattr(broker, "_gateway_stream_check", lambda _binding: None)
    _assert_preflight_refusal(host, api, data, broker, strategy, monkeypatch)


def test_callable_bound_to_different_facade_is_refused(state, ready, inputs, monkeypatch):
    host, api, data, broker, strategy = _bound(state, ready, inputs, monkeypatch)
    other = object()
    method = MethodType(lambda _self, *_args, **_kwargs: None, other)
    monkeypatch.setattr(api, "risk_first_send_reserve_contract",
                        lambda: (CONTRACT, method, host.risk_first_send_host_contract()))
    _assert_preflight_refusal(host, api, data, broker, strategy, monkeypatch)


def test_callable_cannot_spoof_bound_facade_with_an_attribute(state, ready, inputs, monkeypatch):
    host, api, data, broker, strategy = _bound(state, ready, inputs, monkeypatch)

    class Spoof:
        __self__ = api

        def __call__(self, *_args, **_kwargs):
            pytest.fail("spoof callable must not run")

    monkeypatch.setattr(api, "risk_first_send_reserve_contract",
                        lambda: (CONTRACT, Spoof(), host.risk_first_send_host_contract()))
    _assert_preflight_refusal(host, api, data, broker, strategy, monkeypatch)


def test_host_without_explicit_ticket_contract_is_refused(state, ready, inputs, monkeypatch):
    host, api, data, broker, strategy = _bound(state, ready, inputs, monkeypatch)
    monkeypatch.delattr(type(host), "risk_first_send_host_contract")
    _assert_preflight_refusal(host, api, data, broker, strategy, monkeypatch)


@pytest.mark.parametrize("kind", ["missing", "short", "version", "save", "create", "consume"])
def test_malformed_host_contract_is_refused(state, ready, inputs, monkeypatch, kind):
    host, api, data, broker, strategy = _bound(state, ready, inputs, monkeypatch)
    contract = list(host.risk_first_send_host_contract())
    if kind == "missing":
        host_contract = None
    elif kind == "short":
        host_contract = tuple(contract[:3])
    else:
        index = {"version": 0, "save": 1, "create": 2, "consume": 3}[kind]
        contract[index] = "wrong-host-version" if index == 0 else (lambda *_a, **_kw: None)
        host_contract = tuple(contract)
    reserve = MethodType(lambda _self, *_a, **_kw: None, api)
    monkeypatch.setattr(api, "risk_first_send_reserve_contract",
                        lambda: (CONTRACT, reserve, host_contract))
    _assert_preflight_refusal(host, api, data, broker, strategy, monkeypatch)


@pytest.mark.parametrize("index", [1, 2, 3])
def test_host_contract_callable_must_be_bound_to_same_host(state, ready, inputs, monkeypatch, index):
    host, api, data, broker, strategy = _bound(state, ready, inputs, monkeypatch)
    contract = list(host.risk_first_send_host_contract())
    contract[index] = MethodType(lambda _other, *_a, **_kw: None, object())
    reserve = MethodType(lambda _self, *_a, **_kw: None, api)
    monkeypatch.setattr(api, "risk_first_send_reserve_contract",
                        lambda: (CONTRACT, reserve, tuple(contract)))
    _assert_preflight_refusal(host, api, data, broker, strategy, monkeypatch)


@pytest.mark.parametrize("name", ["save_submitted_order_intent", "create_risk_reserve_intent",
                                  "consume_risk_reserve_ticket"])
def test_host_method_replaced_before_preflight_is_refused(state, ready, inputs, monkeypatch, name):
    host, api, data, broker, strategy = _bound(state, ready, inputs, monkeypatch)
    monkeypatch.setattr(host, name, lambda *_a, **_kw: pytest.fail("replacement called"))
    _assert_preflight_refusal(host, api, data, broker, strategy, monkeypatch)


def test_host_save_replaced_after_preflight_does_not_call_replacement(state, ready, inputs, monkeypatch):
    host, api, data, broker, strategy = _bound(state, ready, inputs, monkeypatch)
    calls = _deny_writes(api, monkeypatch)
    before = tuple(host.list_intents())

    def qualify(*_):
        monkeypatch.setattr(host, "save_submitted_order_intent",
                            lambda *_a, **_kw: pytest.fail("replacement called"))
        return {}

    monkeypatch.setattr(broker, "_gateway_require_trade_qualification", qualify)
    order = _limit_order(strategy, data)
    with pytest.raises(RuntimeError, match="^RISK_TICKET_HOST_CONTRACT_CHANGED$"):
        broker.submit(order)
    # Save did not run in this case, but local order preparation already began;
    # the binding explicitly requires restart rather than assuming rollback.
    assert order.status == order.Submitted
    assert broker._gateway_stream_binding.state == "RESTART_REQUIRED"
    assert tuple(host.list_intents()) == before
    assert calls == []


def test_host_change_after_save_preserves_intent_and_recovers_without_new_write(state, ready, inputs, monkeypatch):
    """The fake rebind is not a real restart or venue/account evidence."""
    from tests.unit.brokers.test_iter64_gateway_risk_lifecycle import rebind

    host, api, data, broker, strategy = _bound(state, ready, inputs, monkeypatch)
    calls = _deny_writes(api, monkeypatch)
    original_store = host._store._store
    before_orders = dict(broker.orders)
    before_notifications = list(broker.notifs)

    def save_then_change(*args, **kwargs):
        original_store(*args, **kwargs)
        monkeypatch.setattr(host, "consume_risk_reserve_ticket",
                            lambda *_a, **_kw: pytest.fail("replacement called"))

    monkeypatch.setattr(host._store, "_store", save_then_change)
    order = _limit_order(strategy, data)
    with pytest.raises(RuntimeError, match="^RISK_TICKET_HOST_CONTRACT_CHANGED$"):
        broker.submit(order)
    key = order.info.gateway_request_key
    assert order.status == order.Submitted and order.executed.size == 0
    assert broker._gateway_stream_binding.state == "RESTART_REQUIRED"
    assert host.load_intent(key).request_key == key
    assert host.load_order_snapshot(key) is not None
    assert host.local_order_notifications()[key]["status"] == "pending"
    assert host.load_delegated_command(key) is None
    # The persistent notice exists, but the failed Broker did not register or
    # emit it after the save wrapper raised.
    assert broker.orders == before_orders and list(broker.notifs) == before_notifications
    assert calls == []

    monkeypatch.setattr(host._store, "_store", original_store)
    monkeypatch.delattr(host, "consume_risk_reserve_ticket")
    _data2, broker2, strategy2 = rebind(state, host, api, monkeypatch)
    restored = next(o for o in broker2.orders.values() if o.info.get("gateway_request_key") == key)
    assert restored.status == restored.Submitted and restored.executed.size == 0
    assert host.load_intent(key).request_key == key
    replayed = broker2.get_notification()
    assert replayed is not None and replayed.status == replayed.Submitted and replayed.replayed is True

    reads = []

    def unavailable_status(_route, observed_key, **_kwargs):
        reads.append(observed_key)
        return SimpleNamespace(outcome="UNKNOWN")

    monkeypatch.setattr(api, "risk_order_status", unavailable_status)
    monkeypatch.setattr(api, "delegated_command_status", unavailable_status)
    binding2 = broker2._gateway_stream_binding
    notice2 = broker2._gateway_binding(strategy2, required=True)
    assert broker2._gateway_risk_step(binding2, notice2, key) is False
    assert broker2._gateway_risk_step(binding2, notice2, key) is False
    assert reads == [key, key, key, key]
    assert restored.status == restored.Submitted and host.load_intent(key).request_key == key
    assert calls == []


@pytest.mark.parametrize("configured,selected", [(True, False), (False, True)])
def test_config_and_facade_risk_selection_must_agree(state, ready, inputs, monkeypatch,
                                                     configured, selected):
    host, api, data, broker, strategy = _bound(state, ready, inputs, monkeypatch)
    broker.store.gateway_strategy_config = SimpleNamespace(risk_selection=object() if configured else None)
    if not selected:
        monkeypatch.setattr(api, "_risk", None)
    _assert_preflight_refusal(host, api, data, broker, strategy, monkeypatch)


def test_supported_sdk_keeps_current_source_gate_closed(state, ready, inputs, monkeypatch):
    host, api, data, broker, strategy = _bound(state, ready, inputs, monkeypatch)
    calls = _deny_writes(api, monkeypatch)
    order = _limit_order(strategy, data)
    broker.submit(order)
    key = order.info.gateway_request_key
    assert order.status == order.Submitted and host.load_intent(key).request_key == key
    assert broker._gateway_stream_binding.state == "SUBMIT_UNKNOWN"
    assert calls == []


def test_later_attribute_replacement_does_not_switch_the_bound_callable(state, ready, inputs, monkeypatch):
    host, api, data, broker, strategy = _bound(state, ready, inputs, monkeypatch)
    calls = []

    def declared(self, route, request, **kwargs):
        calls.append(("declared", request.idempotency_key))
        return GatewayRiskRoutedResult("UNKNOWN", code="RISK_OUTCOME_UNKNOWN")

    method = MethodType(declared, api)
    monkeypatch.setattr(api, "risk_first_send_reserve_contract",
                        lambda: (CONTRACT, method, host.risk_first_send_host_contract()))

    def qualify(*_):
        monkeypatch.setattr(api, "reserve_order", lambda *a, **kw: pytest.fail("replaced reserve called"))
        return {}

    monkeypatch.setattr(broker, "_gateway_require_trade_qualification", qualify)
    order = _limit_order(strategy, data)
    broker.submit(order)
    assert calls == [("declared", order.info.gateway_request_key)]
    assert host.load_intent(order.info.gateway_request_key) is not None
    assert broker._gateway_stream_binding.state == "SUBMIT_UNKNOWN"


def test_real_sdk_contract_rechecks_reserve_replacement_before_use(state, ready, inputs, monkeypatch):
    host, api, data, broker, strategy = _bound(state, ready, inputs, monkeypatch)
    calls = _deny_writes(api, monkeypatch)

    def qualify(*_):
        monkeypatch.setattr(api, "reserve_order", lambda *a, **kw: pytest.fail("replacement called"))
        return {}

    monkeypatch.setattr(broker, "_gateway_require_trade_qualification", qualify)
    order = _limit_order(strategy, data)
    with pytest.raises(RuntimeError, match="^RISK_TICKET_CONTRACT_CHANGED$"):
        broker.submit(order)
    key = order.info.gateway_request_key
    assert order.status == order.Submitted and host.load_intent(key).request_key == key
    assert broker._gateway_stream_binding.state == "SUBMIT_UNKNOWN"
    assert calls == []


def test_error_after_call_begins_remains_unknown_without_retry(state, ready, inputs, monkeypatch):
    host, api, data, broker, strategy = _bound(state, ready, inputs, monkeypatch)
    calls = _deny_writes(api, monkeypatch)

    def entered(self, route, request, **kwargs):
        calls.append(("synthetic_send", request.idempotency_key))
        raise TypeError("failure after synthetic send")

    method = MethodType(entered, api)
    monkeypatch.setattr(api, "risk_first_send_reserve_contract",
                        lambda: (CONTRACT, method, host.risk_first_send_host_contract()))
    order = _limit_order(strategy, data)
    with pytest.raises(TypeError, match="failure after synthetic send"):
        broker.submit(order)
    key = order.info.gateway_request_key
    assert order.status == order.Submitted and host.load_intent(key).request_key == key
    assert broker._gateway_stream_binding.state == "SUBMIT_UNKNOWN"
    assert calls == [("synthetic_send", key)]
    with pytest.raises(GatewayExecutionStreamError, match="ORDER_RECONCILE_REQUIRED"):
        broker.submit(_limit_order(strategy, data, price=11))
    assert calls == [("synthetic_send", key)]
