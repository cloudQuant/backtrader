"""R31: real BT, pending host and SDK facade, with an offline RPC stub."""
from dataclasses import replace
from decimal import Decimal

import backtrader as bt
import pytest
from bt_api_base.gateway_execution_stream_protocol import GatewayExecutionStreamProgress
from bt_api_base.market_protocol import MarketInstrumentKey
from bt_api_base.service_protocol import WireIdentity, WireRole
from bt_api_py.gateway_api import GatewayBtApi
from bt_api_py.gateway_execution_stream_client import (
    GatewayExecutionReadContext, GatewayExecutionStreamClientResult,
)
from bt_api_py.gateway_execution_time import GatewayExecutionTimePolicy
from bt_api_py.gateway_strategy_client import GatewayStrategyClientSession
from bt_api_py.service_config import parse_client_config
from bt_api_py.service_runtime import ClientCurveKeys

from tests.unit.brokers.test_iter63_gateway_notification_delivery import framework
from tests.unit.live_state.conftest import state, strategy_dir
from tests.unit.live_state.test_gateway_execution_checkpoint import make_event, page, ready
from tests.unit.live_state.test_gateway_pending import inputs
from tests.unit.live_state.test_iter63_gateway_trade_date_pending import dated

INSTRUMENT = MarketInstrumentKey("ctp", "exchange", "paper", "future", "rb", "rb")


def api_for(host, route):
    config = {"client_config_schema_version": 1, "process_role": "strategy_client",
        "registration": {"strategy_ref": route.scope.strategy_ref},
        "clients": {"gateway": {"config_schema_version": 1, "settings": {"bindings": [{
            "mount": route.mount, "service_id": route.service_id,
            "instance_id": route.instance_id, "scope_ref": route.scope_ref,
            "account_ref": route.scope.account_ref, "transport_ref": "transport"}]}}},
        "communication": {"config_schema_version": 1, "profiles": {"transport": {
            "backend": "zmq", "config_schema_version": 1,
            "endpoints": {"rpc_connect": "tcp://127.0.0.1:12345"},
            "security_profile_ref": "security"}}}}
    session = GatewayStrategyClientSession(parse_client_config(config), binding=host._binding,
        route=route, peer=WireIdentity(WireRole.SERVICE, "service", route.service_id),
        security_profiles={"security": ClientCurveKeys(b"a" * 40, b"b" * 40, b"c" * 40)},
        host=host, requested_operations=frozenset({"direct.events.read_after", "direct.events.ack"}))
    return GatewayBtApi(session, exchange_name="CTP___FUTURE")


def attach(ready, inputs, monkeypatch, events=(), quick=False):
    host, binding, consumer = ready
    _, route, _ = inputs
    api = api_for(host, route)
    data, broker, strategy = framework(quick)
    order = bt.BuyOrder(owner=strategy, data=data, size=1, price=10, exectype=bt.Order.Limit)
    order.addcomminfo(broker.getcommissioninfo(data))
    order.submit(broker)
    order.accept(broker)
    host.save_intent(host.load_intent("key-a"), bt_ref=order.ref)
    calls = {"read": 0, "ack": [], "unknown": False}
    stream = api.gateway_execution_stream("CTP___FUTURE")
    def read(after, epoch, limit, *, timeout_seconds):
        calls["read"] += 1
        selected = [event for event in events if event.sequence > after][:limit]
        return GatewayExecutionStreamClientResult("OBSERVED", page=page(binding, consumer, selected),
            request_context=GatewayExecutionReadContext(binding, consumer, after, epoch, limit))
    def ack(sequence, expected_epoch, *, timeout_seconds):
        calls["ack"].append(sequence)
        if calls["unknown"]:
            return GatewayExecutionStreamClientResult("UNKNOWN", code="RPC_OUTCOME_UNKNOWN")
        return GatewayExecutionStreamClientResult("OBSERVED", progress=GatewayExecutionStreamProgress(
            binding, consumer, expected_epoch, 10, sequence))
    monkeypatch.setattr(stream, "read_after", read)
    monkeypatch.setattr(stream, "ack", ack)
    broker.bind_gateway_execution_stream(strategy, api=api, host=host, data_by_ref={"rb": data},
        orders_by_key={"key-a": order}, instrument_by_ref={"rb": INSTRUMENT},
        time_policy=GatewayExecutionTimePolicy("CTP___FUTURE", "UTC"))
    return host, broker, strategy, order, calls, api


