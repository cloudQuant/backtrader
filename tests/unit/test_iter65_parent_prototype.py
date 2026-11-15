"""65.01 parent-ID experiment, UNIT/FAKE only; no provider authority is implied.

The fake SDK supplies a stable logical parent ID. Child order/trade IDs below
are synthetic test facts, not fields asserted to be valid for any venue. The
prototype deliberately does not invent a venue order number for the parent.
It does not exercise Execution, Gateway, SDK parent projection, or a real account.
"""

from dataclasses import replace
from pathlib import Path
import datetime as dt
import sys

import pytest

import backtrader as bt
from bt_api_base.direct_write_protocol import (
    DirectExecutionEvent,
    DirectExecutionEventKind,
    NativeOrderIdentity,
)
from tests.unit.brokers.direct import _fakes as fake

PARENT = "parent-65-01"
WORKSPACE = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module", autouse=True)
def require_isolated_imports():
    """Do not accept observations made using the main SDK checkout."""
    yield
    escaped = {}
    for name, module in tuple(sys.modules.items()):
        if name == "backtrader" or name.startswith(("backtrader.", "bt_api_py", "bt_api_")):
            source = getattr(module, "__file__", None)
            if source and not Path(source).resolve().is_relative_to(WORKSPACE):
                escaped[name] = source
    assert not escaped, f"Non-worktree BT/SDK imports: {escaped}"


@pytest.fixture
def env(tmp_path, monkeypatch):
    # The real broker receives the logical parent in the fake SDK's actual
    # make_order result and pre-dispatch record, not by editing its index.
    monkeypatch.setattr(fake, "native_identity", lambda *a, **kw: parent_identity())
    environment = fake.Env(tmp_path)
    try:
        yield environment
    finally:
        environment.close()


def parent_identity():
    return NativeOrderIdentity(
        exchange_name=fake.EXCHANGE,
        client_order_id=PARENT,
        fields={"parent_ref": PARENT, "origin_trading_day": fake.TODAY},
        session_generation=1,
    )


def parent_order(status, *, qty=10, filled=0):
    return fake.order_event(parent_identity(), status, sys_id=None, qty=qty, filled=filled)


def child_fill(trade_id, child_order_id, *, day=fake.TODAY, qty=1, price=3500):
    # The identity remains parent-only. The separate exchange_order_id is a
    # synthetic child's real-fact stand-in and participates in BT dedup.
    return DirectExecutionEvent(
        kind=DirectExecutionEventKind.TRADE,
        exchange_name=fake.EXCHANGE,
        symbol=fake.SYMBOL,
        identity=parent_identity(),
        exchange_order_id=child_order_id,
        side="buy",
        offset="open",
        trade_id=trade_id,
        trade_price=price,
        trade_qty=qty,
        trading_day=day,
    )


def buy(env, broker):
    return broker.buy(env.strategy, env.feed, 10, price=3500, exectype=bt.Order.Limit, offset="open")


def start(env, **kwargs):
    broker = env.start(**kwargs)
    fake.quiet(broker)
    return broker


def test_import_is_the_isolated_bt_checkout():
    assert Path(bt.__file__).resolve().is_relative_to(Path(__file__).resolve().parents[2])


@pytest.mark.parametrize("cancel_first", [False, True], ids=["fills_first", "cancel_first"])
def test_parent_partial_fills_cancel_ordering_and_replay(env, cancel_first):
    broker = start(env, first_init=True)
    order = buy(env, broker)
    assert env.api.place_calls[-1].identity == parent_identity()
    env.api.push(parent_order("accepted"))
    broker.next()
    assert order.status == bt.Order.Accepted
    fake.drain(broker)

    fills = [child_fill("trade-1", "child-1"), child_fill("trade-2", "child-2"), child_fill("trade-3", "child-3")]
    if cancel_first:
        env.api.push(parent_order("cancelled", filled=3))
        broker.next()
        assert order.status == bt.Order.Accepted and order.executed.size == 0
    for event in fills:
        env.api.push(event)
        broker.next()
    if not cancel_first:
        env.api.push(parent_order("cancelled", filled=3))
        broker.next()
    assert order.status == bt.Order.Canceled
    assert order.executed.size == 3 and order.executed.remsize == 7
    assert broker.getposition(env.feed, side="long").size == 3
    assert fake.last_status(fake.drain(broker)) == ["Partial", "Partial", "Partial", "Canceled"]
    env.api.push(fills[0])
    broker.next()
    assert order.executed.size == 3 and broker.getposition(env.feed, side="long").size == 3


def test_parent_cancel_passes_stable_identity_to_fake_sdk(env):
    broker = start(env, first_init=True)
    order = buy(env, broker)
    env.api.push(parent_order("accepted"))
    broker.next()
    broker.cancel(order)
    assert len(env.api.cancel_calls) == 1
    assert env.api.cancel_calls[0].target == parent_identity()
    assert order.alive()  # request accepted by fake SDK is not a cancellation confirmation


