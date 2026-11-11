"""R31: real BT, pending host and SDK facade, with an offline RPC stub."""
from dataclasses import replace
from types import SimpleNamespace
from decimal import Decimal
import math

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

from tests.unit.brokers.test_iter63_gateway_notification_delivery import framework as base_framework
from tests.unit.live_state.conftest import state as state, strategy_dir as strategy_dir
from tests.unit.live_state.test_gateway_execution_checkpoint import make_event, page, ready as ready
from tests.unit.live_state.test_gateway_pending import inputs as inputs
from tests.unit.live_state.test_iter63_gateway_trade_date_pending import dated

INSTRUMENT = MarketInstrumentKey("ctp", "exchange", "paper", "future", "rb", "rb")
SYNTHETIC_MARKET_REF = {'key': {'source_ref': 'synthetic', 'entitlement_ref': 'synthetic',
    'instrument': INSTRUMENT.to_dict(), 'channel': 'tick', 'depth': None, 'timeframe': None},
    'epoch': 'synthetic', 'sequence': 1, 'message_id': 'synthetic'}


def framework(quick=False):
    from types import SimpleNamespace
    data, broker, strategy = base_framework(quick)
    broker.store = SimpleNamespace(contract_metadata={'rb': {'instrument_key': INSTRUMENT.to_dict(),
        'exchange_name': 'CTP___FUTURE', 'quantity_unit': 'lots', 'time_in_force': 'GFD'}})
    return data, broker, strategy


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


@pytest.fixture(autouse=True)
def _every_step_runs(monkeypatch):
    # A step that found nothing to do pauses the next ones (see
    # _IDLE_READ_INTERVAL_SECONDS). The tests of this module step a broker in
    # a tight loop and assert on each step; the pacing tests set the interval.
    import backtrader.brokers._btapi_gateway_stream as module

    monkeypatch.setattr(module, "_IDLE_READ_INTERVAL_SECONDS", 0.0)


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


def test_queued_event_waits_for_original_request_identity_without_ack(ready, inputs, monkeypatch):
    from bt_api_py.gateway_direct_client import GatewayClientResult

    event = event_for(ready[0])
    host, broker, strategy, order, calls, api = attach(ready, inputs, monkeypatch, [event])
    actual_load = host.load_record
    strong = actual_load('key-a')
    weak = replace(strong, state='RESERVED', version=1, native_identity=None,
                   strong_identity_key_digests=(), remaining_ttl_seconds=9.0)
    available = [False]
    monkeypatch.setattr(host, 'load_record', lambda key: actual_load(key) if available[0] else weak)
    statuses = []
    def status(_route, key, **_kw):
        statuses.append(key)
        return GatewayClientResult('OBSERVED', strong) if available[0] else GatewayClientResult('UNKNOWN')
    monkeypatch.setattr(api, 'command_status', status)
    before = host.load_execution_checkpoint()
    broker.next()
    after = host.load_execution_checkpoint()
    assert after == before and calls['ack'] == [] and order.executed.size == 0
    assert broker.gateway_execution_stream_status() == 'RECOVERY_PENDING'
    available[0] = True
    broker.next()
    assert statuses == ['key-a'] and order.executed.size == 0.4
    assert host.load_execution_checkpoint().stored_sequence == 3 and calls['ack'] == []


@pytest.mark.parametrize('valid', [True, False])
def test_trade_alias_proof_must_bind_original_command_key(ready, inputs, monkeypatch, valid):
    from bt_api_base.gateway_execution_stream_protocol import GatewayTradeAttribution

    host, binding, _ = ready
    event = event_for(host)
    record = host.load_record('key-a')
    obs = event.observation
    proof = GatewayTradeAttribution(binding.account_scope, binding.strategy_scope,
        event.fact_digest, event.reservation_id, event.command_digest, 'e' * 64, 1,
        obs.venue_key_digest, record.strong_identity_key_digests if valid else ('f' * 64,))
    event = replace(event, observation=replace(obs, schema_version=3, binding_key_digests=(),
                                               trade_attribution=proof))
    host, broker, strategy, order, calls, _ = attach(ready, inputs, monkeypatch, [event])
    if not valid:
        before = host.load_execution_checkpoint()
        with pytest.raises(ValueError, match='EXECUTION_TRADE_ATTRIBUTION_MISMATCH'):
            broker.next()
        assert host.load_execution_checkpoint() == before and order.executed.size == 0
        assert calls['ack'] == []
    else:
        broker.next()
        assert order.executed.size == 0.4
        assert host.load_execution_checkpoint().stored_sequence == 3 and calls['ack'] == []


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


@pytest.mark.parametrize("ended", ["CANCELLED", "REJECTED"])
def test_fill_after_the_venue_ended_the_order_is_applied_and_notified(ready, inputs, monkeypatch, ended):
    """A trade that arrives after the venue reported the order cancelled or rejected is still
    this order's trade: it is applied, the order ends Completed and the strategy hears about it
    (the Gateway-mode side of I63-D001; the direct path is tracked there)."""
    from bt_api_base.direct_write_protocol import DirectExecutionEventKind, DirectOrderStatus
    from bt_api_base.gateway_execution_stream_protocol import GatewayExecutionObservation

    source = make_event(ready[0])
    original = source.observation
    obs = GatewayExecutionObservation(account_scope=original.account_scope, route=original.route,
        instrument=original.instrument, trading_day=original.trading_day,
        kind=DirectExecutionEventKind.ORDER, native_identity_digest=original.native_identity_digest,
        identity_key_digests=original.identity_key_digests, binding_key_digests=original.binding_key_digests,
        venue_key_digest=original.venue_key_digest, status=DirectOrderStatus[ended],
        side="buy", order_quantity="1", filled_quantity="0", remaining_quantity="1")
    trade = event_for(ready[0], 8, quantity="1", fact="f" * 64)
    host, broker, strategy, order, calls, _ = attach(
        ready, inputs, monkeypatch, [replace(source, observation=obs), trade])
    broker.next()
    assert order.status == (order.Canceled if ended == "CANCELLED" else order.Rejected)
    assert order.executed.size == 0
    deliver(broker, strategy)
    broker.next()
    assert order.status == order.Completed and order.executed.size == 1   # the late trade counts
    deliver(broker, strategy)
    broker.next()
    assert [event[0] for event in strategy.events] == ["order", "order", "trade"]
    assert calls["ack"] == [3, 8]                                          # both events are consumed once


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


def test_missing_trade_time_uses_later_fact_after_restart(ready, inputs, monkeypatch):
    original = event_for(ready[0])
    original = replace(original, observation=replace(original.observation, trade_time=None))
    later = dated(original, 6, date='20261107', trade_time='09:00:00')
    host, broker, strategy, order, calls, api = attach(ready, inputs, monkeypatch, [original, later])
    broker._gateway_stream_binding.limit = 1
    broker.next()
    assert host.load_execution_checkpoint().stored_sequence == 3
    assert order.executed.size == 0 and calls['ack'] == []
    data2, broker2, strategy2 = framework()
    recovered = bt.BuyOrder(owner=strategy2, data=data2, size=1, price=10, exectype=bt.Order.Limit)
    recovered.addcomminfo(broker2.getcommissioninfo(data2))
    recovered.submit(broker2)
    recovered.accept(broker2)
    policy = GatewayExecutionTimePolicy('CTP___FUTURE', 'UTC')
    recovered.addinfo(gateway_original_bt_ref=order.ref, gateway_instrument_key=INSTRUMENT.to_dict(),
                      gateway_execution_time_policy=policy.to_mapping(),
                      gateway_execution_time_policy_digest=policy.digest)
    broker2.bind_gateway_execution_stream(strategy2, api=api, host=host, data_by_ref={'rb': data2},
        orders_by_key={'key-a': recovered}, instrument_by_ref={'rb': INSTRUMENT}, page_limit=1,
        time_policy=policy)
    broker2.next()
    assert recovered.executed.size == 0.4 and calls['ack'] == []
    fact = recovered.info['gateway_execution_time_facts'][original.observation.trade_key_digest]
    assert fact['trade_time'] == '09:00:00' and fact['time_fact_digest'] == later.fact_digest
    deliver(broker2, strategy2)
    broker2.next()
    assert calls['ack'] == [3] and recovered.executed.size == 0.4


@pytest.mark.parametrize('ordering', ['time-first', 'date-first'])
def test_independent_trade_time_and_date_metadata_survive_restart(ready, inputs, monkeypatch, ordering):
    normal = event_for(ready[0])
    original = replace(normal, observation=replace(normal.observation, trade_date=None, trade_time=None))
    timed = dated(original, 6 if ordering == 'time-first' else 8,
                  date=None, trade_time='09:00:00', fact='f' * 64)
    dated_event = dated(original, 8 if ordering == 'time-first' else 6,
                        date='20261107', trade_time=None, fact='e' * 64)
    events = [original, timed, dated_event] if ordering == 'time-first' else [original, dated_event, timed]
    host, broker, strategy, order, calls, api = attach(ready, inputs, monkeypatch, events)
    broker.next()
    assert order.executed.size == 0.4 and calls['ack'] == []
    deliver(broker, strategy)
    broker.next()
    assert calls['ack'] == [3] and host.load_execution_checkpoint().applied_sequence == 6
    data2, broker2, strategy2 = framework()
    broker2.bind_gateway_execution_stream(strategy2, api=api, host=host, data_by_ref={'rb': data2},
        orders_by_key={}, instrument_by_ref={'rb': INSTRUMENT},
        time_policy=GatewayExecutionTimePolicy('CTP___FUTURE', 'UTC'))
    recovered = next(iter(broker2.orders.values()))
    broker2.next()
    assert calls['ack'] == [3, 6] and host.load_execution_checkpoint().applied_sequence == 8
    broker2.next()
    assert calls['ack'] == [3, 6, 8] and recovered.executed.size == 0.4
    key = original.observation.trade_key_digest
    assert recovered.info['gateway_trade_dates'][key] == '20261107'
    assert recovered.info['gateway_trade_times'][key] == '09:00:00'
    facts = recovered.info['gateway_execution_time_facts'][key]
    assert facts['date_fact_digest'] == dated_event.fact_digest
    assert facts['time_fact_digest'] == timed.fact_digest
    assert strategy2.events == [] and broker2.get_notification() is None


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


def test_gateway_submits_only_after_durable_intent_and_delivers_local_notification(state, ready, inputs, monkeypatch):
    from backtrader.live_state.gateway_pending import GatewayPendingHost
    from bt_api_py.gateway_direct_client import GatewayClientResult
    from tests.unit.live_state.test_gateway_pending import observe

    _, binding, _ = ready
    host = GatewayPendingHost.upgrade_for_order_state(state.strategy_dir, state.strategy_uuid, binding)
    state.sequence.allocate()  # fixture's existing key-a already owns local sequence 1
    api = api_for(host, inputs[1])
    data, broker, strategy = framework()
    monkeypatch.setattr(broker, "_gateway_require_trade_qualification", lambda *_: SYNTHETIC_MARKET_REF)  # synthetic order-path test
    broker.bind_gateway_execution_stream(strategy, api=api, host=host, data_by_ref={'rb': data},
        orders_by_key={}, instrument_by_ref={'rb': INSTRUMENT},
        time_policy=GatewayExecutionTimePolicy('CTP___FUTURE', 'UTC'), sequence=state.sequence)
    calls = []
    def reserve(route, request, *, timeout_seconds):
        key = request.idempotency_key
        intent = host.load_intent(key)
        assert intent is not None and host.load_order_snapshot(key) is not None
        assert host.local_order_notifications()[key]['status'] == 'pending'
        record = observe(intent)
        host.save_record(key, record)
        calls.append(('reserve', key))
        return GatewayClientResult('OBSERVED', record)
    def dispatch(route, key, *, timeout_seconds, market_ref):
        assert host.load_record(key) is not None
        assert market_ref == SYNTHETIC_MARKET_REF
        calls.append(('dispatch', key))
        return GatewayClientResult('QUEUED', host.load_record(key))
    monkeypatch.setattr(api, 'reserve_order', reserve)
    monkeypatch.setattr(api, 'dispatch_order', dispatch)
    order = bt.BuyOrder(owner=strategy, data=data, size=1, price=10, exectype=bt.Order.Limit)
    order.addinfo(offset='open', quantity_unit='lots', time_in_force='GFD')
    assert broker.submit(order) is order
    assert [item[0] for item in calls] == ['reserve', 'dispatch']
    key = calls[0][1]
    assert order.status == order.Submitted
    assert host.load_execution_checkpoint().applied_sequence == 0
    deliver(broker, strategy)
    assert host.local_order_notifications()[key]['status'] == 'confirmed'
    assert strategy.events[0][0] == 'order'
    assert host.load_execution_checkpoint().acknowledged_sequence == 0


