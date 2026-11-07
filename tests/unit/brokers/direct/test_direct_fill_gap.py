"""Fill gap after the trade-match window (iteration 62 re-review §4 item 1, 2026-11-07).

A trade return that overtakes its order return is held for
``direct_trade_match_window``; past the window it is released as unmatched
(never claimed by inference).  When the order is later associated by its own
identity and its trusted order return shows a venue cumulative traded volume
above the fills applied locally for that order, and that is still so one
window later, the symbol is blocked (``fill_gap_reconcile``) and the existing
return-gap reconcile reads the complete orders and trades: own missing trades
are applied exactly once by trade key with the order's venue identity.  The
symbol is unblocked once the applied fills equal the venue cumulative; a
complete trade list without the missing fills keeps it blocked
(``fill_gap_unresolved``) and retries with the return-gap backoff.  Other
symbols stay writable.  A restored working order's executed base is the fills
the startup trade list proves (CTP-style routes), so a restart never hides a
gap.  Cumulative numbers never fabricate per-trade fills.

UNIT/FAKE: fake facade, real ``backtrader.live_state`` in ``tmp_path``; the
facts poller is stopped (``quiet``) and the window clock is patched.
"""

import time

import pytest

pytest.importorskip("bt_api_py", reason="direct mode needs the bt_api_py SDK DTOs")

import backtrader as bt
from backtrader.brokers import _btapi_direct_mode as direct_mode

from ._fakes import (
    SYMBOL,
    crash,
    drain,
    last_status,
    order_event,
    position,
    quiet,
    trade_event,
)

RECONCILE = "fill_gap_reconcile"
UNRESOLVED = "fill_gap_unresolved"


@pytest.fixture
def now(monkeypatch):
    value = {"t": 1000.0}
    monkeypatch.setattr(direct_mode, "_monotonic", lambda: value["t"])
    return value


def _start(env, **params):
    params.setdefault("direct_return_gap_quiet_period", 0.0)
    broker = env.start(**params)
    quiet(broker)
    return broker


def _buy(env, broker, data=None, size=1):
    return broker.buy(
        env.strategy,
        data if data is not None else env.feed,
        size,
        price=3500.0,
        exectype=bt.Order.Limit,
        offset="open",
    )


def _venue(env, *, orders=(), active=(), trades=(), positions=()):
    env.api.orders = list(orders)
    env.api.active_orders = list(active)
    env.api.trades = list(trades)
    env.api.positions = list(positions)


def run_gap(broker):
    """One facts-poller reconcile read of the pending gap, then ``next``."""
    broker._direct_gap_due = 0.0
    broker._direct_return_gap_poll()
    broker.next()
    return dict(broker.get_direct_reconcile_report().get("return_gap") or {})


def _released_fill_then_cumulative(env, broker, now, sys_id="7001"):
    """The re-review reproduction: the fill is released unmatched, then its order shows it."""
    order = _buy(env, broker)
    call = env.api.place_calls[-1]
    env.api.push(trade_event("T1", sys_id=sys_id))  # ahead of its order return
    broker.next()
    now["t"] += 5.1  # past direct_trade_match_window: released, not ours by inference
    broker.next()
    assert broker.get_direct_reconcile_report()["unmatched_trade_returns"]["count"] == 1
    env.api.push(order_event(call.identity, "filled", sys_id=sys_id, filled=1.0))
    broker.next()
    assert order.status == bt.Order.Accepted and order.executed.size == 0
    assert broker.getposition(env.feed, side="long").size == 0
    drain(broker)
    return order, call