def test_trade_id_collision_across_children_requires_child_order_identity(env):
    broker = start(env, first_init=True)
    order = buy(env, broker)
    env.api.push(parent_order("accepted"))
    broker.next()
    one = child_fill("reused-trade", "child-1")
    two = child_fill("reused-trade", "child-2")
    env.api.push(one)
    env.api.push(two)
    broker.next()
    assert order.executed.size == 2
    assert broker._direct_trade_key(one) != broker._direct_trade_key(two)
    # If projection omits child order identity both facts collapse to one key.
    assert broker._direct_trade_key(replace(one, exchange_order_id=None)) == broker._direct_trade_key(replace(two, exchange_order_id=None))


def test_restart_parent_only_does_not_group_child_trades(env):
    env.init_flat()
    marker, _ = env.seed_marker("ignored", identity=parent_identity())
    env.api.active_orders = [parent_order("partially_filled", filled=2)]
    env.api.trades = [child_fill("trade-1", "child-1"), child_fill("trade-2", "child-2")]
    env.api.positions = [fake.position("long", 2, 2, 0)]
    broker = start(env)
    report = broker.get_direct_reconcile_report()
    assert report["applied_missing_trades"] == 0
    assert report["restored_orders"] == 1
    (restored,) = broker.get_restored_orders()
    assert restored.size == 10 and restored.executed.size == 0
    assert restored.info["venue_filled_before"] == 0
    assert broker.direct_writes_blocked()[fake.SYMBOL] == "fill_gap_reconcile"
    assert env.state().pending.get(marker)["status"] != "TERMINAL"


def test_restart_does_not_restore_synthetic_original_deadline(env):
    """A seeded future deadline is not proof that direct submission accepts it."""
    env.init_flat()
    original = "2026-11-07T14:00:00"
    marker, _ = env.seed_marker(
        "ignored", identity=parent_identity(), summary={"prototype_deadline": original}
    )
    assert env.state().pending.get(marker)["request_summary"]["prototype_deadline"] == original
    env.api.active_orders = [parent_order("accepted")]
    broker = start(env)
    assert broker.get_direct_reconcile_report()["restored_orders"] == 1
    (restored,) = broker.get_restored_orders()
    assert restored.valid is None
    assert broker._direct_meta[restored.ref]["valid_intent"] == {"kind": "day", "value": None}


def test_direct_rejects_explicit_future_deadline_before_fake_sdk(env):
    broker = start(env, first_init=True)
    order = broker.buy(
        env.strategy, env.feed, 10, price=3500, exectype=bt.Order.Limit,
        offset="open", valid=dt.datetime(2026, 11, 7, 14, 0),
    )
    assert order.status == bt.Order.Rejected
    assert order.info["error_code"] == "order_validity_unrepresentable"
    assert env.api.place_calls == []


def test_restart_new_day_keeps_parent_unknown_even_if_listed(env):
    env.init_flat()
    marker, _ = env.seed_marker("ignored", identity=parent_identity(), trading_day=fake.TODAY)
    env.api.trading_day = fake.TOMORROW
    env.api.active_orders = [replace(parent_order("partially_filled", filled=2), trading_day=fake.TOMORROW)]
    broker = start(env)
    report = broker.get_direct_reconcile_report()
    assert marker in report["unknown_markers"]
    assert report["restored_orders"] == 0
    assert env.state().pending.get(marker)["status"] == "UNKNOWN"
    assert broker.direct_writes_blocked()[fake.SYMBOL] == "pending_unknown"


def test_same_child_and_trade_ids_on_distinct_days_collide_in_live_parent(env):
    """Collision experiment only; it does not assert any venue's ID scope."""
    broker = start(env, first_init=True)
    order = buy(env, broker)
    env.api.push(parent_order("accepted"))
    broker.next()
    old = child_fill("same-trade", "same-child-order", day=fake.TODAY)
    new = child_fill("same-trade", "same-child-order", day=fake.TOMORROW)
    assert broker._direct_trade_key(old) == broker._direct_trade_key(new)
    env.api.push(old)
    env.api.push(new)
    broker.next()
    assert order.executed.size == 1  # the distinct synthetic next-day fact was dropped
    assert broker.getposition(env.feed, side="long").size == 1


def test_same_day_unknown_parent_stays_unknown_even_when_listed(env):
    env.init_flat()
    marker, _ = env.seed_marker("ignored", identity=parent_identity(), status="UNKNOWN")
    env.api.active_orders = [parent_order("accepted")]
    broker = start(env)
    assert marker in broker.get_direct_reconcile_report()["unknown_markers"]
    assert broker.get_direct_reconcile_report()["restored_orders"] == 0
    assert broker.direct_writes_blocked()[fake.SYMBOL] == "pending_unknown"


def test_child_native_identity_takes_precedence_over_parent_client_id(env):
    broker = start(env, first_init=True)
    order = buy(env, broker)
    env.api.push(parent_order("accepted"))
    broker.next()
    # Both IDs are synthetic. This shows the current precedence, not a claim
    # about any provider's choice or scope of native IDs.
    identity = NativeOrderIdentity(
        exchange_name=fake.EXCHANGE,
        client_order_id=PARENT,
        fields={"exchange_id": "venue-test", "order_sys_id": "child-1"},
    )
    event = replace(child_fill("trade-1", "child-1"), identity=identity)
    assert broker._direct_order_for_event(event) is None
    env.api.push(event)
    broker.next()
    assert order.executed.size == 0
    assert len(broker._direct_trade_buffer) == 1