def event_for(host, seq=3, *, quantity="0.4", fact="a" * 64, trade="b" * 64):
    event = make_event(host, seq, fact=fact, trade=trade)
    return dated(event, seq, date="20261107", metadata=False, fact=fact, offset=None,
                 order_quantity="1", filled_quantity=quantity,
                 remaining_quantity=format(Decimal("1") - Decimal(quantity), "f"), trade_quantity=quantity)


def deliver(broker, strategy, quick=False):
    notice = broker.get_notification()
    assert notice is not None
    strategy._addnotification(notice, quicknotify=quick)
    if not quick:
        strategy._notify()
    strategy.clear()


@pytest.mark.parametrize("quick", [False, True])
def test_trade_notification_and_explicit_ack(ready, inputs, monkeypatch, quick):
    events = [event_for(ready[0])]
    host, broker, strategy, order, calls, _ = attach(ready, inputs, monkeypatch, events, quick)
    broker.next()
    assert order.executed.size == 0.4 and broker.positions["rb"].size == 0.4
    assert order.info["commission_source"] == "unavailable"
    assert order.info["actual_commission_known"] is False
    assert bt.num2date(order.executed.dt).isoformat() == "2026-11-07T09:00:00"
    assert broker.positions["rb"].datetime.tzinfo is not None
    assert host.load_execution_checkpoint().applied_sequence == 0 and not calls["ack"]
    deliver(broker, strategy, quick)
    assert [event[0] for event in strategy.events] == ["order", "trade"]
    calls["unknown"] = True
    broker.next()
    assert host.load_execution_checkpoint().acknowledged_sequence == 0
    calls["unknown"] = False
    broker.next()
    assert calls["ack"] == [3, 3]
    assert host.load_execution_checkpoint().acknowledged_sequence == 3
    assert order.executed.size == 0.4


def test_undated_waits_then_uses_persisted_metadata(ready, inputs, monkeypatch):
    normal = event_for(ready[0])
    original = replace(normal, observation=replace(normal.observation, schema_version=1, trade_date=None))
    events = [original]
    host, broker, strategy, order, calls, _ = attach(ready, inputs, monkeypatch, events)
    broker.next()
    assert broker.gateway_execution_stream_status() == "TIME_UNAVAILABLE"
    assert host.load_execution_checkpoint().applied_sequence == 0 and order.executed.size == 0
    events.append(dated(original, 6, date="20261107"))
    broker.next()
    assert order.executed.size == 0.4
    assert order.info["gateway_execution_time_facts"][original.observation.trade_key_digest]["trade_date"] == "20261107"
    deliver(broker, strategy)
    broker.next()
    assert host.load_execution_checkpoint().applied_sequence == 6
    assert order.executed.size == 0.4 and len(strategy.events) == 2
    broker.next()
    assert calls["ack"] == [3, 6]


def test_write_methods_fail_without_touching_order(ready, inputs, monkeypatch):
    _, broker, _, order, _, _ = attach(ready, inputs, monkeypatch)
    before = (order.status, order.executed.size, dict(order.info))
    for method in (broker.submit, broker.cancel):
        with pytest.raises(RuntimeError, match="WRITE_ADAPTER_UNAVAILABLE"):
            method(order)
    assert (order.status, order.executed.size, dict(order.info)) == before


def test_multiple_fills_and_duplicate_do_not_reapply(ready, inputs, monkeypatch):
    first = event_for(ready[0])
    duplicate = replace(first, sequence=6, fact_digest="f" * 64)
    final = event_for(ready[0], 8, quantity="0.6", fact="9" * 64, trade="c" * 64)
    events = [first, duplicate, final]
    host, broker, strategy, order, calls, _ = attach(ready, inputs, monkeypatch, events)
    broker.next()
    deliver(broker, strategy)
    broker.next()
    assert order.executed.size == 0.4
    deliver(broker, strategy)
    broker.next()
    assert order.executed.size == 1 and broker.positions["rb"].size == 1
    deliver(broker, strategy)
    broker.next()
    assert calls["ack"] == [3, 6, 8]
    assert host.load_execution_checkpoint().acknowledged_sequence == 8
    assert order.status == order.Completed


def test_callback_failure_does_not_ack(ready, inputs, monkeypatch):
    host, broker, strategy, order, calls, _ = attach(
        ready, inputs, monkeypatch, [event_for(ready[0])])
    broker.next()
    strategy.fail = "order"
    notice = broker.get_notification()
    strategy._addnotification(notice)
    with pytest.raises(RuntimeError, match="callback"):
        strategy._notify()
    broker.next()
    assert broker.gateway_execution_stream_status() == "WAITING_NOTIFICATIONS"
    assert not calls["ack"] and order.executed.size == 0.4
    assert host.load_execution_notification_batch()["status"] == "pending"