@pytest.mark.parametrize('outcome,code', [('UNKNOWN', 'RPC_OUTCOME_UNKNOWN')])
def test_gateway_unknown_submission_restart_replays_local_notice_without_new_reserve(state, ready, inputs, monkeypatch, outcome, code):
    from backtrader.live_state.gateway_pending import GatewayPendingHost
    from bt_api_py.gateway_direct_client import GatewayClientResult

    _, binding, _ = ready
    host = GatewayPendingHost.upgrade_for_order_state(state.strategy_dir, state.strategy_uuid, binding)
    state.sequence.allocate()
    api = api_for(host, inputs[1])
    data, broker, strategy = framework()
    monkeypatch.setattr(broker, "_gateway_require_trade_qualification", lambda *_: SYNTHETIC_MARKET_REF)  # synthetic order-path test
    broker.bind_gateway_execution_stream(strategy, api=api, host=host, data_by_ref={'rb': data},
        orders_by_key={}, instrument_by_ref={'rb': INSTRUMENT},
        time_policy=GatewayExecutionTimePolicy('CTP___FUTURE', 'UTC'), sequence=state.sequence)
    calls = []
    def lost(route, request, *, timeout_seconds):
        calls.append(request.idempotency_key)
        return GatewayClientResult(outcome, code=code)
    monkeypatch.setattr(api, 'reserve_order', lost)
    order = bt.BuyOrder(owner=strategy, data=data, size=1, price=10, exectype=bt.Order.Limit)
    order.addinfo(offset='open', quantity_unit='lots', time_in_force='GFD')
    broker.submit(order)
    key = calls[0]
    saved = host.local_order_notifications()[key]['notification_id']
    data2, broker2, strategy2 = framework()
    broker2.bind_gateway_execution_stream(strategy2, api=api, host=host, data_by_ref={'rb': data2},
        orders_by_key={}, instrument_by_ref={'rb': INSTRUMENT},
        time_policy=GatewayExecutionTimePolicy('CTP___FUTURE', 'UTC'), sequence=state.sequence)
    restored = next(iter(broker2.orders.values()))
    assert restored.ref != order.ref and restored.info.gateway_original_bt_ref == order.ref
    notice = broker2.get_notification()
    assert notice.notification_id == saved and notice.replayed is True
    strategy2._addnotification(notice)
    strategy2._notify()
    assert host.local_order_notifications()[key]['status'] == 'confirmed'
    assert len(calls) == 1
    assert host.load_execution_checkpoint().acknowledged_sequence == 0
    status_calls = []
    monkeypatch.setattr(api, 'command_status', lambda _route, original_key, **_kw:
        (status_calls.append(original_key) or GatewayClientResult('REQUEST_DENIED', code='NOT_FOUND')))
    broker2.next()
    # The reply of that reserve was lost in an earlier process and the Gateway
    # has no command under the key: nothing was reserved, nothing can have been
    # sent. The order ends Rejected (it used to stay RECOVERY_PENDING for good
    # and blocked every later order of the strategy) and is never sent again.
    assert status_calls == [key] and calls == [key]
    assert restored.status == restored.Rejected and not restored.executed.size
    assert restored.info.gateway_request_denied == 'RESERVATION_NOT_FOUND'
    assert host.local_order_notifications()['reject:' + key]['status'] == 'pending'
    strategy2.clear()  # as Cerebro does after each notification cycle
    deliver(broker2, strategy2)
    assert host.local_order_notifications()['reject:' + key]['status'] == 'confirmed'
    broker2.next()
    assert status_calls == [key] and calls == [key]  # terminal: not asked about again
    # (this fixture has no stream to read; the point is that recovery is over)
    assert broker2.gateway_execution_stream_status() != 'RECOVERY_PENDING'
    third = _limit_order(strategy2, data2, price=12)
    monkeypatch.setattr(broker2, "_gateway_require_trade_qualification", lambda *_: SYNTHETIC_MARKET_REF)
    broker2.submit(third)  # no ORDER_RECONCILE_REQUIRED any more
    assert len(calls) == 2 and calls[1] != key


def test_unknown_reserve_of_this_session_is_not_called_absent_too_early(state, ready, inputs, monkeypatch):
    # In the same session a lost reply may belong to a reserve that is still
    # waiting for the Gateway's owner thread: "not found" is final only later.
    import backtrader.brokers._btapi_gateway_stream as module
    from bt_api_py.gateway_direct_client import GatewayClientResult

    host, api, data, broker, strategy = _bound_submit_fixture(state, ready, inputs, monkeypatch)
    monkeypatch.setattr(api, 'reserve_order', lambda route, request, **kw:
                        GatewayClientResult('UNKNOWN', code='RPC_OUTCOME_UNKNOWN'))
    statuses = []
    monkeypatch.setattr(api, 'command_status', lambda _route, key, **_kw:
        (statuses.append(key) or GatewayClientResult('REQUEST_DENIED', code='NOT_FOUND')))
    order = _limit_order(strategy, data)
    broker.submit(order)
    key = order.info.gateway_request_key
    deliver(broker, strategy)
    broker.next()
    assert order.status == order.Submitted and statuses == [key]
    assert broker.gateway_execution_stream_status() == 'RECOVERY_PENDING'
    binding = broker._gateway_stream_binding
    binding.reserve_unknown[key] -= module._RESERVE_ABSENT_AFTER_SECONDS  # that long ago
    broker.next()
    assert order.status == order.Rejected and order.info.gateway_request_denied == 'RESERVATION_NOT_FOUND'
    assert key not in binding.reserve_unknown


@pytest.mark.parametrize('outcome,code', [('REQUEST_DENIED', 'SCOPE_DENIED'), ('UNKNOWN', 'RPC_OUTCOME_UNKNOWN'),
                                          ('TRANSPORT_NOT_STARTED', 'TIMEOUT_BEFORE_START')])
def test_only_a_validated_not_found_ends_an_unknown_reserve(state, ready, inputs, monkeypatch, outcome, code):
    from bt_api_py.gateway_direct_client import GatewayClientResult

    host, api, data, broker, strategy = _bound_submit_fixture(state, ready, inputs, monkeypatch)
    monkeypatch.setattr(api, 'reserve_order', lambda route, request, **kw:
                        GatewayClientResult('UNKNOWN', code='RPC_OUTCOME_UNKNOWN'))
    monkeypatch.setattr(api, 'command_status', lambda *_a, **_kw: GatewayClientResult(outcome, code=code))
    order = _limit_order(strategy, data)
    broker.submit(order)
    deliver(broker, strategy)
    broker._gateway_stream_binding.reserve_unknown.clear()  # as after a restart
    broker.next()
    assert order.status == order.Submitted
    assert broker.gateway_execution_stream_status() == 'RECOVERY_PENDING'


def test_local_submitted_callback_can_submit_next_order(state, ready, inputs, monkeypatch):
    from backtrader.live_state.gateway_pending import GatewayPendingHost
    from bt_api_py.gateway_direct_client import GatewayClientResult
    from tests.unit.live_state.test_gateway_pending import observe

    _, binding, _ = ready
    host = GatewayPendingHost.upgrade_for_order_state(state.strategy_dir, state.strategy_uuid, binding)
    state.sequence.allocate()
    api = api_for(host, inputs[1])
    data, broker, strategy = framework()
    monkeypatch.setattr(broker, "_gateway_require_trade_qualification", lambda *_: SYNTHETIC_MARKET_REF)  # synthetic order-path test
    broker.bind_gateway_execution_stream(strategy, api=api, host=host, data_by_ref={'rb': data},
        orders_by_key={}, instrument_by_ref={'rb': INSTRUMENT},
        time_policy=GatewayExecutionTimePolicy('CTP___FUTURE', 'UTC'), sequence=state.sequence)
    def reserve(route, request, *, timeout_seconds):
        intent = host.load_intent(request.idempotency_key)
        record = observe(intent)
        host.save_record(intent.request_key, record)
        return GatewayClientResult('OBSERVED', record)
    monkeypatch.setattr(api, 'reserve_order', reserve)
    def queued(route, key, **kwargs):
        host.commit_pre_dispatch(key, host.load_record(key))
        return GatewayClientResult('QUEUED', host.load_record(key))
    monkeypatch.setattr(api, 'dispatch_order', queued)
    emitted = []
    def callback(order):
        emitted.append(order.notification_id)
        if len(emitted) == 1:
            second = bt.BuyOrder(owner=strategy, data=data, size=1, price=11, exectype=bt.Order.Limit)
            second.addinfo(offset='open', quantity_unit='lots', time_in_force='GFD')
            broker.submit(second)
    strategy.notify_order = callback
    first = bt.BuyOrder(owner=strategy, data=data, size=1, price=10, exectype=bt.Order.Limit)
    first.addinfo(offset='open', quantity_unit='lots', time_in_force='GFD')
    broker.submit(first)
    deliver(broker, strategy)
    assert len(emitted) == 1
    assert sorted(row['status'] for row in host.local_order_notifications().values()) == ['confirmed', 'pending']
    broker.next()  # Release the local notification after the active callback finishes.
    deliver(broker, strategy)
    assert len(emitted) == 2 and emitted[0] != emitted[1]
    assert all(row['status'] == 'confirmed' for row in host.local_order_notifications().values())


def test_gateway_release_before_dispatch_notifies_and_recovers(state, ready, inputs, monkeypatch):
    from backtrader.live_state.gateway_pending import GatewayPendingHost
    from bt_api_py.gateway_direct_client import GatewayClientResult
    from tests.unit.live_state.test_gateway_pending import observe

    _, binding, _ = ready
    host = GatewayPendingHost.upgrade_for_order_state(state.strategy_dir, state.strategy_uuid, binding)
    state.sequence.allocate()
    api = api_for(host, inputs[1])
    data, broker, strategy = framework()
    monkeypatch.setattr(broker, "_gateway_require_trade_qualification", lambda *_: SYNTHETIC_MARKET_REF)  # synthetic order-path test
    broker.bind_gateway_execution_stream(strategy, api=api, host=host, data_by_ref={'rb': data},
        orders_by_key={}, instrument_by_ref={'rb': INSTRUMENT},
        time_policy=GatewayExecutionTimePolicy('CTP___FUTURE', 'UTC'), sequence=state.sequence)
    def reserve(route, request, *, timeout_seconds):
        intent = host.load_intent(request.idempotency_key)
        record = observe(intent)
        host.save_record(intent.request_key, record)
        return GatewayClientResult('OBSERVED', record)
    # Simulate dispatch not starting, leaving a proven RESERVED record.
    monkeypatch.setattr(api, 'reserve_order', reserve)
    monkeypatch.setattr(api, 'dispatch_order', lambda route, key, **kw:
                        GatewayClientResult('TRANSPORT_NOT_STARTED'))
    def release(route, key, *, operation_id, timeout_seconds):
        from bt_api_py.gateway_direct_client import GatewayReleasePlan
        reserved = host.load_record(key)
        host.save_release(GatewayReleasePlan(key, reserved.reservation_id, reserved.digest, operation_id, 1))
        record = replace(reserved, state='RELEASED', version=2, remaining_ttl_seconds=None,
                         release_operation_id=operation_id, release_expected_version=1)
        host.save_record(key, record)
        return GatewayClientResult('OBSERVED', record)
    monkeypatch.setattr(api, 'release_order', release)
    order = bt.BuyOrder(owner=strategy, data=data, size=1, price=10, exectype=bt.Order.Limit)
    order.addinfo(offset='open', quantity_unit='lots', time_in_force='GFD')
    broker.submit(order)
    key = order.info.gateway_request_key
    broker.cancel(order)
    assert order.status == order.Canceled
    ids = host.local_order_notifications()
    assert ids[key]['status'] == ids['cancel:' + key]['status'] == 'pending'
    data2, broker2, strategy2 = framework()
    broker2.bind_gateway_execution_stream(strategy2, api=api, host=host, data_by_ref={'rb': data2},
        orders_by_key={}, instrument_by_ref={'rb': INSTRUMENT},
        time_policy=GatewayExecutionTimePolicy('CTP___FUTURE', 'UTC'), sequence=state.sequence)
    assert next(iter(broker2.orders.values())).status == order.Canceled
    deliver(broker2, strategy2)
    deliver(broker2, strategy2)
    assert [event[1] for event in strategy2.events] == [ids[key]['notification_id'], ids['cancel:' + key]['notification_id']]
    assert all(row['status'] == 'confirmed' for row in host.local_order_notifications().values())
    assert host.load_execution_checkpoint().acknowledged_sequence == 0


def test_released_record_before_local_cancel_is_repaired_on_restart(state, ready, inputs, monkeypatch):
    from backtrader.live_state.gateway_pending import GatewayPendingHost
    from bt_api_py.gateway_direct_client import GatewayClientResult, GatewayReleasePlan
    from tests.unit.live_state.test_gateway_pending import observe

    _, binding, _ = ready
    host = GatewayPendingHost.upgrade_for_order_state(state.strategy_dir, state.strategy_uuid, binding)
    state.sequence.allocate()
    api = api_for(host, inputs[1])
    data, broker, strategy = framework()
    monkeypatch.setattr(broker, "_gateway_require_trade_qualification", lambda *_: SYNTHETIC_MARKET_REF)  # synthetic order-path test
    broker.bind_gateway_execution_stream(strategy, api=api, host=host, data_by_ref={'rb': data},
        orders_by_key={}, instrument_by_ref={'rb': INSTRUMENT},
        time_policy=GatewayExecutionTimePolicy('CTP___FUTURE', 'UTC'), sequence=state.sequence)
    def reserve(route, request, *, timeout_seconds):
        record = observe(host.load_intent(request.idempotency_key))
        host.save_record(request.idempotency_key, record)
        return GatewayClientResult('OBSERVED', record)
    monkeypatch.setattr(api, 'reserve_order', reserve)
    monkeypatch.setattr(api, 'dispatch_order', lambda *a, **kw: GatewayClientResult('TRANSPORT_NOT_STARTED'))
    def release_then_lost(route, key, *, operation_id, timeout_seconds):
        reserved = host.load_record(key)
        host.save_release(GatewayReleasePlan(key, reserved.reservation_id, reserved.digest, operation_id, 1))
        host.save_record(key, replace(reserved, state='RELEASED', version=2,
            remaining_ttl_seconds=None, release_operation_id=operation_id, release_expected_version=1))
        raise OSError('lost reply after persistence')
    monkeypatch.setattr(api, 'release_order', release_then_lost)
    order = bt.BuyOrder(owner=strategy, data=data, size=1, price=10, exectype=bt.Order.Limit)
    order.addinfo(offset='open', quantity_unit='lots', time_in_force='GFD')
    broker.submit(order)
    key = order.info.gateway_request_key
    with pytest.raises(OSError, match='lost reply'):
        broker.cancel(order)
    assert 'cancel:' + key not in host.local_order_notifications()
    data2, broker2, strategy2 = framework()
    broker2.bind_gateway_execution_stream(strategy2, api=api, host=host, data_by_ref={'rb': data2},
        orders_by_key={}, instrument_by_ref={'rb': INSTRUMENT},
        time_policy=GatewayExecutionTimePolicy('CTP___FUTURE', 'UTC'), sequence=state.sequence)
    assert host.local_order_notifications()['cancel:' + key]['status'] == 'pending'
    deliver(broker2, strategy2)
    deliver(broker2, strategy2)
    assert next(iter(broker2.orders.values())).status == order.Canceled
    assert all(item['status'] == 'confirmed' for item in host.local_order_notifications().values())


