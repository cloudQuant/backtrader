"""R25 real Backtrader object snapshots in the R24 local checkpoint.

This is a caller-driven synthetic integration, not Gateway Broker wiring,
notification atomicity, provider provenance, or a real account test.
"""

from __future__ import annotations

import itertools
import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest

import backtrader as bt
from backtrader.live_state.gateway_pending import GatewayPendingHost
from backtrader.metabase import OwnerContext
from backtrader.position import trade_key_from_order
from bt_api_base.gateway_direct_protocol import GatewayCommandBinding
from bt_api_base.gateway_execution_stream_protocol import gateway_execution_consumer_ref
from tests.unit.live_state.test_gateway_execution_checkpoint import make_event, page
from tests.unit.live_state.test_gateway_pending import inputs as inputs
from tests.unit.live_state.test_gateway_pending_cancel import prepare, upgrade


class _Strategy(bt.Strategy):
    pass


def _framework():
    frame = pd.DataFrame(
        {"open": [10.0], "high": [11.0], "low": [9.0], "close": [10.0], "volume": [1.0]},
        index=pd.to_datetime(["2026-11-03 09:00"]),
    )
    data = bt.feeds.PandasData(dataname=frame, name="rb")
    data._start()
    assert data.load()
    broker = bt.brokers.BackBroker()
    cerebro = bt.Cerebro()
    cerebro.setbroker(broker)
    cerebro.stcount = itertools.count()
    cerebro.datas = [data]
    cerebro.datasbyname = {"rb": data}
    with OwnerContext.set_owner(cerebro):
        owner = _Strategy.__new__(_Strategy)
    owner.datas = [data]
    owner.data = data
    owner._tradehistoryon = True
    return data, owner, broker


def _order(owner, broker, data, *, size, tradeid):
    order = bt.BuyOrder(
        owner=owner,
        data=data,
        size=size,
        price=10.0,
        exectype=bt.Order.Limit,
        tradeid=tradeid,
        simulated=False,
    )
    order.addcomminfo(broker.getcommissioninfo(data))
    order.submit(broker)
    order.accept(broker)
    return order


def _fill(owner, order, position, quantity, price):
    # The bar time and fee are explicit synthetic framework inputs; neither is
    # inferred from a Gateway event's limited execution-time or fee fields.
    position.update(quantity, price)
    order.execute(
        order.data.datetime[0],
        quantity,
        price,
        0,
        0.0,
        0.0,
        quantity,
        quantity * price,
        0.1,
        0.0,
        0.0,
        position.size,
        position.price,
    )
    notification = order.clone()
    owner._addnotification(notification, quicknotify=False)
    return notification


def _real_state():
    data, owner, broker = _framework()
    position = bt.Position()
    partial = _order(owner, broker, data, size=3, tradeid=101)
    terminal = _order(owner, broker, data, size=2, tradeid=102)
    partial_notification = _fill(owner, partial, position, 1, 10.0)
    terminal_notification = _fill(owner, terminal, position, 1, 11.0)
    terminal.cancel()
    partial_trade = owner._trades[data][trade_key_from_order(partial)][-1]
    terminal_trade = owner._trades[data][trade_key_from_order(terminal)][-1]
    assert isinstance(partial_trade, bt.Trade) and isinstance(terminal_trade, bt.Trade)
    assert partial.status == bt.Order.Partial and terminal.status == bt.Order.Canceled
    assert partial_trade.history[0].event.order is partial_notification
    assert terminal_trade.history[0].event.order is terminal_notification
    assert partial.ref == partial_notification.ref and partial is not partial_notification
    assert terminal.ref == terminal_notification.ref and terminal is not terminal_notification
    assert (position.size, partial_trade.size, terminal_trade.size) == (2, 1, 1)
    return (
        data,
        owner,
        broker,
        position,
        partial,
        terminal,
        partial_notification,
        terminal_notification,
        partial_trade,
        terminal_trade,
    )


def _checkpoint(state, inputs):
    binding, _, _ = inputs
    prepare(state, inputs, ("key-a", "key-b"))
    upgrade(state, binding)
    consumer = gateway_execution_consumer_ref(
        principal_ref="principal-a",
        actor_ref="strategy-a",
        execution_domain_ref="paper:demo",
        account_scope="account-a",
        strategy_scope="strategy-a",
    )
    host = GatewayPendingHost.upgrade_for_execution(
        state.strategy_dir, state.strategy_uuid, binding, consumer_ref=consumer
    )
    first = make_event(host, 3)
    candidate = make_event(host, 8, fact="f" * 64, trade="a" * 64)
    terminal_record = host.load_record("key-b")
    terminal_key = terminal_record.strong_identity_key_digests[0]
    observation = replace(
        candidate.observation,
        identity_key_digests=tuple(sorted({terminal_key, "d" * 64})),
        binding_key_digests=(terminal_key,),
    )
    second = replace(
        candidate,
        request_key="key-b",
        reservation_id=terminal_record.reservation_id,
        command_digest=terminal_record.digest,
        observation=observation,
    )
    events = (first, second)
    initial = host.load_execution_checkpoint()
    stored = host.ingest_execution_page(
        page(binding, consumer, events, offered=8),
        expected_revision=initial.revision,
        after_sequence=0,
    )
    return binding, host, stored, events