def test_wrong_order_binding_is_rejected_without_fallback(ready, inputs, monkeypatch):
    host, binding, consumer = ready
    api = api_for(host, inputs[1])
    data, broker, strategy = framework()
    order = bt.SellOrder(owner=strategy, data=data, size=1, price=10, exectype=bt.Order.Limit)
    with pytest.raises(RuntimeError, match="ORDER_BINDING"):
        broker.bind_gateway_execution_stream(strategy, api=api, host=host, data_by_ref={"rb": data},
            orders_by_key={"key-a": order}, instrument_by_ref={"rb": INSTRUMENT},
            time_policy=GatewayExecutionTimePolicy("CTP___FUTURE", "UTC"))
    with pytest.raises(RuntimeError, match="WRITE_ADAPTER_UNAVAILABLE"):
        broker.submit(order)


def test_unbound_next_uses_existing_direct_path(monkeypatch):
    _, broker, _ = framework()
    seen = []
    monkeypatch.setattr(broker, "_direct_active", lambda: True)
    monkeypatch.setattr(broker, "_direct_next", lambda: seen.append(True))
    broker.next()
    assert seen == [True]


def test_restart_restores_original_order_binding_and_waits_for_framework_replay(ready, inputs, monkeypatch):
    host, broker, strategy, order, calls, api = attach(
        ready, inputs, monkeypatch, [event_for(ready[0])])
    host.save_intent(host.load_intent("key-a"), bt_ref=order.ref)
    old_ref = order.ref
    broker.next()
    strategy.fail = "order"
    strategy._addnotification(broker.get_notification())
    with pytest.raises(RuntimeError, match="callback"):
        strategy._notify()
    data, recovered_broker, recovered_strategy = framework()
    recovered_broker.bind_gateway_execution_stream(recovered_strategy, api=api, host=host,
        data_by_ref={"rb": data}, orders_by_key={}, instrument_by_ref={"rb": INSTRUMENT},
        time_policy=GatewayExecutionTimePolicy("CTP___FUTURE", "UTC"))
    recovered = next(iter(recovered_broker.orders.values()))
    assert recovered.ref != old_ref and recovered.info["gateway_original_bt_ref"] == old_ref
    assert recovered.executed.size == 0.4 and recovered_broker.positions["rb"].size == 0.4
    recovered_broker.next()
    assert recovered_broker.gateway_execution_stream_status() == "WAITING_NOTIFICATIONS"
    assert not calls["ack"]
    recovered_strategy._notify()
    recovered_strategy.clear()
    recovered_broker.next()
    assert calls["ack"] == [3]
    assert recovered.executed.size == 0.4 and recovered_broker.positions["rb"].size == 0.4


def test_mismatched_instrument_is_never_projected(ready, inputs, monkeypatch):
    event = event_for(ready[0])
    other = replace(INSTRUMENT, venue="other")
    event = replace(event, observation=replace(event.observation, instrument=other))
    host, broker, strategy, order, calls, _ = attach(ready, inputs, monkeypatch, [event])
    with pytest.raises(RuntimeError, match="EVENT_BINDING"):
        broker.next()
    assert order.executed.size == 0 and host.load_execution_checkpoint().applied_sequence == 0
    assert not calls["ack"]


def test_sparse_request_error_preserves_unknown_order(ready, inputs, monkeypatch):
    from bt_api_base.direct_write_protocol import DirectExecutionEventKind
    from bt_api_base.gateway_execution_stream_protocol import GatewayExecutionObservation, GatewayPlaceErrorAttribution

    trade = event_for(ready[0])
    obs = GatewayExecutionObservation(account_scope="account-a", route="CTP___FUTURE",
        instrument=INSTRUMENT, trading_day="20261108", kind=DirectExecutionEventKind.ORDER_ERROR,
        error_code="UNKNOWN")
    event = replace(trade, observation=obs, place_attribution=GatewayPlaceErrorAttribution("1" * 64))
    host, broker, strategy, order, calls, _ = attach(ready, inputs, monkeypatch, [event])
    order.addinfo(execution_unknown=True)
    broker.next()
    assert order.status == order.Accepted and order.info["execution_unknown"] is True
    deliver(broker, strategy)
    broker.next()
    assert host.load_execution_checkpoint().acknowledged_sequence == 3