def test_local_notification_callback_failure_replays_same_id(state, ready, inputs, monkeypatch):
    from backtrader.live_state.gateway_pending import GatewayPendingHost
    from bt_api_py.gateway_direct_client import GatewayClientResult
    from tests.unit.live_state.test_gateway_pending import observe

    _, binding, _ = ready
    host = GatewayPendingHost.upgrade_for_order_state(state.strategy_dir, state.strategy_uuid, binding)
    state.sequence.allocate()
    api = api_for(host, inputs[1])
    data, broker, strategy = framework()
    monkeypatch.setattr(broker, "_gateway_require_trade_qualification", lambda *_: SYNTHETIC_MARKET_REF)  # synthetic order-path test
    broker.bind_gateway_execution_stream(strategy, api=api, host=host, data_by_ref={'rb': data},
        orders_by_key={}, instrument_by_ref={'rb': INSTRUMENT},
        time_policy=GatewayExecutionTimePolicy('CTP___FUTURE', 'UTC'), sequence=state.sequence)
    def reserve(route, request, *, timeout_seconds):
        record = observe(host.load_intent(request.idempotency_key))
        host.save_record(request.idempotency_key, record)
        return GatewayClientResult('OBSERVED', record)
    monkeypatch.setattr(api, 'reserve_order', reserve)
    monkeypatch.setattr(api, 'dispatch_order', lambda route, key, **kw:
                        GatewayClientResult('QUEUED', host.load_record(key)))
    order = bt.BuyOrder(owner=strategy, data=data, size=1, price=10, exectype=bt.Order.Limit)
    order.addinfo(offset='open', quantity_unit='lots', time_in_force='GFD')
    broker.submit(order)
    key = order.info.gateway_request_key
    strategy.fail = 'order'
    strategy._addnotification(broker.get_notification())
    with pytest.raises(RuntimeError, match='callback'):
        strategy._notify()
    assert host.local_order_notifications()[key]['status'] == 'pending'
    ident = strategy.events[0][1]
    strategy.fail = None
    strategy._notify()
    assert strategy.events[-1][1:3] == (ident, True)
    assert host.local_order_notifications()[key]['status'] == 'confirmed'
    assert host.load_execution_checkpoint().acknowledged_sequence == 0


def test_restores_new_local_order_after_an_older_execution_projection(state, ready, inputs, monkeypatch):
    from backtrader.live_state.gateway_pending import GatewayPendingHost
    from bt_api_py.gateway_direct_client import GatewayClientResult

    host, broker, strategy, original, calls, api = attach(
        ready, inputs, monkeypatch, [event_for(ready[0])])
    monkeypatch.setattr(broker, '_gateway_require_trade_qualification', lambda *_: SYNTHETIC_MARKET_REF)  # synthetic order-path test
    GatewayPendingHost.upgrade_for_order_state(state.strategy_dir, state.strategy_uuid, host._binding)
    host.upgrade_for_local_notifications()
    state.sequence.allocate(original.ref)  # key-a was created by a synthetic fixture
    broker._gateway_stream_binding.sequence = state.sequence
    broker.next()
    deliver(broker, strategy)
    assert host.load_execution_checkpoint().applied_sequence == 3
    monkeypatch.setattr(api, 'reserve_order', lambda *a, **kw: GatewayClientResult('UNKNOWN'))
    newer = bt.BuyOrder(owner=strategy, data=original.data, size=1, price=11, exectype=bt.Order.Limit)
    newer.addinfo(offset='open', quantity_unit='lots', time_in_force='GFD')
    broker.submit(newer)
    key = newer.info.gateway_request_key
    assert host.local_order_notifications()[key]['status'] == 'pending'
    data2, broker2, strategy2 = framework()
    broker2.bind_gateway_execution_stream(strategy2, api=api, host=host, data_by_ref={'rb': data2},
        orders_by_key={}, instrument_by_ref={'rb': INSTRUMENT},
        time_policy=GatewayExecutionTimePolicy('CTP___FUTURE', 'UTC'), sequence=state.sequence)
    restored = broker2._gateway_binding(strategy2, required=True).orders
    assert set(restored) == {'key-a', key}
    assert restored['key-a'].executed.size == 0.4
    assert restored[key].executed.size == 0 and restored[key].status == restored[key].Submitted
    deliver(broker2, strategy2)
    assert host.local_order_notifications()[key]['status'] == 'confirmed'
    assert broker2.positions['rb'].size == 0.4


def test_failed_local_order_persistence_never_sends_rpc(state, ready, inputs, monkeypatch):
    from backtrader.live_state.gateway_pending import GatewayPendingHost

    _, binding, _ = ready
    host = GatewayPendingHost.upgrade_for_order_state(state.strategy_dir, state.strategy_uuid, binding)
    state.sequence.allocate()
    api = api_for(host, inputs[1])
    data, broker, strategy = framework()
    monkeypatch.setattr(broker, "_gateway_require_trade_qualification", lambda *_: SYNTHETIC_MARKET_REF)  # synthetic order-path test
    broker.bind_gateway_execution_stream(strategy, api=api, host=host, data_by_ref={'rb': data},
        orders_by_key={}, instrument_by_ref={'rb': INSTRUMENT},
        time_policy=GatewayExecutionTimePolicy('CTP___FUTURE', 'UTC'), sequence=state.sequence)
    calls = []
    monkeypatch.setattr(api, 'reserve_order', lambda *a, **kw: calls.append('reserve'))
    monkeypatch.setattr(host, 'save_submitted_order_intent',
                        lambda *a, **kw: (_ for _ in ()).throw(OSError('disk')))
    order = bt.BuyOrder(owner=strategy, data=data, size=1, price=10, exectype=bt.Order.Limit)
    order.addinfo(offset='open', quantity_unit='lots', time_in_force='GFD')
    with pytest.raises(OSError, match='disk'):
        broker.submit(order)
    assert not calls and broker.gateway_execution_stream_status() == 'RESTART_REQUIRED'


def test_reserved_without_dispatch_marker_waits_on_original_key(state, ready, inputs, monkeypatch):
    from backtrader.live_state.gateway_pending import GatewayPendingHost
    from bt_api_py.gateway_direct_client import GatewayClientResult
    from tests.unit.live_state.test_gateway_pending import observe
    _, binding, _ = ready
    host = GatewayPendingHost.upgrade_for_order_state(state.strategy_dir, state.strategy_uuid, binding)
    state.sequence.allocate()
    api = api_for(host, inputs[1])
    data, broker, strategy = framework()
    monkeypatch.setattr(broker, "_gateway_require_trade_qualification", lambda *_: SYNTHETIC_MARKET_REF)  # synthetic order-path test
    broker.bind_gateway_execution_stream(strategy, api=api, host=host, data_by_ref={'rb': data},
        orders_by_key={}, instrument_by_ref={'rb': INSTRUMENT},
        time_policy=GatewayExecutionTimePolicy('CTP___FUTURE', 'UTC'), sequence=state.sequence)
    def reserve(route, request, *, timeout_seconds):
        record = observe(host.load_intent(request.idempotency_key))
        host.save_record(request.idempotency_key, record)
        return GatewayClientResult('OBSERVED', record)
    calls = []
    monkeypatch.setattr(api, 'reserve_order', reserve)
    monkeypatch.setattr(api, 'dispatch_order', lambda route, key, **kw:
                        (calls.append(('dispatch', key)) or GatewayClientResult('TRANSPORT_NOT_STARTED')))
    monkeypatch.setattr(api, 'command_status', lambda route, key, **kw:
                        (calls.append(('status', key)) or GatewayClientResult('OBSERVED', host.load_record(key))))
    order = bt.BuyOrder(owner=strategy, data=data, size=1, price=10, exectype=bt.Order.Limit)
    order.addinfo(offset='open', quantity_unit='lots', time_in_force='GFD')
    broker.submit(order)
    key = order.info.gateway_request_key
    deliver(broker, strategy)
    broker.next()
    assert broker.gateway_execution_stream_status() == 'RESERVATION_RECOVERY_PENDING'
    blocked = bt.BuyOrder(owner=strategy, data=data, size=1, price=11, exectype=bt.Order.Limit)
    blocked.addinfo(offset='open', quantity_unit='lots', time_in_force='GFD')
    with pytest.raises(RuntimeError, match='ORDER_RECONCILE_REQUIRED'):
        broker.submit(blocked)
    # Status, an unclear release (not patched here), then a status read that
    # still shows RESERVED: the reservation stays on the recovery path.
    assert calls == [('dispatch', key), ('status', key), ('status', key)]


def test_order_submitted_in_failed_remote_callback_waits_for_replay(state, ready, inputs, monkeypatch):
    from backtrader.live_state.gateway_pending import GatewayPendingHost
    from bt_api_py.gateway_direct_client import GatewayClientResult

    host, broker, strategy, original, calls, api = attach(
        ready, inputs, monkeypatch, [event_for(ready[0])])
    monkeypatch.setattr(broker, '_gateway_require_trade_qualification', lambda *_: SYNTHETIC_MARKET_REF)  # synthetic order-path test
    GatewayPendingHost.upgrade_for_order_state(state.strategy_dir, state.strategy_uuid, host._binding)
    host.upgrade_for_local_notifications()
    state.sequence.allocate(original.ref)
    broker._gateway_stream_binding.sequence = state.sequence
    monkeypatch.setattr(api, 'reserve_order', lambda *a, **kw: GatewayClientResult('UNKNOWN'))
    created = []
    def fail_after_submit(_order):
        newer = bt.BuyOrder(owner=strategy, data=original.data, size=1, price=11, exectype=bt.Order.Limit)
        newer.addinfo(offset='open', quantity_unit='lots', time_in_force='GFD')
        broker.submit(newer)
        created.append(newer)
        raise RuntimeError('callback after submit')
    strategy.notify_order = fail_after_submit
    broker.next()
    strategy._addnotification(broker.get_notification())
    with pytest.raises(RuntimeError, match='callback after submit'):
        strategy._notify()
    key = created[0].info.gateway_request_key
    assert host.local_order_notifications()[key]['status'] == 'pending'
    assert host.load_execution_notification_batch()['status'] == 'pending'
    assert broker.get_notification() is None
    data2, broker2, strategy2 = framework()
    broker2.bind_gateway_execution_stream(strategy2, api=api, host=host, data_by_ref={'rb': data2},
        orders_by_key={}, instrument_by_ref={'rb': INSTRUMENT},
        time_policy=GatewayExecutionTimePolicy('CTP___FUTURE', 'UTC'), sequence=state.sequence)
    assert broker2.get_notification() is None
    strategy2._notify()
    strategy2.clear()
    assert host.load_execution_notification_batch()['status'] == 'confirmed'
    broker2.next()
    assert calls['ack'] == [3]
    deliver(broker2, strategy2)
    assert host.local_order_notifications()[key]['status'] == 'confirmed'
    assert broker2.positions['rb'].size == 0.4


@pytest.mark.parametrize('info,code', [
    ({'quantity_unit': 'lots', 'time_in_force': 'GFD'}, 'ORDER_OFFSET_REQUIRED'),
    ({'offset': 'open', 'quantity_unit': 'lots', 'time_in_force': 'GFD',
      'exchange_id': 'another'}, 'INSTRUMENT_SCOPE'),
    ({'offset': 'open', 'quantity_unit': 'lots', 'time_in_force': 'GFD',
      'reduce_only': True}, 'ORDER_REDUCE_ONLY_INVALID'),
    ({'offset': 'close', 'quantity_unit': 'lots', 'time_in_force': 'GFD'},
     'STRATEGY_POSITION_UNAVAILABLE'),
])
def test_missing_or_conflicting_order_semantics_fail_before_intent_or_rpc(state, ready, inputs, monkeypatch, info, code):
    from backtrader.live_state.gateway_pending import GatewayPendingHost
    _, binding, _ = ready
    host = GatewayPendingHost.upgrade_for_order_state(state.strategy_dir, state.strategy_uuid, binding)
    state.sequence.allocate()
    api = api_for(host, inputs[1])
    data, broker, strategy = framework()
    monkeypatch.setattr(broker, "_gateway_require_trade_qualification", lambda *_: SYNTHETIC_MARKET_REF)  # synthetic order-path test
    broker.bind_gateway_execution_stream(strategy, api=api, host=host, data_by_ref={'rb': data},
        orders_by_key={}, instrument_by_ref={'rb': INSTRUMENT},
        time_policy=GatewayExecutionTimePolicy('CTP___FUTURE', 'UTC'), sequence=state.sequence)
    calls = []
    monkeypatch.setattr(api, 'reserve_order', lambda *args, **kw: calls.append('reserve'))
    before = state.sequence.local_seq
    order = bt.BuyOrder(owner=strategy, data=data, size=1, price=10, exectype=bt.Order.Limit)
    order.addinfo(**info)
    with pytest.raises(RuntimeError, match=code):
        broker.submit(order)
    assert state.sequence.local_seq == before and order.status == order.Created and not calls
    assert host.iter_order_snapshots() == {}