def test_released_fill_with_a_later_cumulative_is_blocked_reconciled_and_applied_once(env, now):
    broker = _start(env, first_init=True)
    order, call = _released_fill_then_cumulative(env, broker, now)
    # Inside one window after the order return the late fill may still come.
    assert broker.direct_writes_blocked() == {}
    now["t"] += 5.1
    broker.next()
    assert broker.direct_writes_blocked() == {SYMBOL: RECONCILE}
    places = len(env.api.place_calls)
    refused = _buy(env, broker)
    assert refused.status == bt.Order.Rejected and refused.info["error_code"] == RECONCILE
    assert len(env.api.place_calls) == places
    # Only the gap's symbol: another instrument stays writable.
    assert _buy(env, broker, env.other_feed).status == bt.Order.Submitted
    gaps = broker.get_direct_reconcile_report()["fill_gaps"]
    assert gaps["detected"] == 1
    (entry,) = gaps["open"].values()
    assert (entry["symbol"], entry["venue_filled"], entry["applied"]) == (SYMBOL, 1.0, 0.0)
    assert entry["state"] == "reconcile"
    drain(broker)

    _venue(
        env,
        orders=[order_event(call.identity, "filled", sys_id="7001", filled=1.0)],
        trades=[trade_event("T1", sys_id="7001")],
        positions=[position("long", 1, 1, 0)],
    )
    gap = run_gap(broker)
    assert gap["status"] == "completed" and gap["applied_trades"] == 1
    assert order.status == bt.Order.Completed and order.executed.size == 1
    assert "Completed" in last_status(drain(broker))
    assert broker.getposition(env.feed, side="long").size == 1
    assert broker.direct_writes_blocked() == {}
    gaps = broker.get_direct_reconcile_report()["fill_gaps"]
    assert gaps["resolved"] == 1 and gaps["open"] == {}
    marker = env.state().pending.get(call.marker_id)
    assert marker["status"] == "TERMINAL" and marker["facts"]["final_status"] == "filled"

    # A replayed fill and order return later never book it again.
    env.api.push(trade_event("T1", sys_id="7001"))
    env.api.push(order_event(call.identity, "filled", sys_id="7001", filled=1.0))
    broker.next()
    now["t"] += 10.0
    broker.next()
    assert order.executed.size == 1
    assert broker.getposition(env.feed, side="long").size == 1
    assert broker.direct_writes_blocked() == {}
    assert _buy(env, broker).status == bt.Order.Submitted


def test_fill_missing_from_the_complete_trade_list_stays_blocked_and_retries(env, now):
    broker = _start(env, first_init=True, direct_return_gap_retry_interval=10.0)
    order, call = _released_fill_then_cumulative(env, broker, now, sys_id="7002")
    now["t"] += 5.1
    broker.next()
    listed = order_event(call.identity, "filled", sys_id="7002", filled=1.0)
    _venue(env, orders=[listed], positions=[position("long", 1, 1, 0)])  # no trade row
    before = time.monotonic()
    gap = run_gap(broker)
    assert gap["status"] == "pending" and gap["last_reason"] == UNRESOLVED
    assert broker.direct_writes_blocked() == {SYMBOL: UNRESOLVED}
    assert before + 10.0 <= broker._direct_gap_due <= time.monotonic() + 10.0
    # Never fabricated from the cumulative number.
    assert order.executed.size == 0 and broker.getposition(env.feed, side="long").size == 0
    places = len(env.api.place_calls)
    refused = _buy(env, broker)
    assert refused.status == bt.Order.Rejected and refused.info["error_code"] == UNRESOLVED
    assert len(env.api.place_calls) == places
    assert _buy(env, broker, env.other_feed).status == bt.Order.Submitted
    (entry,) = broker.get_direct_reconcile_report()["fill_gaps"]["open"].values()
    assert entry["state"] == "unresolved"

    gap = run_gap(broker)  # still missing: the backoff doubles
    assert gap["failures"] == 2 and broker.direct_writes_blocked() == {SYMBOL: UNRESOLVED}
    _venue(
        env,
        orders=[listed],
        trades=[trade_event("T1", sys_id="7002")],
        positions=[position("long", 1, 1, 0)],
    )
    gap = run_gap(broker)
    assert gap["status"] == "completed"
    assert order.status == bt.Order.Completed and order.executed.size == 1
    assert broker.direct_writes_blocked() == {}