def test_persistence_failure_blocks_ack_and_further_projection(ready, inputs, monkeypatch):
    from backtrader.live_state import pending as pending_module

    host, broker, strategy, order, calls, _ = attach(
        ready, inputs, monkeypatch, [event_for(ready[0])])
    broker.next()
    strategy._addnotification(broker.get_notification())
    monkeypatch.setattr(pending_module, "atomic_write_json", lambda *a: (_ for _ in ()).throw(OSError("storage")))
    with pytest.raises(OSError, match="storage"):
        strategy._notify()
    broker.next()
    assert not calls["ack"] and order.executed.size == 0.4
    assert host.load_execution_checkpoint().applied_sequence == 0


def test_cancel_error_does_not_cancel_order(ready, inputs, monkeypatch):
    from bt_api_base.direct_write_protocol import DirectExecutionEventKind
    from bt_api_base.gateway_execution_stream_protocol import GatewayExecutionObservation, GatewayCancelErrorAttribution
    from tests.unit.live_state.test_gateway_pending_cancel import plan, record

    host = ready[0]
    cancel = plan(host, inputs[1])
    host.save_cancel_plan(cancel)
    host.save_cancel_record(cancel.operation_id, record(cancel))
    event = event_for(host)
    obs = GatewayExecutionObservation(account_scope="account-a", route="CTP___FUTURE",
        instrument=INSTRUMENT, trading_day="20261108", kind=DirectExecutionEventKind.CANCEL_ERROR,
        error_code="UNKNOWN")
    event = replace(event, observation=obs,
        cancel_attribution=GatewayCancelErrorAttribution(cancel.operation_id, "attempt-a", "1" * 64))
    host, broker, strategy, order, calls, _ = attach(ready, inputs, monkeypatch, [event])
    broker.next()
    assert order.status == order.Accepted
    deliver(broker, strategy)
    broker.next()
    assert host.load_execution_checkpoint().acknowledged_sequence == 3


def test_gateway_reconcile_does_not_enqueue_legacy_store(ready, inputs, monkeypatch):
    from types import SimpleNamespace

    _, broker, _, order, _, _ = attach(ready, inputs, monkeypatch)
    seen = []
    broker.store = SimpleNamespace(enqueue_order_reconciliation=lambda ref: seen.append(ref))
    broker._request_order_reconcile(order)
    assert seen == []


def test_terminal_order_waits_for_separate_fill(ready, inputs, monkeypatch):
    from bt_api_base.direct_write_protocol import DirectExecutionEventKind, DirectOrderStatus
    from bt_api_base.gateway_execution_stream_protocol import GatewayExecutionObservation

    source = make_event(ready[0])
    original = source.observation
    obs = GatewayExecutionObservation(account_scope=original.account_scope, route=original.route,
        instrument=original.instrument, trading_day=original.trading_day,
        kind=DirectExecutionEventKind.ORDER, native_identity_digest=original.native_identity_digest,
        identity_key_digests=original.identity_key_digests, binding_key_digests=original.binding_key_digests,
        venue_key_digest=original.venue_key_digest, status=DirectOrderStatus.FILLED,
        side="buy", order_quantity="1", filled_quantity="1", remaining_quantity="0")
    terminal = replace(source, observation=obs)
    trade = event_for(ready[0], 8, quantity="1", fact="f" * 64)
    host, broker, strategy, order, calls, _ = attach(ready, inputs, monkeypatch, [terminal, trade])
    broker.next()
    assert order.executed.size == 0 and order.status != order.Completed
    assert order.info["execution_pending_trades"] is True
    deliver(broker, strategy)
    broker.next()
    assert order.executed.size == 1 and order.status == order.Completed
    deliver(broker, strategy)
    broker.next()
    assert calls["ack"] == [3, 8]


def test_restored_snapshot_rejects_changed_time_policy(ready, inputs, monkeypatch):
    host, broker, strategy, order, calls, api = attach(
        ready, inputs, monkeypatch, [event_for(ready[0])])
    broker.next()
    deliver(broker, strategy)
    data, next_broker, next_strategy = framework()
    with pytest.raises(RuntimeError, match="TIME_POLICY_CONFLICT"):
        next_broker.bind_gateway_execution_stream(next_strategy, api=api, host=host,
            data_by_ref={"rb": data}, orders_by_key={}, instrument_by_ref={"rb": INSTRUMENT},
            time_policy=GatewayExecutionTimePolicy("CTP___FUTURE", "Asia/Shanghai"))