def _fresh_process_projection(payload):
    """Reopen the real checkpoint in a clean interpreter and apply one new fill."""
    from backtrader.brokers._btapi_gateway_projection import restore_framework_state

    binding = GatewayCommandBinding(**payload["binding"])
    host = GatewayPendingHost(payload["strategy_dir"], payload["strategy_uuid"], binding)
    checkpoint = host.load_execution_checkpoint()
    assert checkpoint.applied_sequence == 3
    assert [item.sequence for item in host.read_execution_events()] == [8]
    data, owner, broker = _framework()
    sentinel_order = _order(owner, broker, data, size=1, tradeid=901)
    sentinel_trade = bt.Trade(data=data, tradeid=901)
    restored = restore_framework_state(
        checkpoint.projection,
        data_by_ref={"rb": data},
        owner=owner,
        broker=broker,
        commission_for_data=broker.getcommissioninfo,
    )
    a, a_notice = restored.orders["key-a"], restored.orders["notice-a"]
    b, b_notice = restored.orders["key-b"], restored.orders["notice-b"]
    ta, tb = restored.trades["trade-a"], restored.trades["trade-b"]
    assert a is not a_notice and b is not b_notice
    assert a.ref == a_notice.ref and b.ref == b_notice.ref
    assert restored.order_refs[payload["order_refs"]["key-a"]] == a.ref
    assert restored.order_refs[payload["order_refs"]["key-b"]] == b.ref
    assert restored.trade_refs[payload["trade_refs"]["trade-a"]] == ta.ref
    assert restored.trade_refs[payload["trade_refs"]["trade-b"]] == tb.ref
    assert ta.history[0].event.order is a_notice and tb.history[0].event.order is b_notice
    assert b.status == bt.Order.Canceled
    assert (restored.positions["rb"].size, ta.size, tb.size, b.executed.size) == (2, 1, 1, 1)
    next_order = _order(owner, broker, data, size=1, tradeid=902)
    next_trade = bt.Trade(data=data, tradeid=902)
    assert next_order.ref > max(sentinel_order.ref, *(o.ref for o in restored.orders.values()))
    assert next_trade.ref > max(sentinel_trade.ref, *(t.ref for t in restored.trades.values()))
    owner._trades[data][trade_key_from_order(a)].append(ta)
    owner._trades[data][trade_key_from_order(b)].append(tb)
    broker.positions[data] = restored.positions["rb"]
    notice = _fill(owner, b, restored.positions["rb"], 1, 12.0)
    assert len(notice.executed.getpending()) == 1 and notice.executed.getpending()[0].price == 12.0
    assert tb.history[0].event.order is b_notice and tb.history[1].event.order is notice
    assert b.status == bt.Order.Completed and len(b.executed.exbits) == 2
    return {
        "pid": os.getpid(),
        "checkpoint_applied": checkpoint.applied_sequence,
        "remaining_sequence": 8,
        "position": restored.positions["rb"].size,
        "position_price": restored.positions["rb"].price,
        "trade_size": tb.size,
        "trade_price": tb.price,
        "trade_commission": tb.commission,
        "order_exbits": len(b.executed.exbits),
        "trade_history": len(tb.history),
        "original_and_clone_distinct": b is not b_notice,
        "original_and_clone_ref_equal": b.ref == b_notice.ref,
        "counters_advanced": True,
    }