def test_contract_rules_require_full_instrument_and_route_binding(state, ready, inputs, monkeypatch):
    from types import SimpleNamespace
    from backtrader.live_state.gateway_pending import GatewayPendingHost
    from bt_api_py.gateway_direct_client import GatewayClientResult
    from bt_api_ctp.order_request_mapping import map_order_request
    _, binding, _ = ready
    host = GatewayPendingHost.upgrade_for_order_state(state.strategy_dir, state.strategy_uuid, binding)
    state.sequence.allocate()
    api = api_for(host, inputs[1])
    data, broker, strategy = framework()
    monkeypatch.setattr(broker, "_gateway_require_trade_qualification", lambda *_: SYNTHETIC_MARKET_REF)  # synthetic order-path test
    row = {'instrument_key': INSTRUMENT.to_dict(), 'exchange_name': 'CTP___FUTURE',
           'quantity_unit': 'lots', 'time_in_force': 'GFD'}
    broker.store = SimpleNamespace(contract_metadata={'rb': row})
    broker.bind_gateway_execution_stream(strategy, api=api, host=host, data_by_ref={'rb': data},
        orders_by_key={}, instrument_by_ref={'rb': INSTRUMENT},
        time_policy=GatewayExecutionTimePolicy('CTP___FUTURE', 'UTC'), sequence=state.sequence)
    calls = []
    def reserve(route, request, *, timeout_seconds):
        calls.append(request)
        return GatewayClientResult('UNKNOWN')
    monkeypatch.setattr(api, 'reserve_order', reserve)
    order = bt.BuyOrder(owner=strategy, data=data, size=1, price=10, exectype=bt.Order.Limit)
    order.addinfo(offset='open')
    row['instrument_key'] = replace(INSTRUMENT, venue='another').to_dict()
    with pytest.raises(RuntimeError, match='INSTRUMENT_RULE_SCOPE'):
        broker.submit(order)
    row['instrument_key'] = INSTRUMENT.to_dict()
    row['exchange_name'] = 'OTHER'
    with pytest.raises(RuntimeError, match='INSTRUMENT_RULE_SCOPE'):
        broker.submit(order)
    row['exchange_name'] = 'CTP___FUTURE'
    order.addinfo(quantity_unit='contracts')
    with pytest.raises(RuntimeError, match='INSTRUMENT_RULE_CONFLICT'):
        broker.submit(order)
    order.info.pop('quantity_unit')
    broker.submit(order)
    assert len(calls) == 1
    request = calls[0]
    assert (request.quantity_unit, request.time_in_force, request.offset, request.exchange_id) == (
        'lots', 'GFD', 'open', INSTRUMENT.venue)
    assert map_order_request(request)['offset'] == 'open'
    binding = broker._gateway_stream_binding
    broker._gateway_stream_order(binding, request.idempotency_key, order, allow_unreserved=True)
    order.price = 12
    with pytest.raises(RuntimeError, match='ORDER_BINDING'):
        broker._gateway_stream_order(binding, request.idempotency_key, order, allow_unreserved=True)


def test_gateway_order_rejects_plain_feed_before_any_durable_write_or_rpc(state, ready, inputs, monkeypatch):
    from backtrader.live_state.gateway_pending import GatewayPendingHost
    _, binding, _ = ready
    host = GatewayPendingHost.upgrade_for_order_state(state.strategy_dir, state.strategy_uuid, binding)
    state.sequence.allocate()
    api = api_for(host, inputs[1])
    data, broker, strategy = framework()  # PandasData is not real-time Gateway evidence.
    broker.bind_gateway_execution_stream(strategy, api=api, host=host, data_by_ref={'rb': data},
        orders_by_key={}, instrument_by_ref={'rb': INSTRUMENT},
        time_policy=GatewayExecutionTimePolicy('CTP___FUTURE', 'UTC'), sequence=state.sequence)
    calls = []
    monkeypatch.setattr(api, 'reserve_order', lambda *args, **kwargs: calls.append('reserve'))
    before_seq = state.sequence.local_seq
    before = host._store._load()
    order = bt.BuyOrder(owner=strategy, data=data, size=1, price=10, exectype=bt.Order.Limit)
    order.addinfo(offset='open', quantity_unit='lots', time_in_force='GFD')
    with pytest.raises(RuntimeError, match='FEED_NOT_TRADABLE'):
        broker.submit(order)
    assert state.sequence.local_seq == before_seq and host._store._load() == before
    assert order.status == order.Created and calls == []


def test_gateway_order_cannot_replace_missing_contract_rules_with_order_fields(state, ready, inputs, monkeypatch):
    from backtrader.live_state.gateway_pending import GatewayPendingHost
    _, binding, _ = ready
    host = GatewayPendingHost.upgrade_for_order_state(state.strategy_dir, state.strategy_uuid, binding)
    state.sequence.allocate()
    api = api_for(host, inputs[1])
    data, broker, strategy = framework()
    broker.store.contract_metadata = {}
    broker.bind_gateway_execution_stream(strategy, api=api, host=host, data_by_ref={'rb': data},
        orders_by_key={}, instrument_by_ref={'rb': INSTRUMENT},
        time_policy=GatewayExecutionTimePolicy('CTP___FUTURE', 'UTC'), sequence=state.sequence)
    calls = []
    monkeypatch.setattr(api, 'reserve_order', lambda *_a, **_kw: calls.append('reserve'))
    before_seq, before = state.sequence.local_seq, host._store._load()
    order = bt.BuyOrder(owner=strategy, data=data, size=1, price=10, exectype=bt.Order.Limit)
    order.addinfo(offset='open', quantity_unit='lots', time_in_force='GFD')
    with pytest.raises(RuntimeError, match='INSTRUMENT_RULES_UNAVAILABLE'):
        broker.submit(order)
    assert state.sequence.local_seq == before_seq and host._store._load() == before and not calls


def test_gateway_waits_for_first_feed_bar_without_direct_fallback(monkeypatch):
    from types import SimpleNamespace
    old_data, broker, strategy = framework()
    order = bt.BuyOrder(owner=strategy, data=old_data, size=1, price=10, exectype=bt.Order.Limit)
    data = bt.feeds.PandasData(dataname=old_data.p.dataname, name='rb')
    data._start()
    strategy.datas, strategy.data = [data], data
    calls = []
    store = SimpleNamespace(_gateway_mode=True, is_connected=True,
        gateway_strategy_config=SimpleNamespace(instruments_by_ref={'rb': INSTRUMENT}),
        gateway_sequence=object())
    def bind(_strategy, **_kwargs):
        calls.append('bind')
        broker._gateway_stream_binding = object()
    store.bind_gateway_strategy = bind
    broker.store = store
    broker.cerebro = SimpleNamespace(runningstrats=[strategy])
    broker.next()
    assert broker.gateway_execution_stream_status() == 'WAITING_FEED' and calls == []
    with pytest.raises(RuntimeError, match='FEED_NOT_READY'):
        broker.submit(order)
    assert calls == []
    assert data.load()
    assert broker._gateway_auto_bind(strategy) is strategy and calls == ['bind']


@pytest.mark.parametrize('ok,live,reasons', [
    (False, True, ('REALTIME_TICK_UNAVAILABLE',)),
    (False, False, ('FEED_NOT_LIVE',)),
    (False, True, ('RECEIVE_TIME_STALE',)),
    (True, False, ()),
    (True, True, ('CLOCK_UNVERIFIED',)),
])
def test_gateway_gate_rejects_unusable_feed_verdicts(monkeypatch, ok, live, reasons):
    from backtrader.feeds.btapifeed import BtApiFeed, FeedTradeQualification
    _, broker, _ = framework()
    source = object.__new__(BtApiFeed)
    source._history = []
    verdict = FeedTradeQualification(ok, reasons, live, None, None, None)
    monkeypatch.setattr(BtApiFeed, 'gateway_trade_qualification', lambda *_args, **_kwargs: verdict)
    with pytest.raises(RuntimeError, match='FEED_NOT_TRADABLE'):
        broker._gateway_require_trade_qualification(source, INSTRUMENT)


def test_gateway_gate_refuses_replay_and_warmup_even_if_stub_claims_ok(monkeypatch):
    from backtrader.feeds.btapifeed import BtApiFeed, FeedTradeQualification
    _, broker, _ = framework()
    source = object.__new__(BtApiFeed)
    source._history = []
    verdict = FeedTradeQualification(True, (), True, None, None, 0.0)
    monkeypatch.setattr(BtApiFeed, 'gateway_trade_qualification', lambda *_args, **_kwargs: verdict)
    source.replaying = True
    with pytest.raises(RuntimeError, match='FEED_NOT_TRADABLE'):
        broker._gateway_require_trade_qualification(source, INSTRUMENT)
    source.replaying = False
    source._history = [object()]
    with pytest.raises(RuntimeError, match='FEED_NOT_TRADABLE'):
        broker._gateway_require_trade_qualification(source, INSTRUMENT)


@pytest.mark.parametrize('expiry,allowed', [(None, False), (100, False), (101, True)])
def test_gateway_gate_requires_unexpired_local_clock_proof(monkeypatch, expiry, allowed):
    from backtrader.feeds.btapifeed import BtApiFeed, FeedTradeQualification
    from backtrader.brokers import _btapi_gateway_stream as stream_module
    _, broker, _ = framework()
    source = object.__new__(BtApiFeed)
    source._history = []
    verdict = FeedTradeQualification(True, (), True, None, None, 0.0, expiry, SYNTHETIC_MARKET_REF)
    monkeypatch.setattr(BtApiFeed, 'gateway_trade_qualification', lambda *_args, **_kwargs: verdict)
    monkeypatch.setattr(stream_module.time, 'monotonic_ns', lambda: 100)
    if allowed:
        broker._gateway_require_trade_qualification(source, INSTRUMENT)
    else:
        with pytest.raises(RuntimeError, match='FEED_NOT_TRADABLE'):
            broker._gateway_require_trade_qualification(source, INSTRUMENT)


def test_gateway_gate_rejects_absent_or_wrong_instrument_market_ref(monkeypatch):
    from backtrader.feeds.btapifeed import BtApiFeed, FeedTradeQualification
    from backtrader.brokers import _btapi_gateway_stream as stream_module
    _, broker, _ = framework()
    source = object.__new__(BtApiFeed)
    source._history = []
    monkeypatch.setattr(stream_module.time, 'monotonic_ns', lambda: 100)
    other_key = dict(SYNTHETIC_MARKET_REF['key'])
    other_key['instrument'] = replace(INSTRUMENT, native_symbol='other').to_dict()
    for ref in (None, {**SYNTHETIC_MARKET_REF, 'key': other_key}):
        verdict = FeedTradeQualification(True, (), True, None, None, 0.0, 101, ref)
        monkeypatch.setattr(BtApiFeed, 'gateway_trade_qualification', lambda *_a, **_kw: verdict)
        with pytest.raises(RuntimeError, match='FEED_NOT_TRADABLE'):
            broker._gateway_require_trade_qualification(source, INSTRUMENT)


def _bound_submit_fixture(state, ready, inputs, monkeypatch, *, qualify=True):
    from backtrader.live_state.gateway_pending import GatewayPendingHost

    _, binding, _ = ready
    host = GatewayPendingHost.upgrade_for_order_state(state.strategy_dir, state.strategy_uuid, binding)
    state.sequence.allocate()
    api = api_for(host, inputs[1])
    data, broker, strategy = framework()
    if qualify:
        monkeypatch.setattr(broker, "_gateway_require_trade_qualification",
                            lambda *_: SYNTHETIC_MARKET_REF)  # synthetic order-path test
    broker.bind_gateway_execution_stream(strategy, api=api, host=host, data_by_ref={'rb': data},
        orders_by_key={}, instrument_by_ref={'rb': INSTRUMENT},
        time_policy=GatewayExecutionTimePolicy('CTP___FUTURE', 'UTC'), sequence=state.sequence)
    return host, api, data, broker, strategy


def _rebind(state, host, api, monkeypatch=None):
    data, broker, strategy = framework()
    if monkeypatch is not None:
        monkeypatch.setattr(broker, "_gateway_require_trade_qualification",
                            lambda *_: SYNTHETIC_MARKET_REF)  # synthetic order-path test
    broker.bind_gateway_execution_stream(strategy, api=api, host=host, data_by_ref={'rb': data},
        orders_by_key={}, instrument_by_ref={'rb': INSTRUMENT},
        time_policy=GatewayExecutionTimePolicy('CTP___FUTURE', 'UTC'), sequence=state.sequence)
    return data, broker, strategy


def _emulated_release(host, calls=None, *, fail=0):
    from bt_api_py.gateway_direct_client import GatewayClientResult, GatewayReleasePlan

    remaining = [fail]

    def release(route, key, *, operation_id, timeout_seconds):
        if calls is not None:
            calls.append(('release', operation_id))
        if remaining[0]:
            remaining[0] -= 1
            raise OSError('synthetic release transport failure')
        reserved = host.load_record(key)
        if reserved.state != 'RELEASED':
            host.save_release(GatewayReleasePlan(key, reserved.reservation_id, reserved.digest,
                                                 operation_id, reserved.version))
            host.save_record(key, replace(reserved, state='RELEASED', version=reserved.version + 1,
                remaining_ttl_seconds=None, expiry_pending=False, release_operation_id=operation_id,
                release_expected_version=reserved.version))
        return GatewayClientResult('OBSERVED', host.load_record(key))
    return release


def _limit_order(strategy, data, price=10):
    order = bt.BuyOrder(owner=strategy, data=data, size=1, price=price, exectype=bt.Order.Limit)
    order.addinfo(offset='open', quantity_unit='lots', time_in_force='GFD')
    return order


@pytest.mark.parametrize('restart_before_delivery', [False, True])
def test_reserve_denial_rejects_locally_and_never_blocks_the_stream(
        state, ready, inputs, monkeypatch, restart_before_delivery):
    # SimNow 63.09: a validated REQUEST_DENIED reserve left the order Submitted
    # and every later next() returned RECOVERY_PENDING before reading events.
    from bt_api_py.gateway_direct_client import GatewayClientResult
    from tests.unit.live_state.test_gateway_pending import observe

    host, api, data, broker, strategy = _bound_submit_fixture(state, ready, inputs, monkeypatch)
    calls = []

    def denied(route, request, *, timeout_seconds):
        calls.append(('reserve', request.idempotency_key))
        return GatewayClientResult('REQUEST_DENIED', code='ADMISSION_DENIED')
    monkeypatch.setattr(api, 'reserve_order', denied)
    monkeypatch.setattr(api, 'dispatch_order', lambda *a, **kw: calls.append(('dispatch',)))
    monkeypatch.setattr(api, 'command_status', lambda *a, **kw: calls.append(('status',)))
    order = _limit_order(strategy, data)
    assert broker.submit(order) is order
    key = order.info.gateway_request_key
    assert order.status == order.Rejected and order.info.gateway_request_denied == 'ADMISSION_DENIED'
    notices = host.local_order_notifications()
    assert notices[key]['status'] == notices['reject:' + key]['status'] == 'pending'
    assert notices['reject:' + key]['code'] == 'ADMISSION_DENIED'
    assert host.load_record(key) is None
    if restart_before_delivery:
        data, broker, strategy = _rebind(state, host, api, monkeypatch)
        restored = next(iter(broker.orders.values()))
        assert restored.status == restored.Rejected
    deliver(broker, strategy)
    deliver(broker, strategy)
    assert [event[1] for event in strategy.events] == [
        notices[key]['notification_id'], notices['reject:' + key]['notification_id']]
    assert all(row['status'] == 'confirmed' for row in host.local_order_notifications().values())
    broker.next()
    assert broker.gateway_execution_stream_status() != 'RECOVERY_PENDING'
    assert ('status',) not in calls and ('dispatch',) not in calls

    def reserve(route, request, *, timeout_seconds):
        calls.append(('reserve', request.idempotency_key))
        record = observe(host.load_intent(request.idempotency_key))
        host.save_record(request.idempotency_key, record)
        return GatewayClientResult('OBSERVED', record)
    monkeypatch.setattr(api, 'reserve_order', reserve)
    monkeypatch.setattr(api, 'dispatch_order', lambda route, k, **kw:
                        GatewayClientResult('QUEUED', host.load_record(k)))
    second = _limit_order(strategy, data, price=11)
    broker.submit(second)  # no ORDER_RECONCILE_REQUIRED from the rejected intent
    assert [c[0] for c in calls].count('reserve') == 2
    _, broker3, _ = _rebind(state, host, api)
    by_key = {o.info.gateway_request_key: o for o in broker3.orders.values()}
    assert by_key[key].status == order.Rejected