def test_late_order_return_and_reconcile_both_seeing_the_fill_apply_it_once(env, now):
    broker = _start(env, first_init=True)
    order, call = _released_fill_then_cumulative(env, broker, now, sys_id="7003")
    now["t"] += 5.1
    broker.next()
    assert broker.direct_writes_blocked() == {SYMBOL: RECONCILE}
    _venue(
        env,
        orders=[order_event(call.identity, "filled", sys_id="7003", filled=1.0)],
        trades=[trade_event("T1", sys_id="7003")],
        positions=[position("long", 1, 1, 0)],
    )
    broker._direct_gap_due = 0.0
    broker._direct_return_gap_poll()  # the read is taken, not applied yet
    # The fill and its order return arrive live before the read is applied.
    env.api.push(trade_event("T1", sys_id="7003"))
    env.api.push(order_event(call.identity, "filled", sys_id="7003", filled=1.0))
    broker.next()
    assert order.status == bt.Order.Completed and order.executed.size == 1
    assert broker.getposition(env.feed, side="long").size == 1
    assert broker.direct_writes_blocked() == {}
    run_gap(broker)
    assert order.executed.size == 1
    assert broker.getposition(env.feed, side="long").size == 1
    assert env.state().snapshot.read()["positions"][SYMBOL]["long"]["total"] == 1


def test_order_return_ahead_of_its_fill_within_the_window_never_blocks(env, now):
    """The usual CTP order: OnRtnOrder (cumulative) a moment before OnRtnTrade."""
    broker = _start(env, first_init=True)
    order = _buy(env, broker)
    call = env.api.place_calls[-1]
    env.api.push(order_event(call.identity, "filled", sys_id="7004", filled=1.0))
    broker.next()
    now["t"] += 4.0
    broker.next()
    env.api.push(trade_event("T1", sys_id="7004"))
    broker.next()
    now["t"] += 10.0
    broker.next()
    assert order.status == bt.Order.Completed
    assert broker.direct_writes_blocked() == {}
    assert "fill_gaps" not in broker.get_direct_reconcile_report()


def test_restart_does_not_hide_a_fill_missing_from_the_startup_trade_list(env, now):
    """Restored working order: the executed base is the fills the trade list proves."""
    env.init_flat()
    _marker_id, identity = env.seed_marker("000000000701")
    # Cumulative 1 of 2 at the venue, but the day's complete trade list (and the
    # position read) do not have that fill yet: nothing proves it was applied.
    env.api.active_orders = [
        order_event(identity, "partially_filled", sys_id="7101", qty=2, filled=1)
    ]
    env.api.trades = []
    env.api.positions = []
    broker = _start(env)
    assert broker.direct_writes_blocked() == {SYMBOL: RECONCILE}
    (restored,) = broker.take_over_restored_orders(env.strategy)
    assert restored.size == 2 and restored.info["venue_filled_before"] == 0.0
    refused = _buy(env, broker)
    assert refused.status == bt.Order.Rejected and refused.info["error_code"] == RECONCILE
    drain(broker)

    env.api.trades = [trade_event("T1", sys_id="7101")]
    env.api.positions = [position("long", 1, 1, 0)]
    broker.next()  # the first drain asks for the reconcile read
    gap = run_gap(broker)
    assert gap["status"] == "completed" and gap["applied_trades"] == 1
    assert restored.executed.size == 1 and restored.status == bt.Order.Partial
    assert broker.getposition(env.feed, side="long").size == 1
    assert broker.direct_writes_blocked() == {}
    env.api.push(trade_event("T2", sys_id="7101"))  # the remaining fill, live
    broker.next()
    assert restored.status == bt.Order.Completed
    assert broker.getposition(env.feed, side="long").size == 2
    crash(broker)


def test_restart_with_every_fill_listed_keeps_the_remaining_size(env):
    env.init_flat()
    _marker_id, identity = env.seed_marker("000000000702")
    env.api.active_orders = [
        order_event(identity, "partially_filled", sys_id="7102", qty=3, filled=1)
    ]
    env.api.trades = [trade_event("T1", sys_id="7102")]
    env.api.positions = [position("long", 1, 1, 0)]
    broker = _start(env)
    assert broker.direct_writes_blocked() == {}
    (restored,) = broker.get_restored_orders()
    assert restored.size == 2 and restored.info["venue_filled_before"] == 1.0
    assert "fill_gaps" not in broker.get_direct_reconcile_report()