@pytest.mark.parametrize("failure_window", ["before_replace", "after_replace"])
def test_real_framework_snapshot_atomic_recovery_and_late_fill(
    state, inputs, monkeypatch, failure_window
):
    from backtrader.brokers._btapi_gateway_projection import (
        capture_framework_state,
        restore_framework_state,
    )
    import backtrader.live_state.pending as pending_module

    binding, host, stored, events = _checkpoint(state, inputs)
    (
        data,
        owner,
        broker,
        position,
        partial,
        terminal,
        partial_notice,
        terminal_notice,
        trade_a,
        trade_b,
    ) = _real_state()
    orders = {
        "key-a": partial,
        "notice-a": partial_notice,
        "key-b": terminal,
        "notice-b": terminal_notice,
    }
    trades = {"trade-a": trade_a, "trade-b": trade_b}
    original_order_refs = {key: value.ref for key, value in orders.items()}
    original_trade_refs = {key: value.ref for key, value in trades.items()}
    before_windows = {
        key: (value.executed.p1, value.executed.p2, len(value.executed.exbits))
        for key, value in orders.items()
    }
    before_history = {
        key: tuple(id(item) for item in value.history) for key, value in trades.items()
    }
    snapshot = capture_framework_state(
        orders=orders,
        positions={"rb": position},
        trades=trades,
        data_by_ref={"rb": data},
        owner=owner,
        broker=broker,
    )
    assert json.loads(json.dumps(snapshot, allow_nan=False)) == snapshot
    assert snapshot["schema_version"] == 1
    assert before_windows == {
        key: (value.executed.p1, value.executed.p2, len(value.executed.exbits))
        for key, value in orders.items()
    }
    assert before_history == {
        key: tuple(id(item) for item in value.history) for key, value in trades.items()
    }
    before = Path(state.pending.path).read_bytes()
    atomic_write = pending_module.atomic_write_json
    with monkeypatch.context() as patch:

        def fail_at_boundary(*args, **kwargs):
            if failure_window == "after_replace":
                atomic_write(*args, **kwargs)
            raise OSError("synthetic checkpoint boundary")

        patch.setattr(pending_module, "atomic_write_json", fail_at_boundary)
        with pytest.raises(OSError):
            host.commit_execution_projection(
                3, snapshot, expected_revision=stored.revision, expected_applied_sequence=0
            )
    reopened = GatewayPendingHost(state.strategy_dir, state.strategy_uuid, binding)
    recovered = reopened.load_execution_checkpoint()
    if failure_window == "before_replace":
        assert Path(state.pending.path).read_bytes() == before
        assert recovered.applied_sequence == 0 and recovered.projection is None
        assert reopened.read_execution_events() == events
        recovered = reopened.commit_execution_projection(
            3, snapshot, expected_revision=recovered.revision, expected_applied_sequence=0
        )
    else:
        assert recovered.applied_sequence == 3 and recovered.projection == snapshot
    assert reopened.read_execution_events() == (events[1],)
    assert recovered.acknowledged_sequence == 0
    process_payload = {
        "strategy_dir": str(state.strategy_dir),
        "strategy_uuid": state.strategy_uuid,
        "binding": {
            name: getattr(binding, name)
            for name in ("journal_id", "account_scope", "strategy_scope", "principal")
        },
        "order_refs": original_order_refs,
        "trade_refs": original_trade_refs,
    }
    script = (
        "import json, runpy, sys; "
        "module = runpy.run_path(sys.argv[1]); "
        "result = module['_fresh_process_projection'](json.loads(sys.argv[2])); "
        "print(json.dumps(result, allow_nan=False, sort_keys=True))"
    )
    child = subprocess.run(
        [sys.executable, "-c", script, str(Path(__file__).resolve()), json.dumps(process_payload)],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert child.returncode == 0, (child.stdout, child.stderr)
    child_result = json.loads(child.stdout.strip())
    assert child_result["pid"] != os.getpid()
    assert child_result["checkpoint_applied"] == 3 and child_result["remaining_sequence"] == 8
    assert (
        child_result["position"],
        child_result["trade_size"],
        child_result["order_exbits"],
        child_result["trade_history"],
    ) == (3, 2, 2, 2)
    assert child_result["position_price"] == pytest.approx(11.0)
    assert child_result["trade_price"] == pytest.approx(11.5)
    assert child_result["trade_commission"] == pytest.approx(0.2)
    assert (
        child_result["original_and_clone_distinct"] and child_result["original_and_clone_ref_equal"]
    )
    assert child_result["counters_advanced"]
    # The child applied the fill only to its process-local objects.
    assert reopened.read_execution_events() == (events[1],)

    new_data, new_owner, new_broker = _framework()
    restored = restore_framework_state(
        recovered.projection,
        data_by_ref={"rb": new_data},
        owner=new_owner,
        broker=new_broker,
        commission_for_data=new_broker.getcommissioninfo,
    )
    assert all(isinstance(order, bt.Order) for order in restored.orders.values())
    assert all(isinstance(trade, bt.Trade) for trade in restored.trades.values())
    assert isinstance(restored.positions["rb"], bt.Position)
    a, a_notice = restored.orders["key-a"], restored.orders["notice-a"]
    b, b_notice = restored.orders["key-b"], restored.orders["notice-b"]
    ta, tb = restored.trades["trade-a"], restored.trades["trade-b"]
    assert a is not a_notice and b is not b_notice
    assert a.executed.exbits is a_notice.executed.exbits
    assert b.executed.exbits is b_notice.executed.exbits
    assert a.ref == a_notice.ref != original_order_refs["key-a"]
    assert b.ref == b_notice.ref != original_order_refs["key-b"]
    assert ta.ref != original_trade_refs["trade-a"] and tb.ref != original_trade_refs["trade-b"]
    assert restored.order_refs[original_order_refs["key-a"]] == a.ref
    assert restored.order_refs[original_order_refs["key-b"]] == b.ref
    assert restored.trade_refs[original_trade_refs["trade-a"]] == ta.ref
    assert restored.trade_refs[original_trade_refs["trade-b"]] == tb.ref
    assert ta.history[0].event.order is a_notice and tb.history[0].event.order is b_notice
    assert a.status == bt.Order.Partial and b.status == bt.Order.Canceled
    assert a_notice.status == bt.Order.Partial and b_notice.status == bt.Order.Partial
    assert (restored.positions["rb"].size, ta.size, tb.size) == (2, 1, 1)
    assert restored.positions["rb"].price == pytest.approx(10.5)
    assert (ta.price, tb.price) == pytest.approx((10.0, 11.0))
    assert (ta.commission, tb.commission) == pytest.approx((0.1, 0.1))
    assert (a.executed.size, b.executed.size) == (1, 1)
    assert len(a.executed.exbits) == len(b.executed.exbits) == 1
    assert (a.executed.p1, a.executed.p2) == (partial.executed.p1, partial.executed.p2)
    assert (a_notice.executed.p1, a_notice.executed.p2) == (
        partial_notice.executed.p1,
        partial_notice.executed.p2,
    )
    assert (b_notice.executed.p1, b_notice.executed.p2) == (
        terminal_notice.executed.p1,
        terminal_notice.executed.p2,
    )
    assert a.data is b.data is new_data and a.owner is b.owner is new_owner
    assert a.broker is b.broker is new_broker

    # Explicit installation is caller work: restore does not attach these to
    # Strategy or Broker.  Only the remaining event is applied after restart.
    new_owner._trades[new_data][trade_key_from_order(a)].append(ta)
    new_owner._trades[new_data][trade_key_from_order(b)].append(tb)
    new_broker.positions[new_data] = restored.positions["rb"]
    remaining = reopened.read_execution_events()
    assert [event.sequence for event in remaining] == [8]
    assert remaining[0].request_key == "key-b"
    assert (remaining[0].observation.trade_quantity, remaining[0].observation.trade_price) == (
        "1",
        "12",
    )
    notice = _fill(new_owner, b, restored.positions["rb"], 1, 12.0)
    assert len(notice.executed.getpending()) == 1
    assert notice.executed.getpending()[0].price == 12.0
    assert len(b_notice.executed.getpending()) == 1
    assert b_notice.executed.getpending()[0].price == 11.0
    assert b.status == bt.Order.Completed and b.executed.size == 2
    assert len(b.executed.exbits) == 2 and len(tb.history) == 2
    assert tb.history[0].event.order is b_notice and tb.history[1].event.order is notice
    assert (restored.positions["rb"].size, ta.size, tb.size) == (3, 1, 2)
    assert restored.positions["rb"].price == pytest.approx(11.0)
    assert tb.price == pytest.approx(11.5)
    assert tb.commission == pytest.approx(0.2)

    # Persist the new fill and restart a second time. The checkpoint, rather
    # than an in-memory receipt set, prevents replaying either consumed fact.
    orders_after = dict(restored.orders)
    orders_after["notice-b-late"] = notice
    next_snapshot = capture_framework_state(
        orders=orders_after,
        positions=restored.positions,
        trades=restored.trades,
        data_by_ref={"rb": new_data},
        owner=new_owner,
        broker=new_broker,
    )
    completed = reopened.commit_execution_projection(
        8, next_snapshot, expected_revision=recovered.revision, expected_applied_sequence=3
    )
    assert completed.applied_sequence == 8 and completed.acknowledged_sequence == 0
    reopened_again = GatewayPendingHost(state.strategy_dir, state.strategy_uuid, binding)
    assert reopened_again.read_execution_events() == ()
    third_data, third_owner, third_broker = _framework()
    third = restore_framework_state(
        reopened_again.load_execution_checkpoint().projection,
        data_by_ref={"rb": third_data},
        owner=third_owner,
        broker=third_broker,
        commission_for_data=third_broker.getcommissioninfo,
    )
    assert third.positions["rb"].size == 3 and third.trades["trade-b"].size == 2
    assert third.positions["rb"].price == pytest.approx(11.0)
    assert third.trades["trade-b"].price == pytest.approx(11.5)
    assert third.trades["trade-b"].commission == pytest.approx(0.2)
    assert third.orders["key-b"].executed.size == 2
    assert len(third.orders["key-b"].executed.exbits) == len(third.trades["trade-b"].history) == 2
    assert third.trades["trade-b"].history[1].event.order is third.orders["notice-b-late"]
    assert third.orders["notice-b-late"].ref == third.orders["key-b"].ref
    assert third.orders["key-b"].ref != b.ref and third.trades["trade-b"].ref != tb.ref