def test_reserve_denial_rejection_is_validated_by_pending_state(state, ready, inputs, monkeypatch):
    from bt_api_py.gateway_direct_client import GatewayClientResult
    from tests.unit.live_state.test_gateway_pending import observe

    host, api, data, broker, strategy = _bound_submit_fixture(state, ready, inputs, monkeypatch)

    def reserve(route, request, *, timeout_seconds):
        record = observe(host.load_intent(request.idempotency_key))
        host.save_record(request.idempotency_key, record)
        return GatewayClientResult('OBSERVED', record)
    monkeypatch.setattr(api, 'reserve_order', reserve)
    monkeypatch.setattr(api, 'dispatch_order', lambda route, k, **kw:
                        GatewayClientResult('QUEUED', host.load_record(k)))
    order = _limit_order(strategy, data)
    broker.submit(order)
    key = order.info.gateway_request_key
    snapshot = host.load_order_snapshot(key)['snapshot']
    # A reservation exists: a local rejection is not provable.
    with pytest.raises(ValueError, match='GATEWAY_REJECTION_NOT_PROVEN'):
        host.save_rejected_order_notification(key, bt_ref=order.ref, snapshot=snapshot,
                                              code='ADMISSION_DENIED')
    with pytest.raises(ValueError, match='GATEWAY_LOCAL_NOTIFICATION_INVALID'):
        host.save_rejected_order_notification(key, bt_ref=order.ref, snapshot=snapshot,
                                              code='not a code')


@pytest.mark.parametrize('code', ['MARKET_GATE_UNAVAILABLE', 'DISPATCH_CLAIM_UNAVAILABLE'])
def test_dispatch_denial_releases_the_unsent_reservation(state, ready, inputs, monkeypatch, code):
    from bt_api_py.gateway_direct_client import GatewayClientResult
    from tests.unit.live_state.test_gateway_pending import observe

    host, api, data, broker, strategy = _bound_submit_fixture(state, ready, inputs, monkeypatch)
    calls = []

    def reserve(route, request, *, timeout_seconds):
        record = observe(host.load_intent(request.idempotency_key))
        host.save_record(request.idempotency_key, record)
        return GatewayClientResult('OBSERVED', record)
    monkeypatch.setattr(api, 'reserve_order', reserve)
    monkeypatch.setattr(api, 'dispatch_order', lambda *a, **kw: GatewayClientResult('REQUEST_DENIED', code=code))
    monkeypatch.setattr(api, 'release_order', _emulated_release(host, calls))
    order = _limit_order(strategy, data)
    broker.submit(order)
    key = order.info.gateway_request_key
    assert order.status == order.Canceled and order.info.gateway_dispatch_denied == code
    assert host.load_record(key).state == 'RELEASED'
    assert host.local_order_notifications()['cancel:' + key]['status'] == 'pending'
    assert calls == [('release', 'release-' + __import__('hashlib').sha256(key.encode()).hexdigest())]
    deliver(broker, strategy)
    deliver(broker, strategy)
    assert all(row['status'] == 'confirmed' for row in host.local_order_notifications().values())


@pytest.mark.parametrize('gateway_state', ['RESERVED', 'EXPIRED'])
def test_reservation_left_by_an_earlier_process_is_withdrawn_after_restart(
        state, ready, inputs, monkeypatch, gateway_state):
    # SimNow 63.09: an order whose dispatch was refused kept its RESERVED
    # record (with a marker); after a restart it stayed Submitted forever and
    # its non-current generation blocked new submits (ORDER_RECONCILE_REQUIRED).
    from bt_api_py.gateway_direct_client import GatewayClientResult
    from tests.unit.live_state.test_gateway_pending import observe

    host, api, data, broker, strategy = _bound_submit_fixture(state, ready, inputs, monkeypatch)

    def reserve(route, request, *, timeout_seconds):
        record = observe(host.load_intent(request.idempotency_key))
        host.save_record(request.idempotency_key, record)
        return GatewayClientResult('OBSERVED', record)

    def unknown_dispatch(route, key, **kwargs):
        host.commit_pre_dispatch(key, host.load_record(key))  # marker persisted before the RPC
        return GatewayClientResult('UNKNOWN', code='RPC_OUTCOME_UNKNOWN')
    monkeypatch.setattr(api, 'reserve_order', reserve)
    monkeypatch.setattr(api, 'dispatch_order', unknown_dispatch)
    order = _limit_order(strategy, data)
    broker.submit(order)
    key = order.info.gateway_request_key
    assert host.load_context(key).marker_id is not None
    deliver(broker, strategy)
    # The Gateway never dispatched it; the next process withdraws it.
    calls = []
    release = _emulated_release(host, calls)

    def status(route, k, **kwargs):
        calls.append(('status', k))
        record = host.load_record(k)
        if record.state == 'RESERVED' and record.generation_current:
            # The Gateway restarted: the reservation belongs to an old owner generation.
            record = replace(record, owner_generation=record.reservation_generation + "-restarted",
                             generation_current=False, remaining_ttl_seconds=0,
                             expiry_pending=True)
            host.save_record(k, record)
        if gateway_state == 'EXPIRED' and record.state == 'RESERVED':
            record = replace(record, state='EXPIRED', version=record.version + 1,
                             remaining_ttl_seconds=None, expiry_pending=False)
            host.save_record(k, record)
        return GatewayClientResult('OBSERVED', record)
    monkeypatch.setattr(api, 'command_status', status)
    monkeypatch.setattr(api, 'release_order', release)
    data2, broker2, strategy2 = _rebind(state, host, api, monkeypatch)
    restored = next(iter(broker2.orders.values()))
    broker2.next()
    assert restored.status == restored.Canceled
    assert host.load_record(key).state == ('RELEASED' if gateway_state == 'RESERVED' else 'EXPIRED')
    assert any(c[0] == 'release' for c in calls) == (gateway_state == 'RESERVED')
    deliver(broker2, strategy2)
    assert all(row['status'] == 'confirmed' for row in host.local_order_notifications().values())
    # A finalized order never blocks the next submit on the same data.
    monkeypatch.setattr(api, 'dispatch_order', lambda route, k, **kw:
                        GatewayClientResult('QUEUED', host.load_record(k)))
    second = _limit_order(strategy2, data2, price=11)
    broker2.submit(second)
    assert host.load_record(second.info.gateway_request_key).state == 'RESERVED'


def test_uncertain_dispatch_reservation_is_withdrawn_in_process(state, ready, inputs, monkeypatch):
    # A dispatch with an UNKNOWN outcome was never acknowledged: its RESERVED
    # reservation is read back and released instead of hanging until restart.
    from bt_api_py.gateway_direct_client import GatewayClientResult
    from tests.unit.live_state.test_gateway_pending import observe

    host, api, data, broker, strategy = _bound_submit_fixture(state, ready, inputs, monkeypatch)

    def reserve(route, request, *, timeout_seconds):
        record = observe(host.load_intent(request.idempotency_key))
        host.save_record(request.idempotency_key, record)
        return GatewayClientResult('OBSERVED', record)

    def unknown(route, key, **kwargs):
        host.commit_pre_dispatch(key, host.load_record(key))
        return GatewayClientResult('UNKNOWN', code='RPC_OUTCOME_UNKNOWN')
    calls = []
    monkeypatch.setattr(api, 'reserve_order', reserve)
    monkeypatch.setattr(api, 'dispatch_order', unknown)
    monkeypatch.setattr(api, 'command_status', lambda route, k, **kw:
                        GatewayClientResult('OBSERVED', host.load_record(k)))
    monkeypatch.setattr(api, 'release_order', _emulated_release(host, calls))
    order = _limit_order(strategy, data)
    broker.submit(order)
    assert order.status == order.Submitted
    deliver(broker, strategy)
    broker.next()
    assert order.status == order.Canceled and calls


def test_reservation_this_process_is_dispatching_is_not_withdrawn(state, ready, inputs, monkeypatch):
    from bt_api_py.gateway_direct_client import GatewayClientResult
    from tests.unit.live_state.test_gateway_pending import observe

    host, api, data, broker, strategy = _bound_submit_fixture(state, ready, inputs, monkeypatch)

    def reserve(route, request, *, timeout_seconds):
        record = observe(host.load_intent(request.idempotency_key))
        host.save_record(request.idempotency_key, record)
        return GatewayClientResult('OBSERVED', record)

    def queued(route, key, **kwargs):
        host.commit_pre_dispatch(key, host.load_record(key))
        return GatewayClientResult('QUEUED', host.load_record(key))
    calls = []
    monkeypatch.setattr(api, 'reserve_order', reserve)
    monkeypatch.setattr(api, 'dispatch_order', queued)
    monkeypatch.setattr(api, 'release_order', _emulated_release(host, calls))
    order = _limit_order(strategy, data)
    broker.submit(order)
    deliver(broker, strategy)
    broker.next()
    assert not calls and order.status == order.Submitted


def _queued_then_left_reserved(state, ready, inputs, monkeypatch):
    """A dispatch the Gateway acknowledged as queued and then never carried out (I63-E136)."""
    from bt_api_py.gateway_direct_client import GatewayClientResult
    from tests.unit.live_state.test_gateway_pending import observe

    host, api, data, broker, strategy = _bound_submit_fixture(state, ready, inputs, monkeypatch)

    def reserve(route, request, *, timeout_seconds):
        record = observe(host.load_intent(request.idempotency_key))
        host.save_record(request.idempotency_key, record)
        return GatewayClientResult('OBSERVED', record)

    def queued(route, key, **kwargs):
        host.commit_pre_dispatch(key, host.load_record(key))
        return GatewayClientResult('QUEUED', host.load_record(key))
    calls, gateway = [], {'record': None, 'outcome': 'OBSERVED'}

    def status(route, key, **kwargs):
        calls.append(('status', key))
        if gateway['outcome'] != 'OBSERVED':
            return GatewayClientResult(gateway['outcome'], code='RPC_OUTCOME_UNKNOWN')
        if gateway['record'] is not None:
            host.save_record(key, gateway['record'](host.load_record(key)))
        return GatewayClientResult('OBSERVED', host.load_record(key))
    monkeypatch.setattr(api, 'reserve_order', reserve)
    monkeypatch.setattr(api, 'dispatch_order', queued)
    monkeypatch.setattr(api, 'command_status', status)
    monkeypatch.setattr(api, 'release_order', _emulated_release(host, calls))
    import backtrader.brokers._btapi_gateway_stream as stream_module
    clock = [1000.0]
    monkeypatch.setattr(stream_module, 'time', SimpleNamespace(
        monotonic=lambda: clock[0], monotonic_ns=lambda: int(clock[0] * 1e9)))
    order = _limit_order(strategy, data)
    broker.submit(order)
    deliver(broker, strategy)

    def step(seconds=0.0):
        clock[0] += seconds
        broker._gateway_stream_binding.next_idle_read = 0.0
        broker.next()
    return host, broker, strategy, order, calls, gateway, step


@pytest.mark.parametrize('reason', ['time_over', 'older_generation'])
def test_queued_dispatch_that_can_no_longer_happen_is_withdrawn_in_process(
        state, ready, inputs, monkeypatch, reason):
    host, broker, strategy, order, calls, gateway, step = _queued_then_left_reserved(
        state, ready, inputs, monkeypatch)
    key = order.info.gateway_request_key
    step()                                                # first sight: only the next read is planned
    step(1.9)
    assert calls == [] and order.status == order.Submitted
    step(0.2)                                             # still dispatchable at the Gateway: untouched
    assert calls == [('status', key)] and order.status == order.Submitted
    gateway['record'] = (
        (lambda record: replace(record, remaining_ttl_seconds=0, expiry_pending=True))
        if reason == 'time_over' else
        (lambda record: replace(record, owner_generation=record.reservation_generation + '-restarted',
                                generation_current=False, remaining_ttl_seconds=0, expiry_pending=True)))
    step(1.0)                                             # not yet due again
    assert len(calls) == 1
    step(1.1)
    assert order.status == order.Canceled
    assert [call[0] for call in calls[1:]] == ['status', 'release']
    assert host.load_record(key).state == 'RELEASED'
    deliver(broker, strategy)
    assert all(row['status'] == 'confirmed' for row in host.local_order_notifications().values())
    step(5.0)
    assert len(calls) == 3                                # a finished order is not read again


def test_queued_dispatch_found_expired_at_the_gateway_is_finalized(state, ready, inputs, monkeypatch):
    host, broker, strategy, order, calls, gateway, step = _queued_then_left_reserved(
        state, ready, inputs, monkeypatch)
    gateway['record'] = lambda record: replace(record, state='EXPIRED', version=record.version + 1,
                                               remaining_ttl_seconds=None, expiry_pending=False)
    step()
    step(2.1)
    assert order.status == order.Canceled and [call[0] for call in calls] == ['status']


