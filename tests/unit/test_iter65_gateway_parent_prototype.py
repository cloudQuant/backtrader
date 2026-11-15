"""65.01 offline Gateway stream prototype; all SDK/Gateway facts are synthetic.

The existing stream fixture supplies one registered request and one native
command identity. It cannot issue or authenticate parent/child projections.
The tests exercise real BT, SDK DTO/client and durable BT checkpoint code, with
in-memory RPC substitutes and temporary files. They make no provider or account
claims and do not contact the configured placeholder endpoint.
"""

import sys
import datetime as dt
from dataclasses import replace
from pathlib import Path

import pytest
import backtrader as bt

from bt_api_base.direct_write_protocol import DirectExecutionEventKind, DirectOrderStatus
from bt_api_base.gateway_execution_stream_protocol import (
    GatewayExecutionObservation, GatewayExecutionStreamProgress,
)
from bt_api_py.gateway_execution_stream_client import (
    GatewayExecutionReadContext, GatewayExecutionStreamClientResult,
)
from bt_api_py.gateway_execution_time import GatewayExecutionTimePolicy
from backtrader.live_state.gateway_pending import GatewayPendingHost

from tests.unit.brokers.test_iter63_gateway_stream_consumer import (
    INSTRUMENT, api_for, attach, deliver, event_for, framework,
)
from tests.unit.live_state.conftest import state as state, strategy_dir as strategy_dir
from tests.unit.live_state.test_gateway_execution_checkpoint import page, ready as ready
from tests.unit.live_state.test_gateway_pending import inputs as inputs

WORKSPACE = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module", autouse=True)
def isolated_sources():
    yield
    wrong = {}
    for name, module in tuple(sys.modules.items()):
        if name == "backtrader" or name.startswith(("backtrader.", "bt_api_py", "bt_api_")):
            source = getattr(module, "__file__", None)
            if source and not Path(source).resolve().is_relative_to(WORKSPACE):
                wrong[name] = source
    assert not wrong, f"non-worktree modules: {wrong}"


@pytest.fixture(autouse=True)
def no_idle_delay(monkeypatch):
    import backtrader.brokers._btapi_gateway_stream as stream_module
    monkeypatch.setattr(stream_module, "_IDLE_READ_INTERVAL_SECONDS", 0.0)


def test_folded_single_command_cross_day_replay_and_restart(state, ready, inputs, monkeypatch):
    """Candidate folded facts are already bound to one command; no child authority is asserted."""
    first = event_for(ready[0], 3, quantity="0.4", fact="a" * 64, trade="b" * 64)
    duplicate = replace(first, sequence=6, fact_digest="f" * 64)
    second = event_for(ready[0], 8, quantity="0.6", fact="9" * 64, trade="c" * 64)
    second = replace(second, observation=replace(second.observation,
        trading_day="20261109", trade_date="20261109"))
    events = [first, duplicate, second]
    host, broker, strategy, order, calls, api = attach(ready, inputs, monkeypatch, events)
    broker.next()
    assert order.executed.size == 0.4 and broker.positions["rb"].size == 0.4
    deliver(broker, strategy)
    broker.next()  # acknowledge first; process duplicate
    assert order.executed.size == 0.4
    deliver(broker, strategy)
    assert host.load_execution_checkpoint().applied_sequence == 6

    # Reopen the actual durable checkpoint with a new BT broker and strategy.
    reopened = GatewayPendingHost(state.strategy_dir, state.strategy_uuid, host._binding)
    assert reopened.load_execution_checkpoint() == host.load_execution_checkpoint()
    data2, broker2, strategy2 = framework()
    # A new SDK session is bound to the reopened host, with both RPC operations
    # stubbed just as in attach(): no network is used.
    api2 = api_for(reopened, inputs[1])
    stream2 = api2.gateway_execution_stream("CTP___FUTURE")
    def read(after, epoch, limit, *, timeout_seconds):
        selected = [event for event in events if event.sequence > after][:limit]
        return GatewayExecutionStreamClientResult("OBSERVED", page=page(ready[1], ready[2], selected),
            request_context=GatewayExecutionReadContext(ready[1], ready[2], after, epoch, limit))
    def ack(sequence, expected_epoch, *, timeout_seconds):
        calls["ack"].append(sequence)
        return GatewayExecutionStreamClientResult("OBSERVED", progress=GatewayExecutionStreamProgress(
            ready[1], ready[2], expected_epoch, 10, sequence))
    monkeypatch.setattr(stream2, "read_after", read)
    monkeypatch.setattr(stream2, "ack", ack)
    broker2.bind_gateway_execution_stream(strategy2, api=api2, host=reopened,
        data_by_ref={"rb": data2}, orders_by_key={}, instrument_by_ref={"rb": INSTRUMENT},
        time_policy=GatewayExecutionTimePolicy("CTP___FUTURE", "UTC"))
    (restored,) = broker2.orders.values()
    assert restored.executed.size == 0.4 and broker2.positions["rb"].size == 0.4
    broker2.next()
    assert restored.executed.size == 1 and broker2.positions["rb"].size == 1
    assert restored.status == restored.Completed
    deliver(broker2, strategy2)
    broker2.next()
    assert reopened.load_execution_checkpoint().acknowledged_sequence == 8
    assert calls["ack"] == [3, 6, 8]
    assert restored.executed.size == 1