def test_same_shape_order_must_match_durable_original_ref(ready, inputs, monkeypatch):
    host, _, _ = ready
    api = api_for(host, inputs[1])
    data, broker, strategy = framework()
    first = bt.BuyOrder(owner=strategy, data=data, size=1, price=10, exectype=bt.Order.Limit)
    second = bt.BuyOrder(owner=strategy, data=data, size=1, price=10, exectype=bt.Order.Limit)
    host.save_intent(host.load_intent("key-a"), bt_ref=first.ref)
    with pytest.raises(RuntimeError, match="ORDER_BINDING"):
        broker.bind_gateway_execution_stream(strategy, api=api, host=host, data_by_ref={"rb": data},
            orders_by_key={"key-a": second}, instrument_by_ref={"rb": INSTRUMENT},
            time_policy=GatewayExecutionTimePolicy("CTP___FUTURE", "UTC"))
    assert not broker.notifs


def test_stream_binding_rejects_other_thread(ready, inputs, monkeypatch):
    import threading

    _, broker, _, _, _, _ = attach(ready, inputs, monkeypatch)
    errors = []
    def run():
        try:
            broker.next()
        except RuntimeError as error:
            errors.append(str(error))
    thread = threading.Thread(target=run)
    thread.start()
    thread.join()
    assert errors == ["GATEWAY_STREAM_SCOPE"]


def test_consumer_identity_drift_is_rejected_before_read(ready, inputs, monkeypatch):
    host, broker, strategy, order, calls, api = attach(ready, inputs, monkeypatch)
    stream = api.gateway_execution_stream("CTP___FUTURE")
    monkeypatch.setattr(stream, "_consumer_ref", "gexec:" + "0" * 64)
    with pytest.raises(RuntimeError, match="GATEWAY_STREAM_SCOPE"):
        broker.next()
    assert calls["read"] == 0 and not calls["ack"]
    assert host.load_execution_checkpoint().applied_sequence == 0


def test_stored_next_fill_does_not_require_remote_read(ready, inputs, monkeypatch):
    first = event_for(ready[0])
    second = event_for(ready[0], 8, quantity="0.6", fact="f" * 64, trade="c" * 64)
    host, broker, strategy, order, calls, api = attach(ready, inputs, monkeypatch, [first, second])
    broker.next()
    assert calls["read"] == 1 and host.load_execution_checkpoint().stored_sequence == 8
    deliver(broker, strategy)
    stream = api.gateway_execution_stream("CTP___FUTURE")
    def unavailable(*args, **kwargs):
        calls["read"] += 1
        return GatewayExecutionStreamClientResult("UNKNOWN", code="RPC_OUTCOME_UNKNOWN")
    monkeypatch.setattr(stream, "read_after", unavailable)
    broker.next()
    checkpoint = host.load_execution_checkpoint()
    assert (checkpoint.applied_sequence, checkpoint.acknowledged_sequence) == (3, 3)
    assert order.executed.size == 1 and broker.positions["rb"].size == 1
    assert calls["read"] == 1 and calls["ack"] == [3]
    deliver(broker, strategy)
    assert [item[0] for item in strategy.events] == ["order", "trade", "order"]
    broker.next()
    assert calls["ack"] == [3, 8] and calls["read"] == 2
    assert broker.get_notification() is None


def test_missing_date_reads_next_page_only_when_needed(ready, inputs, monkeypatch):
    normal = event_for(ready[0])
    original = replace(normal, observation=replace(normal.observation, schema_version=1, trade_date=None))
    metadata = dated(original, 6, date="20261107")
    host, broker, strategy, order, calls, _ = attach(ready, inputs, monkeypatch, [original, metadata])
    broker._gateway_stream_binding.limit = 1
    broker.next()
    assert calls["read"] == 1 and host.load_execution_checkpoint().stored_sequence == 3
    assert order.executed.size == 0 and not calls["ack"] and not strategy.events
    broker.next()
    assert calls["read"] == 2 and host.load_execution_checkpoint().stored_sequence == 6
    assert order.executed.size == 0.4 and not calls["ack"]
    deliver(broker, strategy)
    broker.next()
    assert calls["read"] == 2 and calls["ack"] == [3]
    assert host.load_execution_checkpoint().applied_sequence == 6
    assert order.executed.size == 0.4 and len(strategy.events) == 2
    broker.next()
    assert calls["ack"] == [3, 6] and broker.get_notification() is None