def test_queued_dispatch_with_an_unreadable_status_is_left_alone(state, ready, inputs, monkeypatch):
    host, broker, strategy, order, calls, gateway, step = _queued_then_left_reserved(
        state, ready, inputs, monkeypatch)
    gateway['outcome'] = 'UNKNOWN'
    step()
    step(2.1)
    assert order.status == order.Submitted and [call[0] for call in calls] == ['status']
    assert broker._gateway_stream_binding.state == 'RECOVERY_PENDING'


def test_queued_dispatch_whose_release_is_refused_is_not_ended_locally(state, ready, inputs, monkeypatch):
    """The dispatch won at the Gateway while the release was on its way: the order proceeds."""
    from bt_api_py.gateway_direct_client import GatewayClientResult

    host, broker, strategy, order, calls, gateway, step = _queued_then_left_reserved(
        state, ready, inputs, monkeypatch)
    gateway['record'] = lambda record: replace(record, remaining_ttl_seconds=0, expiry_pending=True)

    def refused(route, key, *, operation_id, timeout_seconds):
        calls.append(('release', operation_id))
        return GatewayClientResult('REQUEST_DENIED', code='STATE_CONFLICT')
    monkeypatch.setattr(broker._gateway_stream_binding.api, 'release_order', refused)
    step()
    step(2.1)
    assert [call[0] for call in calls] == ['status', 'release', 'status']
    assert order.status == order.Submitted
    assert order.info.gateway_request_key in broker._gateway_stream_binding.dispatched
    assert broker._gateway_stream_binding.state == 'RESERVATION_RECOVERY_PENDING'


@pytest.mark.parametrize('lost_ref', [False, True])
@pytest.mark.parametrize('release_failures', [0, 1])
def test_gateway_feed_losing_qualification_after_reserve_never_dispatches(
        state, ready, inputs, monkeypatch, lost_ref, release_failures):
    from backtrader.live_state.gateway_pending import GatewayPendingHost
    from bt_api_py.gateway_direct_client import GatewayClientResult
    from tests.unit.live_state.test_gateway_pending import observe
    _, binding, _ = ready
    host = GatewayPendingHost.upgrade_for_order_state(state.strategy_dir, state.strategy_uuid, binding)
    state.sequence.allocate()
    api = api_for(host, inputs[1])
    data, broker, strategy = framework()
    broker.bind_gateway_execution_stream(strategy, api=api, host=host, data_by_ref={'rb': data},
        orders_by_key={}, instrument_by_ref={'rb': INSTRUMENT},
        time_policy=GatewayExecutionTimePolicy('CTP___FUTURE', 'UTC'), sequence=state.sequence)
    calls = []
    def qualification(*_):
        calls.append('qualification')
        if calls.count('qualification') == 2:
            if lost_ref:
                return None
            raise RuntimeError('synthetic stale')
        return SYNTHETIC_MARKET_REF
    def reserve(route, request, *, timeout_seconds):
        record = observe(host.load_intent(request.idempotency_key))
        host.save_record(request.idempotency_key, record)
        calls.append('reserve')
        return GatewayClientResult('OBSERVED', record)
    monkeypatch.setattr(broker, '_gateway_require_trade_qualification', qualification)
    monkeypatch.setattr(api, 'reserve_order', reserve)
    monkeypatch.setattr(api, 'dispatch_order', lambda *args, **kwargs: calls.append('dispatch'))
    releases = []
    monkeypatch.setattr(api, 'release_order', _emulated_release(host, releases, fail=release_failures))
    order = bt.BuyOrder(owner=strategy, data=data, size=1, price=10, exectype=bt.Order.Limit)
    order.addinfo(offset='open', quantity_unit='lots', time_in_force='GFD')
    assert broker.submit(order) is order
    key = order.info.gateway_request_key
    assert calls == ['qualification', 'reserve', 'qualification']
    assert host.load_context(key).marker_id is None
    if release_failures:
        # Unclear release: the reservation stays on the recovery path.
        assert broker.gateway_execution_stream_status() == 'RELEASE_PENDING'
        assert host.load_record(key).state == 'RESERVED' and order.status == order.Submitted
        monkeypatch.setattr(api, 'command_status', lambda route, k, **kw:
                            GatewayClientResult('OBSERVED', host.load_record(k)))
        deliver(broker, strategy)  # the local Submitted notice
        broker.next()
    assert 'dispatch' not in calls
    assert host.load_record(key).state == 'RELEASED' and order.status == order.Canceled
    assert len({op for _, op in releases}) == 1 and len(releases) == 1 + release_failures


def _strategy_position_observation(binding, *, long='3', short='0', available=None):
    from bt_api_py.gateway_strategy_position import GatewayStrategyPositionObservation
    return GatewayStrategyPositionObservation(INSTRUMENT, 'lots', '20261107',
        Decimal(long), Decimal('0'), Decimal(short), Decimal('0'), False, 'owner', 'UNKNOWN',
        None if available is None else Decimal(available),
        None if available is None else Decimal('0'), 1, binding, 'registration', 'epoch')


def test_gateway_getposition_only_returns_fresh_strategy_position(ready, inputs, monkeypatch):
    from types import SimpleNamespace
    from bt_api_py.gateway_strategy_position import GatewayStrategyPositionResult
    host, broker, strategy, order, _, api = attach(ready, inputs, monkeypatch)
    broker.store = SimpleNamespace(_gateway_mode=True, is_connected=True, gateway_api=api,
                                   contract_metadata={
        'rb': {'instrument_key': INSTRUMENT.to_dict(), 'exchange_name': 'CTP___FUTURE',
               'quantity_unit': 'lots'}})
    observation = [_strategy_position_observation(host._binding)]
    monkeypatch.setattr(api, 'get_strategy_position', lambda *_a, **_kw:
                        GatewayStrategyPositionResult('OBSERVED', observation[0]))
    current = [True]
    monkeypatch.setattr(api, 'strategy_position_is_current', lambda *_a, **_kw: current[0])
    with pytest.raises(RuntimeError, match='GATEWAY_ACCOUNT_POSITION_UNAVAILABLE'):
        broker.getposition(order.data)
    position = broker.get_strategy_position(strategy, order.data)
    assert position.size == 3 and math.isnan(position.price)
    with pytest.raises(RuntimeError, match='STRATEGY_BINDING_UNAVAILABLE'):
        broker.get_strategy_position(object(), order.data)
    assert broker.gateway_financial_unavailable['cash'] == 'GATEWAY_ACCOUNT_CASH_UNAVAILABLE'
    observation[0] = _strategy_position_observation(host._binding, long='3', short='2')
    with pytest.raises(RuntimeError, match='POSITION_SIDE_REQUIRED'):
        broker.get_strategy_position(strategy, order.data)
    assert broker.get_strategy_position(strategy, order.data, side='short').size == 2
    observation[0] = _strategy_position_observation(host._binding, long='0', short='2')
    assert broker.get_strategy_position(strategy, order.data).size == -2
    current[0] = False
    with pytest.raises(RuntimeError, match='STRATEGY_POSITION_UNAVAILABLE'):
        broker.get_strategy_position(strategy, order.data)


@pytest.mark.parametrize('available,allowed', [('0', False), ('2', True)])
def test_gateway_close_requires_strategy_capacity_before_intent(state, ready, inputs, monkeypatch, available, allowed):
    from backtrader.live_state.gateway_pending import GatewayPendingHost
    from bt_api_py.gateway_direct_client import GatewayClientResult
    from bt_api_py.gateway_strategy_position import GatewayStrategyPositionResult
    _, binding, _ = ready
    host = GatewayPendingHost.upgrade_for_order_state(state.strategy_dir, state.strategy_uuid, binding)
    state.sequence.allocate()
    api = api_for(host, inputs[1])
    data, broker, strategy = framework()
    broker.bind_gateway_execution_stream(strategy, api=api, host=host, data_by_ref={'rb': data},
        orders_by_key={}, instrument_by_ref={'rb': INSTRUMENT},
        time_policy=GatewayExecutionTimePolicy('CTP___FUTURE', 'UTC'), sequence=state.sequence)
    monkeypatch.setattr(broker, '_gateway_require_trade_qualification', lambda *_: SYNTHETIC_MARKET_REF)
    observation = _strategy_position_observation(binding, available=available)
    monkeypatch.setattr(api, 'get_strategy_close_capacity', lambda *_a, **_kw:
                        GatewayStrategyPositionResult('OBSERVED', observation))
    monkeypatch.setattr(api, 'strategy_position_is_current', lambda *_a, **_kw: True)
    calls = []
    monkeypatch.setattr(api, 'reserve_order', lambda _route, request, **_kw:
                        (calls.append(request) or GatewayClientResult('UNKNOWN')))
    order = bt.SellOrder(owner=strategy, data=data, size=1, price=10, exectype=bt.Order.Limit)
    order.addinfo(offset='close', quantity_unit='lots', time_in_force='GFD')
    before = state.sequence.local_seq
    if allowed:
        broker.submit(order)
        assert len(calls) == 1 and calls[0].offset == 'close'
    else:
        with pytest.raises(RuntimeError, match='STRATEGY_CLOSE_UNAVAILABLE'):
            broker.submit(order)
        assert state.sequence.local_seq == before and calls == [] and order.status == order.Created


def test_gateway_financial_requires_explicit_strategy_and_verified_currency(ready, inputs, monkeypatch):
    from types import SimpleNamespace
    from bt_api_py.gateway_strategy_financial import GatewayStrategyFinancialObservation, GatewayStrategyFinancialResult
    host, broker, strategy, _, _, api = attach(ready, inputs, monkeypatch)
    broker.store = SimpleNamespace(_gateway_mode=True, is_connected=True, gateway_api=api,
        gateway_strategy_config=SimpleNamespace(strategy_finance_currency='CNY'))
    observation = GatewayStrategyFinancialObservation('CNY', 'futures_linear_v1', 1, 'cut', 'owner',
        'a' * 64, Decimal('42'), Decimal('-2'), 1, host._binding, 'registration', 'epoch')
    monkeypatch.setattr(api, 'get_strategy_financial', lambda *_a, **_kw:
                        GatewayStrategyFinancialResult('OBSERVED', observation))
    current = [True]
    monkeypatch.setattr(api, 'strategy_financial_is_current', lambda *_a, **_kw: current[0])
    assert broker.get_strategy_cash(strategy, currency='CNY') == -2
    assert broker.get_strategy_value(strategy, currency='CNY') == 42
    assert broker.get_strategy_cash(strategy) == -2
    with pytest.raises(RuntimeError, match='CURRENCY_MISMATCH'):
        broker.get_strategy_cash(strategy, currency='USD')
    with pytest.raises(RuntimeError, match='BINDING_UNAVAILABLE'):
        broker.get_strategy_cash(object(), currency='CNY')
    current[0] = False
    with pytest.raises(RuntimeError, match='STRATEGY_CASH_UNAVAILABLE'):
        broker.get_strategy_cash(strategy, currency='CNY')
    broker.store.gateway_strategy_config.strategy_finance_currency = None
    with pytest.raises(RuntimeError, match='CURRENCY_REQUIRED'):
        broker.get_strategy_cash(strategy)


def test_restore_accepts_locally_rejected_original_without_gateway_record(
        state, ready, inputs, monkeypatch):
    # SimNow 63.09 (2026-11-10 09:17): a reserve denial finalized locally as
    # Rejected has no Gateway record. Once a later execution event wrote a
    # projection listing it among the originals, every restart failed with
    # GATEWAY_NOTIFICATION_RESTORE_INVALID.
    from backtrader.live_state.gateway_pending import GatewayPendingHost
    from bt_api_py.gateway_direct_client import GatewayClientResult

    host, broker, strategy, original, calls, api = attach(
        ready, inputs, monkeypatch, [event_for(ready[0])])
    monkeypatch.setattr(broker, '_gateway_require_trade_qualification', lambda *_: SYNTHETIC_MARKET_REF)  # synthetic order-path test
    GatewayPendingHost.upgrade_for_order_state(state.strategy_dir, state.strategy_uuid, host._binding)
    host.upgrade_for_local_notifications()
    state.sequence.allocate(original.ref)  # key-a was created by a synthetic fixture
    broker._gateway_stream_binding.sequence = state.sequence
    monkeypatch.setattr(api, 'reserve_order', lambda *a, **kw:
                        GatewayClientResult('REQUEST_DENIED', code='ADMISSION_DENIED'))
    denied = bt.BuyOrder(owner=strategy, data=original.data, size=1, price=11, exectype=bt.Order.Limit)
    denied.addinfo(offset='open', quantity_unit='lots', time_in_force='GFD')
    broker.submit(denied)
    key = denied.info.gateway_request_key
    assert denied.status == denied.Rejected and host.load_record(key) is None
    def drain():
        while (notice := broker.get_notification()) is not None:
            strategy._addnotification(notice, quicknotify=False)
            strategy._notify()
            strategy.clear()

    for _ in range(6):  # local notices first, then key-a's event writes a new projection
        drain()
        broker.next()
    drain()
    checkpoint = host.load_execution_checkpoint()
    assert checkpoint.applied_sequence == 3, broker.gateway_execution_stream_status()
    assert key in checkpoint.projection['state']['_gateway_strategy']['originals']
    data2, broker2, strategy2 = framework()
    broker2.bind_gateway_execution_stream(strategy2, api=api, host=host, data_by_ref={'rb': data2},
        orders_by_key={}, instrument_by_ref={'rb': INSTRUMENT},
        time_policy=GatewayExecutionTimePolicy('CTP___FUTURE', 'UTC'), sequence=state.sequence)
    restored = broker2._gateway_binding(strategy2, required=True).orders
    assert restored[key].status == restored[key].Rejected
    assert restored['key-a'].executed.size == 0.4
    broker2.next()
    assert broker2.gateway_execution_stream_status() not in ('RECOVERY_PENDING', 'RESTART_REQUIRED')