def test_unregistered_child_request_is_rejected_atomically(ready, inputs, monkeypatch):
    event = replace(event_for(ready[0]), request_key="synthetic-child-request")
    host, broker, strategy, order, calls, _ = attach(ready, inputs, monkeypatch, [event])
    before = host.load_execution_checkpoint()
    with pytest.raises(ValueError, match="EXECUTION_EVENT_ORPHAN"):
        broker.next()
    assert host.load_execution_checkpoint() == before
    assert order.executed.size == 0 and calls["ack"] == []


def test_child_identity_cannot_be_claimed_by_parent_command(ready, inputs, monkeypatch):
    event = event_for(ready[0])
    # Distinct synthetic child identity has no original command binding or
    # valid attribution proof. No identity proof is fabricated for the test.
    obs = replace(event.observation, identity_key_digests=("d" * 64, "f" * 64),
                  binding_key_digests=("f" * 64,))
    event = replace(event, observation=obs)
    host, broker, strategy, order, calls, _ = attach(ready, inputs, monkeypatch, [event])
    before = host.load_execution_checkpoint()
    with pytest.raises(ValueError, match="EXECUTION_EVENT_BINDING_MISMATCH"):
        broker.next()
    assert host.load_execution_checkpoint() == before
    assert order.executed.size == 0 and calls["ack"] == []


def test_child_order_quantity_cannot_stand_in_for_parent_quantity(ready, inputs, monkeypatch):
    event = event_for(ready[0])
    event = replace(event, observation=replace(event.observation,
        order_quantity="0.4", filled_quantity="0.4", remaining_quantity="0"))
    host, broker, strategy, order, calls, _ = attach(ready, inputs, monkeypatch, [event])
    with pytest.raises(RuntimeError, match="GATEWAY_STREAM_EVENT_BINDING"):
        broker.next()
    checkpoint = host.load_execution_checkpoint()
    assert checkpoint.applied_sequence == 0 and order.executed.size == 0 and calls["ack"] == []