def test_consumer_rejects_conflicting_known_trade_times_before_projection(ready, inputs, monkeypatch):
    from tests.unit.live_state.test_iter63_gateway_trade_date_pending import result

    normal = event_for(ready[0])
    original = replace(normal, observation=replace(normal.observation, schema_version=1, trade_date=None))
    compatible = dated(original, 6, date="20261107")
    host, broker, strategy, order, calls, _ = attach(ready, inputs, monkeypatch)
    host.ingest_execution_result(result(ready[1], ready[2], [original, compatible]), expected_revision=0)
    real_read = host.read_execution_events
    def with_conflicting_time(after_sequence=None, *, limit=256):
        events = real_read(after_sequence=after_sequence, limit=limit)
        return tuple(replace(event, observation=replace(event.observation, trade_time="10:00:00"))
                     if event.sequence == 6 else event for event in events)
    monkeypatch.setattr(host, "read_execution_events", with_conflicting_time)
    with pytest.raises(RuntimeError, match="TRADE_TIME_CONFLICT"):
        broker.next()
    checkpoint = host.load_execution_checkpoint()
    assert (checkpoint.applied_sequence, checkpoint.acknowledged_sequence) == (0, 0)
    assert order.executed.size == 0 and not calls["ack"] and calls["read"] == 0
    assert not strategy.events and broker.get_notification() is None


def test_consumer_rejects_late_conflicting_time_without_new_effect(ready, inputs, monkeypatch):
    first = event_for(ready[0])
    events = [first]
    host, broker, strategy, order, calls, _ = attach(ready, inputs, monkeypatch, events)
    broker.next()
    deliver(broker, strategy)
    events.append(dated(first, 6, date="20261107"))
    real_read = host.read_execution_events
    def with_conflicting_time(after_sequence=None, *, limit=256):
        rows = real_read(after_sequence=after_sequence, limit=limit)
        return tuple(replace(event, observation=replace(event.observation, trade_time="10:00:00"))
                     if event.sequence == 6 else event for event in rows)
    monkeypatch.setattr(host, "read_execution_events", with_conflicting_time)
    with pytest.raises(RuntimeError, match="TRADE_TIME_CONFLICT"):
        broker.next()
    checkpoint = host.load_execution_checkpoint()
    assert (checkpoint.applied_sequence, checkpoint.acknowledged_sequence) == (3, 3)
    assert order.executed.size == 0.4 and broker.positions["rb"].size == 0.4
    assert calls["ack"] == [3] and len(strategy.events) == 2
    assert broker.get_notification() is None


def test_unknown_ack_blocks_even_a_complete_stored_next_fill(ready, inputs, monkeypatch):
    first = event_for(ready[0])
    second = event_for(ready[0], 8, quantity="0.6", fact="f" * 64, trade="c" * 64)
    host, broker, strategy, order, calls, _ = attach(ready, inputs, monkeypatch, [first, second])
    broker.next()
    deliver(broker, strategy)
    calls["unknown"] = True
    broker.next()
    checkpoint = host.load_execution_checkpoint()
    assert (checkpoint.stored_sequence, checkpoint.applied_sequence, checkpoint.acknowledged_sequence) == (8, 3, 0)
    assert order.executed.size == 0.4 and broker.get_notification() is None
    assert calls["ack"] == [3] and calls["read"] == 1
    calls["unknown"] = False
    broker.next()
    assert calls["ack"] == [3, 3] and calls["read"] == 1
    assert order.executed.size == 1


def test_missing_date_and_unknown_read_does_not_arm_or_ack(ready, inputs, monkeypatch):
    normal = event_for(ready[0])
    original = replace(normal, observation=replace(normal.observation, schema_version=1, trade_date=None))
    host, broker, strategy, order, calls, api = attach(ready, inputs, monkeypatch, [original])
    broker.next()
    assert broker.gateway_execution_stream_status() == "TIME_UNAVAILABLE"
    stream = api.gateway_execution_stream("CTP___FUTURE")
    def unavailable(*args, **kwargs):
        calls["read"] += 1
        return GatewayExecutionStreamClientResult("UNKNOWN", code="RPC_OUTCOME_UNKNOWN")
    monkeypatch.setattr(stream, "read_after", unavailable)
    broker.next()
    assert calls["read"] == 2 and not calls["ack"]
    assert broker.gateway_execution_stream_status() == "READ_UNAVAILABLE"
    assert host.load_execution_checkpoint().applied_sequence == 0
    assert order.executed.size == 0 and broker.get_notification() is None and not strategy.events