def test_terminal_orders_are_skipped_by_submit_and_step_checks(state, ready, inputs, monkeypatch):
    # SimNow 63.09 (E108): every broker step loaded the full state once or twice
    # per known order, terminal ones included; a terminal order's stale local
    # record must also never block a new submit.
    from bt_api_py.gateway_direct_client import GatewayClientResult
    from tests.unit.live_state.test_gateway_pending import observe

    host, api, data, broker, strategy = _bound_submit_fixture(state, ready, inputs, monkeypatch)

    def reserve(route, request, *, timeout_seconds):
        record = observe(host.load_intent(request.idempotency_key))
        host.save_record(request.idempotency_key, record)
        return GatewayClientResult('OBSERVED', record)

    calls = []
    monkeypatch.setattr(api, 'reserve_order', reserve)
    monkeypatch.setattr(api, 'dispatch_order', lambda route, key, **kw:
                        (calls.append(('dispatch', key)) or GatewayClientResult('TRANSPORT_NOT_STARTED')))
    monkeypatch.setattr(api, 'command_status', lambda route, key, **kw:
                        (calls.append(('status', key)) or GatewayClientResult('OBSERVED', host.load_record(key))))
    order = bt.BuyOrder(owner=strategy, data=data, size=1, price=10, exectype=bt.Order.Limit)
    order.addinfo(offset='open', quantity_unit='lots', time_in_force='GFD')
    broker.submit(order)
    key = order.info.gateway_request_key
    deliver(broker, strategy)
    tracked = broker._gateway_binding(strategy, required=True).orders[key]
    tracked.status = tracked.Canceled  # its outcome became final (e.g. a venue cancel event)
    loads = []
    real_load = host.load_record
    monkeypatch.setattr(host, 'load_record', lambda k: loads.append(k) or real_load(k))
    calls.clear()
    broker.next()
    assert key not in loads and ('status', key) not in calls
    second = bt.BuyOrder(owner=strategy, data=data, size=1, price=11, exectype=bt.Order.Limit)
    second.addinfo(offset='open', quantity_unit='lots', time_in_force='GFD')
    broker.submit(second)  # no ORDER_RECONCILE_REQUIRED from the terminal order
    assert second.info.gateway_request_key != key


def test_unreachable_gateway_waits_instead_of_ending_the_strategy(ready, inputs, monkeypatch):
    # SimNow 63.09 (I63-E112): pausing or restarting the Gateway ended the
    # strategy with GATEWAY_STREAM_SCOPE; it must wait, refuse submits and
    # resume reading once the session is healthy again.
    from types import SimpleNamespace

    host, broker, strategy, order, calls, api = attach(ready, inputs, monkeypatch)
    store = SimpleNamespace(_gateway_mode=True, is_connected=False, gateway_api=api,
                            gateway_session_state=lambda: "UNAVAILABLE")
    monkeypatch.setattr(broker, "store", store)
    broker.next()
    broker.next()
    assert broker.gateway_execution_stream_status() == "GATEWAY_UNAVAILABLE"
    assert calls["read"] == 0 and not calls["ack"]
    second = bt.BuyOrder(owner=strategy, data=order.data, size=1, price=11, exectype=bt.Order.Limit)
    second.addinfo(offset="open", quantity_unit="lots", time_in_force="GFD")
    with pytest.raises(RuntimeError, match="GATEWAY_STREAM_GATEWAY_UNAVAILABLE"):
        broker._gateway_stream_check(broker._gateway_stream_binding)
    store.is_connected = True
    broker.next()  # reconnected: the same binding reads again
    assert calls["read"] >= 1
    assert broker.gateway_execution_stream_status() != "GATEWAY_UNAVAILABLE"


def test_lost_session_of_a_stopped_store_ends_the_strategy(ready, inputs, monkeypatch):
    # Only a Store that was stopped or lost its run lock ends the strategy with
    # SESSION_LOST (it cannot register again); see the D63-03 tests below for a
    # lost session of a running Store.
    from types import SimpleNamespace

    host, broker, strategy, order, calls, api = attach(ready, inputs, monkeypatch)
    state = {"value": "UNAVAILABLE"}
    reconnects = []
    store = SimpleNamespace(_gateway_mode=True, is_connected=False, gateway_api=api,
                            gateway_session_state=lambda: state["value"],
                            gateway_session_recoverable=lambda: False,
                            gateway_reconnect=lambda: reconnects.append(1) or False)
    monkeypatch.setattr(broker, "store", store)
    broker.next()
    assert broker.gateway_execution_stream_status() == "GATEWAY_UNAVAILABLE"
    state["value"] = "LOST"
    with pytest.raises(RuntimeError, match="GATEWAY_STREAM_SESSION_LOST"):
        broker.next()
    assert calls["read"] == 0 and not calls["ack"] and not reconnects


def _lost_session_store(api, state):
    class Store:
        _gateway_mode = True
        reconnects = 0

        def __init__(self):
            self.gateway_api = api

        @property
        def is_connected(self):
            return state["session"] == "CONNECTED"

        def gateway_session_state(self):
            return state["session"]

        def gateway_session_recoverable(self):
            return True

        def gateway_reconnect(self):
            self.reconnects += 1
            replacement = state.get("replacement")
            if replacement is None:
                return False
            self.gateway_api = replacement
            state["session"] = "CONNECTED"
            return True

    return Store()


def test_lost_session_of_a_running_store_waits_and_registers_again(ready, inputs, monkeypatch):
    # D63-03: a Gateway restart (new service epoch) or an expired lease loses
    # the SDK session for good. The strategy keeps running, refuses submits,
    # and continues with a newly registered session: same orders, same durable
    # cursor, nothing re-sent.
    host, broker, strategy, order, calls, api = attach(ready, inputs, monkeypatch)
    _, route, _ = inputs
    binding = broker._gateway_stream_binding
    binding.dispatched.add("key-a")
    state = {"session": "LOST"}
    store = _lost_session_store(api, state)
    monkeypatch.setattr(broker, "store", store)
    for _ in range(3):
        broker.next()  # the Gateway is still away: wait, never raise
    assert store.reconnects == 3 and binding.api is api
    assert broker.gateway_execution_stream_status() == "GATEWAY_UNAVAILABLE"
    assert calls["read"] == 0 and not calls["ack"]
    with pytest.raises(RuntimeError, match="GATEWAY_STREAM_GATEWAY_UNAVAILABLE"):
        broker._gateway_stream_check(binding)
    # A status read or a submit check never starts a registration by itself.
    assert store.reconnects == 3

    replacement = api_for(host, route)
    new_stream = replacement.gateway_execution_stream("CTP___FUTURE")
    reads = []

    def read(after, epoch, limit, *, timeout_seconds):
        reads.append(after)
        _, bound, consumer = ready
        return GatewayExecutionStreamClientResult(
            "OBSERVED", page=page(bound, consumer, []),
            request_context=GatewayExecutionReadContext(bound, consumer, after, epoch, limit))

    monkeypatch.setattr(new_stream, "read_after", read)
    api.close()  # the Store closed the lost session before registering again
    state["replacement"] = replacement
    stored = host.load_execution_checkpoint().stored_sequence
    broker.next()
    assert binding.api is replacement and binding.stream is new_stream
    assert reads == [stored] and calls["read"] == 0  # resumes after the stored sequence
    assert not binding.dispatched  # old acknowledgements are read back, not trusted
    assert broker.gateway_execution_stream_status() == "ACTIVE"
    assert broker._gateway_binding(strategy, required=True).orders["key-a"] is order
    broker._gateway_stream_check(binding)  # usable again


def test_replaced_session_is_not_used_before_the_step_adopts_it(ready, inputs, monkeypatch):
    host, broker, strategy, order, calls, api = attach(ready, inputs, monkeypatch)
    _, route, _ = inputs
    binding = broker._gateway_stream_binding
    replacement = api_for(host, route)
    state = {"session": "CONNECTED"}
    store = _lost_session_store(replacement, state)  # the Store already holds the new session
    monkeypatch.setattr(broker, "store", store)
    api.close()
    assert broker.gateway_execution_stream_status() == "GATEWAY_UNAVAILABLE"
    with pytest.raises(RuntimeError, match="GATEWAY_STREAM_GATEWAY_UNAVAILABLE"):
        broker._gateway_stream_check(binding)
    assert binding.api is api and calls["read"] == 0


def test_new_session_for_another_host_is_refused(ready, inputs, monkeypatch, state):
    from backtrader.live_state.gateway_pending import GatewayPendingHost

    host, broker, strategy, order, calls, api = attach(ready, inputs, monkeypatch)
    binding = broker._gateway_stream_binding
    # A valid session of the same strategy state, but over another host object:
    # the binding's durable host must stay the exact one it was bound with.
    other_host = GatewayPendingHost.upgrade_for_execution(
        state.strategy_dir, state.strategy_uuid, ready[1], consumer_ref=ready[2])
    assert other_host is not host and other_host._binding == host._binding
    foreign = api_for(other_host, inputs[1])
    state = {"session": "CONNECTED"}
    monkeypatch.setattr(broker, "store", _lost_session_store(foreign, state))
    api.close()
    with pytest.raises(RuntimeError, match="GATEWAY_STREAM_SCOPE"):
        broker.next()
    assert binding.state == "RESTART_REQUIRED" and binding.api is api
    with pytest.raises(RuntimeError, match="GATEWAY_STREAM_RESTART_REQUIRED"):
        broker.next()


# ---------------------------------------------------------------------------
# D62-19 in Gateway mode: a stopping strategy cancels its own working orders
# ---------------------------------------------------------------------------
def _cancelled_event(host):
    from bt_api_base.direct_write_protocol import DirectExecutionEventKind, DirectOrderStatus
    from bt_api_base.gateway_execution_stream_protocol import GatewayExecutionObservation

    source = make_event(host)
    original = source.observation
    obs = GatewayExecutionObservation(account_scope=original.account_scope, route=original.route,
        instrument=original.instrument, trading_day=original.trading_day,
        kind=DirectExecutionEventKind.ORDER, native_identity_digest=original.native_identity_digest,
        identity_key_digests=original.identity_key_digests, binding_key_digests=original.binding_key_digests,
        venue_key_digest=original.venue_key_digest, status=DirectOrderStatus.CANCELLED,
        side="buy", order_quantity="1", filled_quantity="0", remaining_quantity="1")
    return replace(source, observation=obs)


def _stop_fixture(ready, inputs, monkeypatch, events, *, timeout):
    from bt_api_py.gateway_direct_client import GatewayClientResult

    host, broker, strategy, order, calls, api = attach(ready, inputs, monkeypatch, events)
    broker._gateway_stream_binding.sequence = object()  # a write-capable binding
    monkeypatch.setattr(broker.p, "stop_cancel_timeout", timeout, raising=False)
    cancels = []

    def cancel(route, key, *, operation_id, timeout_seconds):
        cancels.append((key, operation_id))
        return GatewayClientResult("QUEUED")

    monkeypatch.setattr(api, "cancel_order", cancel)
    return host, broker, strategy, order, calls, api, cancels


def test_stopping_gateway_strategy_cancels_its_working_order_and_waits_for_the_venue(ready, inputs, monkeypatch):
    host, broker, strategy, order, calls, api, cancels = _stop_fixture(
        ready, inputs, monkeypatch, [_cancelled_event(ready[0])], timeout=5.0)
    assert order.alive()
    summary = broker._gateway_stop_working_orders()
    assert [key for key, _ in cancels] == ["key-a"] and calls["read"] >= 1
    assert order.status == order.Canceled
    assert summary == {"cancel_requested": 1, "confirmed_terminal": 1, "awaiting_confirmation": 0,
                       "refused": {}, "unresolved_working_orders": 0}
    # Nothing is left to cancel on a second stop.
    assert broker._gateway_stop_working_orders()["cancel_requested"] == 0 and len(cancels) == 1


def test_stop_never_reports_an_unconfirmed_cancel_as_cancelled(ready, inputs, monkeypatch):
    host, broker, strategy, order, calls, api, cancels = _stop_fixture(
        ready, inputs, monkeypatch, [], timeout=0.2)  # the venue does not answer in time
    summary = broker._gateway_stop_working_orders()
    assert len(cancels) == 1 and order.alive() and order.status == order.Accepted
    assert summary == {"cancel_requested": 1, "confirmed_terminal": 0, "awaiting_confirmation": 1,
                       "refused": {}, "unresolved_working_orders": 1}


def test_stop_while_the_gateway_is_unreachable_reports_the_cancel_as_not_requested(ready, inputs, monkeypatch):
    host, broker, strategy, order, calls, api, cancels = _stop_fixture(
        ready, inputs, monkeypatch, [], timeout=0.2)
    state = {"session": "UNAVAILABLE"}
    monkeypatch.setattr(broker, "store", _lost_session_store(api, state))
    summary = broker._gateway_stop_working_orders()
    assert cancels == [] and order.alive()
    assert summary == {"cancel_requested": 0, "confirmed_terminal": 0, "awaiting_confirmation": 0,
                       "refused": {"GATEWAY_STREAM_GATEWAY_UNAVAILABLE": 1},
                       "unresolved_working_orders": 1}


def test_stop_releases_a_reservation_that_was_never_sent(state, ready, inputs, monkeypatch):
    from bt_api_py.gateway_direct_client import GatewayClientResult
    from tests.unit.live_state.test_gateway_pending import observe

    host, api, data, broker, strategy = _bound_submit_fixture(state, ready, inputs, monkeypatch)
    calls = []

    def reserve(route, request, *, timeout_seconds):
        record = observe(host.load_intent(request.idempotency_key))
        host.save_record(request.idempotency_key, record)
        return GatewayClientResult("OBSERVED", record)

    monkeypatch.setattr(api, "reserve_order", reserve)
    monkeypatch.setattr(api, "dispatch_order", lambda *a, **kw: GatewayClientResult("TRANSPORT_NOT_STARTED"))
    monkeypatch.setattr(api, "release_order", _emulated_release(host, calls))
    monkeypatch.setattr(api, "cancel_order", lambda *a, **kw: calls.append(("cancel",)))
    order = _limit_order(strategy, data)
    broker.submit(order)
    assert order.alive()
    summary = broker._gateway_stop_working_orders()
    assert [name for name, *_ in calls] == ["release"]  # withdrawn, never sent to the venue
    assert order.status == order.Canceled
    assert (summary["cancel_requested"], summary["confirmed_terminal"],
            summary["unresolved_working_orders"]) == (1, 1, 0)