def test_late_partial_trade_after_cancel_is_observable(ready, inputs, monkeypatch):
    trade = event_for(ready[0], 8, quantity="0.4", fact="f" * 64)
    source = event_for(ready[0])
    original = source.observation
    cancelled = GatewayExecutionObservation(
        account_scope=original.account_scope, route=original.route,
        instrument=original.instrument, trading_day=original.trading_day,
        kind=DirectExecutionEventKind.ORDER, native_identity_digest=original.native_identity_digest,
        identity_key_digests=original.identity_key_digests,
        binding_key_digests=original.binding_key_digests,
        venue_key_digest=original.venue_key_digest, status=DirectOrderStatus.CANCELLED,
        side="buy", order_quantity="1", filled_quantity="0", remaining_quantity="1")
    host, broker, strategy, order, calls, _ = attach(
        ready, inputs, monkeypatch, [replace(source, observation=cancelled), trade])
    broker.next()
    assert order.status == order.Canceled and order.executed.size == 0
    deliver(broker, strategy)
    broker.next()
    assert order.executed.size == 0.4 and broker.positions["rb"].size == 0.4
    assert order.status == order.Canceled  # the unfilled remainder is not revived
    deliver(broker, strategy)
    broker.next()
    assert calls["ack"] == [3, 8]


def test_cancel_with_reported_fill_waits_for_late_trade(ready, inputs, monkeypatch):
    trade = event_for(ready[0], 8, quantity="0.4", fact="f" * 64)
    source = event_for(ready[0])
    original = source.observation
    cancelled = GatewayExecutionObservation(
        account_scope=original.account_scope, route=original.route,
        instrument=original.instrument, trading_day=original.trading_day,
        kind=DirectExecutionEventKind.ORDER, native_identity_digest=original.native_identity_digest,
        identity_key_digests=original.identity_key_digests,
        binding_key_digests=original.binding_key_digests,
        venue_key_digest=original.venue_key_digest, status=DirectOrderStatus.CANCELLED,
        side="buy", order_quantity="1", filled_quantity="0.4", remaining_quantity="0.6")
    host, broker, strategy, order, calls, _ = attach(
        ready, inputs, monkeypatch, [replace(source, observation=cancelled), trade])
    broker.next()
    assert order.alive() and order.executed.size == 0
    assert order.info["execution_pending_trades"] is True
    deliver(broker, strategy)
    broker.next()
    assert order.status == order.Canceled and order.executed.size == 0.4
    assert broker.positions["rb"].size == 0.4
    deliver(broker, strategy)
    broker.next()
    assert calls["ack"] == [3, 8]


def test_older_trade_after_newer_fill_cancel_and_checkpoint_restart(state, ready, inputs, monkeypatch):
    """Single synthetic command only: this does not prove a cross-day parent or provider behavior."""
    newer = event_for(ready[0], 3, quantity="0.4", fact="a" * 64, trade="b" * 64)
    newer = replace(newer, observation=replace(newer.observation,
        trading_day="20261109", trade_date="20261109"))
    original = newer.observation
    cancel_observation = GatewayExecutionObservation(
        account_scope=original.account_scope, route=original.route,
        instrument=original.instrument, trading_day=original.trading_day,
        kind=DirectExecutionEventKind.ORDER, native_identity_digest=original.native_identity_digest,
        identity_key_digests=original.identity_key_digests,
        binding_key_digests=original.binding_key_digests,
        venue_key_digest=original.venue_key_digest, status=DirectOrderStatus.CANCELLED,
        side="buy", order_quantity="1", filled_quantity="0.7", remaining_quantity="0.3")
    cancelled = replace(newer, sequence=6, fact_digest="f" * 64, observation=cancel_observation)
    older = event_for(ready[0], 8, quantity="0.3", fact="9" * 64, trade="c" * 64)
    duplicate = replace(older, sequence=9, fact_digest="8" * 64)
    events = [newer, cancelled]
    host, broker, strategy, order, calls, _ = attach(ready, inputs, monkeypatch, events)
    broker.next()
    assert order.executed.size == 0.4 and broker.positions["rb"].size == 0.4
    deliver(broker, strategy)
    broker.next()
    assert order.info["execution_pending_trades"] is True
    assert order.executed.size == 0.4 and order.status != order.Canceled
    deliver(broker, strategy)
    broker.next()
    checkpoint = host.load_execution_checkpoint()
    assert (checkpoint.applied_sequence, checkpoint.acknowledged_sequence) == (6, 6)

    reopened = GatewayPendingHost(state.strategy_dir, state.strategy_uuid, host._binding)
    data2, broker2, strategy2 = framework()
    api2 = api_for(reopened, inputs[1])
    stream2 = api2.gateway_execution_stream("CTP___FUTURE")
    events.extend([older, duplicate])
    def read(after, epoch, limit, *, timeout_seconds):
        selected = [event for event in events if event.sequence > after][:limit]
        return GatewayExecutionStreamClientResult("OBSERVED", page=page(ready[1], ready[2], selected),
            request_context=GatewayExecutionReadContext(ready[1], ready[2], after, epoch, limit))
    def ack(sequence, expected_epoch, *, timeout_seconds):
        calls["ack"].append(sequence)
        return GatewayExecutionStreamClientResult("OBSERVED", progress=GatewayExecutionStreamProgress(
            ready[1], ready[2], expected_epoch, 10, sequence))
    monkeypatch.setattr(stream2, "read_after", read)
    monkeypatch.setattr(stream2, "ack", ack)
    broker2.bind_gateway_execution_stream(strategy2, api=api2, host=reopened,
        data_by_ref={"rb": data2}, orders_by_key={}, instrument_by_ref={"rb": INSTRUMENT},
        time_policy=GatewayExecutionTimePolicy("CTP___FUTURE", "UTC"))
    (restored,) = broker2.orders.values()
    assert restored.executed.size == 0.4 and broker2.positions["rb"].size == 0.4
    broker2.next()
    assert restored.executed.size == pytest.approx(0.7)
    assert broker2.positions["rb"].size == pytest.approx(0.7)
    assert restored.status == restored.Canceled
    # The late fill's source time is kept per execution bit, but cancel()
    # overwrites the cumulative executed.dt with the fixture's data clock.
    assert [bt.num2date(bit.dt).isoformat() for bit in restored.executed.exbits] == [
        "2026-11-09T09:00:00", "2026-11-07T09:00:00"]
    assert bt.num2date(restored.executed.dt).isoformat() == "2026-11-03T09:00:00"
    facts = restored.info["gateway_execution_time_facts"]
    assert facts[newer.observation.trade_key_digest]["trade_date"] == "20261109"
    assert facts[older.observation.trade_key_digest]["trade_date"] == "20261107"
    deliver(broker2, strategy2)
    # The trade was already open before restart: BT sends an order notification
    # for this partial increase, not a second opening trade notification.
    assert [event[0] for event in strategy2.events] == ["order"]
    restored_trade = next(iter(next(iter(strategy2._trades.values())).values()))[0]
    assert restored_trade.size == pytest.approx(0.7)
    broker2.next()
    assert restored.executed.size == pytest.approx(0.7)
    deliver(broker2, strategy2)
    assert [event[0] for event in strategy2.events] == ["order", "order"]
    assert restored_trade.size == pytest.approx(0.7)
    assert [event[3] for event in strategy2.events] == pytest.approx([0.7, 0.7])
    broker2.next()
    assert calls["ack"] == [3, 6, 8, 9]
    checkpoint = reopened.load_execution_checkpoint()
    assert (checkpoint.applied_sequence, checkpoint.acknowledged_sequence) == (9, 9)
    assert restored.executed.size == pytest.approx(0.7)