def test_broker_stop_reports_gateway_working_orders_and_plain_brokers_are_unchanged(ready, inputs, monkeypatch):
    host, broker, strategy, order, calls, api, cancels = _stop_fixture(
        ready, inputs, monkeypatch, [_cancelled_event(ready[0])], timeout=5.0)
    stopped = []
    monkeypatch.setattr(broker, "_stop_registered_session", lambda: stopped.append(order.status) or "store-result")
    assert broker.stop() == "store-result"
    # The cancel was requested and observed before the session was closed.
    assert stopped == [order.Canceled] and len(cancels) == 1
    assert broker._shutdown_summary["gateway_working_orders"]["confirmed_terminal"] == 1
    _, plain, _ = framework()
    assert plain._gateway_stop_working_orders() is None


def test_idle_strategy_does_not_ask_the_gateway_on_every_step(ready, inputs, monkeypatch):
    # SimNow 2026-11-10: one idle example stepped its broker hundreds of times
    # per second. Each step re-read the durable state several times and asked
    # the Gateway for events: one core busy, the Gateway minutes behind on
    # market data for every strategy.
    import time

    import backtrader.brokers._btapi_gateway_stream as module

    host, broker, strategy, order, calls, api = attach(ready, inputs, monkeypatch)
    binding = broker._gateway_stream_binding
    loads = []
    real_load = host.load_execution_checkpoint
    monkeypatch.setattr(host, "load_execution_checkpoint",
                        lambda: loads.append(1) or real_load())
    monkeypatch.setattr(module, "_IDLE_READ_INTERVAL_SECONDS", 30.0)
    before = time.monotonic()
    for _ in range(200):
        broker.next()
    assert calls["read"] == 1 and broker.gateway_execution_stream_status() == "ACTIVE"
    assert before + 29.0 < binding.next_idle_read <= time.monotonic() + 30.0
    durable_reads = len(loads)
    for _ in range(200):
        broker.next()
    assert len(loads) == durable_reads  # a paused step does not touch the durable state
    binding.next_idle_read = time.monotonic()  # the interval has passed
    for _ in range(200):
        broker.next()
    assert calls["read"] == 2 and len(loads) > durable_reads


def test_a_local_cancel_ends_the_idle_pause(ready, inputs, monkeypatch):
    import backtrader.brokers._btapi_gateway_stream as module

    host, broker, strategy, order, calls, api = attach(ready, inputs, monkeypatch)
    binding = broker._gateway_stream_binding
    monkeypatch.setattr(module, "_IDLE_READ_INTERVAL_SECONDS", 3600.0)
    broker.next()
    assert calls["read"] == 1 and binding.next_idle_read > 0
    # The cancel itself may be refused here (no native identity in this fixture);
    # what matters is that local work lets the very next step run.
    try:
        broker._gateway_cancel_order(order)
    except Exception:
        pass
    assert binding.next_idle_read == 0.0
    broker.next()
    assert calls["read"] == 2


def test_a_local_submit_ends_the_idle_pause(ready, inputs, monkeypatch):
    import backtrader.brokers._btapi_gateway_stream as module

    host, broker, strategy, order, calls, api = attach(ready, inputs, monkeypatch)
    binding = broker._gateway_stream_binding
    monkeypatch.setattr(module, "_IDLE_READ_INTERVAL_SECONDS", 3600.0)
    broker.next()
    assert binding.next_idle_read > 0
    second = bt.BuyOrder(owner=strategy, data=order.data, size=1, price=11, exectype=bt.Order.Limit)
    try:
        broker._gateway_submit_order(second)
    except Exception:
        pass  # refused in this fixture; the pause must be over all the same
    assert binding.next_idle_read == 0.0


def test_waiting_for_an_unreachable_gateway_is_paced(ready, inputs, monkeypatch):
    # After a Gateway restart the example spun at 100 % CPU while it waited.
    from types import SimpleNamespace

    import backtrader.brokers._btapi_gateway_stream as module

    host, broker, strategy, order, calls, api = attach(ready, inputs, monkeypatch)
    binding = broker._gateway_stream_binding
    states = []
    store = SimpleNamespace(_gateway_mode=True, is_connected=False, gateway_api=api,
                            gateway_session_state=lambda: states.append(1) or "UNAVAILABLE")
    monkeypatch.setattr(broker, "store", store)
    monkeypatch.setattr(module, "_IDLE_READ_INTERVAL_SECONDS", 3600.0)
    broker.next()
    assert broker.gateway_execution_stream_status() == "GATEWAY_UNAVAILABLE"
    asked = len(states)
    for _ in range(50):
        broker.next()
    assert len(states) == asked and calls["read"] == 0  # 50 paused steps asked nothing
    assert broker.gateway_execution_stream_status() == "GATEWAY_UNAVAILABLE"
    binding.next_idle_read = 0.0  # the interval has passed
    store.is_connected = True
    broker.next()
    assert calls["read"] == 1 and broker.gateway_execution_stream_status() == "ACTIVE"


def test_reads_are_not_paced_while_events_keep_coming(ready, inputs, monkeypatch):
    import backtrader.brokers._btapi_gateway_stream as module

    monkeypatch.setattr(module, "_IDLE_READ_INTERVAL_SECONDS", 3600.0)
    first = event_for(ready[0], 3, quantity="0.4")
    second = event_for(ready[0], 4, quantity="0.6", fact="c" * 64, trade="d" * 64)
    host, broker, strategy, order, calls, api = attach(ready, inputs, monkeypatch, [first, second])
    broker._gateway_stream_binding.limit = 1  # one event per read: the second needs its own read
    broker.next()
    assert calls["read"] == 1 and abs(order.executed.size - 0.4) < 1e-9
    deliver(broker, strategy)
    for _ in range(6):
        broker.next()
        if broker.notifs:
            deliver(broker, strategy)
    assert abs(order.executed.size - 1.0) < 1e-9 and order.status == order.Completed
    # After the last event one empty read follows, then the strategy is idle.
    reads = calls["read"]
    for _ in range(50):
        broker.next()
    assert calls["read"] in (reads, reads + 1)


def _unbound(session, *, recoverable=True):
    from types import SimpleNamespace

    data, broker, strategy = framework()
    asked = []
    store = SimpleNamespace(_gateway_mode=True, is_connected=False,
        gateway_strategy_config=SimpleNamespace(instruments_by_ref={'rb': INSTRUMENT}),
        gateway_sequence=object(), gateway_session_state=lambda: session[0],
        gateway_session_recoverable=lambda: recoverable)

    def reconnect():
        asked.append(session[0])
        if session[-1] == "gateway back":
            store.is_connected = True
            return True
        return False

    def bind(_strategy, **_kwargs):
        if not store.is_connected:
            raise RuntimeError("GATEWAY_SESSION_UNAVAILABLE")
        asked.append("bind")
        broker._gateway_stream_binding = object()

    store.gateway_reconnect, store.bind_gateway_strategy = reconnect, bind
    broker.store = store
    broker.cerebro = SimpleNamespace(runningstrats=[strategy])
    return data, broker, strategy, store, asked


def test_unbound_broker_waits_and_registers_again_when_the_gateway_restarts():
    # SimNow 2026-11-10 22:49: a 1-minute strategy binds at its first bar. The
    # Gateway was restarted in that first minute; the first bar then ended the
    # strategy with GATEWAY_SESSION_UNAVAILABLE, and before that nothing asked
    # for a new registration (only a bound broker did).
    session = ["UNAVAILABLE"]
    data, broker, strategy, store, asked = _unbound(session)
    broker.next()  # momentarily unhealthy: wait, do not ask for a registration
    assert asked == [] and broker.gateway_execution_stream_status() == "GATEWAY_UNAVAILABLE"
    session[0] = "LOST"
    broker.next()
    broker.next()
    assert asked == ["LOST", "LOST"] and broker.__dict__.get("_gateway_stream_binding") is None
    order = bt.BuyOrder(owner=strategy, data=data, size=1, price=10, exectype=bt.Order.Limit)
    with pytest.raises(RuntimeError, match="FEED_NOT_READY"):
        broker.submit(order)  # refused while waiting, never sent another way
    session.append("gateway back")  # this attempt succeeds
    assert broker._gateway_auto_bind() is strategy
    # (the refused submit asked once more; the real Store spaces attempts by a backoff)
    assert asked == ["LOST", "LOST", "LOST", "LOST", "bind"]
    assert broker.__dict__.get("_gateway_stream_binding") is not None
    assert broker.__dict__.get("_gateway_waiting_for_session") is False


def test_unbound_broker_of_a_stopped_store_ends_with_session_lost():
    data, broker, strategy, store, asked = _unbound(["LOST"], recoverable=False)
    with pytest.raises(RuntimeError, match="GATEWAY_STREAM_SESSION_LOST"):
        broker.next()
    assert asked == []


def _closable_fixture(ready, inputs, monkeypatch, *, today, yesterday, short=("0", "0"), capacities):
    """A bound Gateway-mode broker whose ledger answers the given buckets."""
    from types import SimpleNamespace

    from bt_api_py.gateway_strategy_position import (
        GatewayStrategyPositionObservation, GatewayStrategyPositionResult,
    )

    host, broker, strategy, order, _, api = attach(ready, inputs, monkeypatch)
    broker.store = SimpleNamespace(_gateway_mode=True, is_connected=True, gateway_api=api,
                                   contract_metadata={
        'rb': {'instrument_key': INSTRUMENT.to_dict(), 'exchange_name': 'CTP___FUTURE',
               'quantity_unit': 'lots'}})
    position = {"long": [today, yesterday], "short": list(short)}

    def observation(available=None, reserved=None):
        return GatewayStrategyPositionObservation(
            INSTRUMENT, 'lots', '20261111', Decimal(position["long"][0]),
            Decimal(position["long"][1]), Decimal(position["short"][0]),
            Decimal(position["short"][1]), False, 'owner', 'UNKNOWN',
            None if available is None else Decimal(available),
            None if reserved is None else Decimal(reserved), 1, host._binding, 'registration',
            'epoch')

    asked = []

    def capacity(_route, instrument, *, quantity_unit, side, offset, quantity, position_side,
                 timeout_seconds):
        asked.append((side, offset, quantity, position_side))
        answer = capacities.get(offset)
        if answer is None:
            return GatewayStrategyPositionResult('UNAVAILABLE', code='STRATEGY_LEDGER_UNAVAILABLE')
        if callable(answer):
            answer = answer(position)
        return GatewayStrategyPositionResult('OBSERVED', observation(*answer))

    monkeypatch.setattr(api, 'get_strategy_position',
                        lambda *_a, **_kw: GatewayStrategyPositionResult('OBSERVED', observation()))
    monkeypatch.setattr(api, 'get_strategy_close_capacity', capacity)
    current = [True]
    monkeypatch.setattr(api, 'strategy_position_is_current', lambda *_a, **_kw: current[0])
    return broker, order.data, asked, position, current


def test_gateway_closable_view_comes_from_the_strategy_ledger(ready, inputs, monkeypatch):
    # The 007_ctp Gateway examples plan their closes from broker.get_closable();
    # in Gateway mode it raised closable_view_requires_direct_mode, so no
    # example could close through a Gateway (found 2026-11-10).
    # A venue with separate today/yesterday closes: a plain close is refused.
    broker, data, asked, position, current = _closable_fixture(
        ready, inputs, monkeypatch, today="2", yesterday="1",
        capacities={"close_today": ("1", "1"), "close_yesterday": ("1", "1")})
    view = broker.get_closable(data, "long")
    assert view == {"total": 3.0, "today": 2.0, "yesterday": 1.0, "frozen_close": 1.0,
                    "closable": None, "closable_today": 1.0, "closable_yesterday": 1.0,
                    "venue": INSTRUMENT.venue}
    # Closing a long position is a sell; the asked quantity does not matter.
    assert asked == [("sell", "close", Decimal(1), None), ("sell", "close_today", Decimal(1), None),
                     ("sell", "close_yesterday", Decimal(1), None)]
    with pytest.raises(RuntimeError, match="POSITION_SIDE_REQUIRED"):
        broker.get_closable(data, None)
    # Nothing is served from a position that is not current.
    current[0] = False
    with pytest.raises(RuntimeError, match="STRATEGY_POSITION_UNAVAILABLE"):
        broker.get_closable(data, "long")


def test_gateway_closable_view_of_a_short_side_on_a_plain_close_venue(ready, inputs, monkeypatch):
    broker, data, asked, position, current = _closable_fixture(
        ready, inputs, monkeypatch, today="0", yesterday="0", short=("1", "3"),
        capacities={"close": ("4", "0")})
    view = broker.get_closable(data, "short")
    assert (view["total"], view["today"], view["yesterday"]) == (4.0, 1.0, 3.0)
    assert view["closable"] == 4.0 and view["frozen_close"] == 0.0
    assert view["closable_today"] is None and view["closable_yesterday"] is None
    assert {side for side, *_ in asked} == {"buy"}
    assert broker.get_closable(data, "long")["total"] == 0.0


def test_gateway_closable_is_unknown_when_the_position_moved_between_reads(ready, inputs, monkeypatch):
    def moved(position):
        position["long"][0] = "1"  # a fill landed after the first read
        return ("1", "0")

    broker, data, asked, position, current = _closable_fixture(
        ready, inputs, monkeypatch, today="2", yesterday="0",
        capacities={"close_today": moved, "close_yesterday": ("0", "0")})
    view = broker.get_closable(data, "long")
    assert view["today"] == 2.0 and view["closable_today"] is None
    assert view["closable_yesterday"] is None and view["closable"] is None


def test_gateway_closable_without_a_capacity_figure_is_unknown(ready, inputs, monkeypatch):
    broker, data, asked, position, current = _closable_fixture(
        ready, inputs, monkeypatch, today="2", yesterday="0",
        capacities={"close_today": (None, None), "close_yesterday": ("0", "0")})
    view = broker.get_closable(data, "long")
    assert view["closable_today"] is None and view["closable_yesterday"] == 0.0


def test_closable_view_outside_gateway_mode_is_still_the_direct_one(ready, inputs, monkeypatch):
    from types import SimpleNamespace

    host, broker, strategy, order, _, api = attach(ready, inputs, monkeypatch)
    broker.store = SimpleNamespace(_gateway_mode=False)
    with pytest.raises(Exception, match="closable_view_requires_direct_mode"):
        broker.get_closable(order.data, "long")