def test_reused_trade_digest_on_another_day_is_rejected(ready, inputs, monkeypatch):
    """Synthetic digest collision, not a statement about a venue's ID scope."""
    first = event_for(ready[0], 3, quantity="0.4", fact="a" * 64, trade="b" * 64)
    second = replace(first, sequence=8, fact_digest="f" * 64,
        observation=replace(first.observation, trading_day="20261109", trade_date="20261109"))
    events = [first]
    host, broker, strategy, order, calls, _ = attach(ready, inputs, monkeypatch, events)
    broker.next()
    deliver(broker, strategy)
    events.append(second)
    with pytest.raises(ValueError, match="EXECUTION_TRADE_CONFLICT"):
        broker.next()
    assert host.load_execution_checkpoint().stored_sequence == 3
    assert order.executed.size == 0.4 and broker.positions["rb"].size == 0.4
    assert calls["ack"] == [3]


@pytest.fixture
def gateway_submit_probe(state, ready, inputs, monkeypatch):
    _, binding, _ = ready
    host = GatewayPendingHost.upgrade_for_order_state(state.strategy_dir, state.strategy_uuid, binding)
    state.sequence.allocate()
    api = api_for(host, inputs[1])
    data, broker, strategy = framework()
    broker.bind_gateway_execution_stream(strategy, api=api, host=host, data_by_ref={"rb": data},
        orders_by_key={}, instrument_by_ref={"rb": INSTRUMENT},
        time_policy=GatewayExecutionTimePolicy("CTP___FUTURE", "UTC"), sequence=state.sequence)
    calls = []
    get_stream = api.gateway_execution_stream
    def observe_stream(route):
        calls.append(("stream_getter", route))
        return get_stream(route)
    monkeypatch.setattr(api, "gateway_execution_stream", observe_stream)
    monkeypatch.setattr(api, "reserve_order", lambda *args, **kwargs: calls.append(("reserve",)))
    monkeypatch.setattr(api, "dispatch_order", lambda *args, **kwargs: calls.append(("dispatch",)))
    return state, host, data, broker, strategy, calls


@pytest.mark.parametrize("valid", [dt.datetime(2026, 11, 9, 14, 0), bt.Order.DAY], ids=["datetime", "day"])
def test_gateway_submit_rejects_explicit_expiry_before_reserve(gateway_submit_probe, valid):
    state, host, data, broker, strategy, calls = gateway_submit_probe
    before = state.sequence.local_seq
    order = bt.BuyOrder(owner=strategy, data=data, size=1, price=10, exectype=bt.Order.Limit,
                        valid=valid)
    assert type(order.valid) is float
    assert order.valid is not None
    if isinstance(valid, dt.datetime):
        assert order.valid == bt.date2num(valid)
    order.addinfo(offset="open", quantity_unit="lots", time_in_force="GFD")
    with pytest.raises(RuntimeError, match="GATEWAY_STREAM_ORDER_UNSUPPORTED"):
        broker.submit(order)
    assert state.sequence.local_seq == before and order.status == order.Created
    assert host.iter_order_snapshots() == {}
    assert calls == [("stream_getter", "CTP___FUTURE")]


@pytest.mark.parametrize("order_type", [bt.BuyOrder, bt.SellOrder], ids=["buy", "sell"])
@pytest.mark.parametrize("valid", [None, dt.datetime(2026, 11, 9, 14, 0)], ids=["no_valid", "valid"])
def test_gateway_market_rejected_before_reserve(gateway_submit_probe, order_type, valid):
    """Current Gateway Broker guard, not a claim about other paths or Execution routing."""
    state, host, data, broker, strategy, calls = gateway_submit_probe
    before = state.sequence.local_seq
    order = order_type(owner=strategy, data=data, size=1, exectype=bt.Order.Market, valid=valid)
    assert (order.valid is None) == (valid is None)
    order.addinfo(offset="open", quantity_unit="lots", time_in_force="GFD")
    with pytest.raises(RuntimeError, match="GATEWAY_STREAM_ORDER_UNSUPPORTED"):
        broker.submit(order)
    assert state.sequence.local_seq == before and order.status == order.Created
    assert host.iter_order_snapshots() == {}
    assert calls == [("stream_getter", "CTP___FUTURE")]
