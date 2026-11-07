"""Return gap: a same-day session change or a provider event drop (2026-11-07).

The CTP private flow runs QUICK, so returns of a same-day TD reconnect gap are
never re-delivered, and the provider's bounded return queue may drop events.
After each event drain the Broker compares the provider session generation
(same trading day only; another day goes to the R-3 switch) and the optional
``direct_execution_dropped_events`` count.  A signal blocks new orders
(``return_gap_reconcile``) until one complete observation was reconciled
through the live-return projection: own fills applied exactly once, own order
statuses projected, own sent orders absent from the complete list
``not_found_at_venue`` (D63-38 a, never re-sent).  Incomplete reads keep the
block and retry with a bounded backoff.

UNIT/FAKE: fake facade, real ``backtrader.live_state`` in ``tmp_path``.  The
background poller is stopped (``quiet``); each test drives the poller side.
"""

import datetime as dt
import time

import pytest

pytest.importorskip("bt_api_py", reason="direct mode needs the bt_api_py SDK DTOs")

import backtrader as bt
from bt_api_base.trading_session_protocol import TradingPhase

from ._fakes import (
    EXCHANGE,
    SYMBOL,
    T0,
    TOMORROW,
    drain,
    last_status,
    order_event,
    position,
    quiet,
    run_day_switch,
    trade_event,
    window,
)

GAP = "return_gap_reconcile"
NEW_DAY = dt.date(2026, 11, 6)


def _start(env, **params):
    params.setdefault("direct_return_gap_quiet_period", 0.0)
    broker = env.start(first_init=True, **params)
    quiet(broker)
    return broker


def _buy(env, broker, size=1):
    return broker.buy(
        env.strategy, env.feed, size, price=3500.0, exectype=bt.Order.Limit, offset="open"
    )


def _working(env, broker, sys_id="5001", size=1):
    order = _buy(env, broker, size)
    call = env.api.place_calls[-1]
    env.api.push(order_event(call.identity, "accepted", sys_id=sys_id, qty=size))
    broker.next()
    assert order.status == bt.Order.Accepted
    drain(broker)
    return order, call


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


def _counter(env, value=0):
    count = {"value": value}
    env.api.direct_execution_dropped_events = lambda exchange_name: count["value"]
    return count


# ---------------------------------------------------------------------------
# same-day reconnect
# ---------------------------------------------------------------------------
def test_fill_during_a_same_day_reconnect_is_applied_exactly_once(env):
    broker = _start(env)
    order, call = _working(env, broker)
    # TD reconnect on the same trading day; the fill's returns were lost (QUICK).
    env.api.session_generation = 2
    _venue(
        env,
        orders=[order_event(call.identity, "filled", sys_id="5001", filled=1.0)],
        trades=[trade_event("T1", sys_id="5001")],
        positions=[position("long", 1, 1, 0)],
    )
    broker.next()
    gap = broker.get_direct_reconcile_report()["return_gap"]
    assert gap["status"] == "pending" and gap["detected_by"] == "session_generation_changed"
    assert broker.direct_writes_blocked() == {"*": GAP}
    places = len(env.api.place_calls)
    refused = _buy(env, broker)
    assert refused.status == bt.Order.Rejected and refused.info["error_code"] == GAP
    assert len(env.api.place_calls) == places
    drain(broker)

    gap = run_gap(broker)
    assert gap["status"] == "completed" and gap["applied_trades"] == 1
    assert order.status == bt.Order.Completed
    assert "Completed" in last_status(drain(broker))  # the strategy sees the fill
    assert broker.getposition(env.feed).size == 1
    assert broker.direct_writes_blocked() == {}
    assert broker._direct_session_generation == 2
    marker = env.state().pending.get(call.marker_id)
    assert marker["status"] == "TERMINAL" and marker["facts"]["final_status"] == "filled"
    assert env.state().snapshot.read()["positions"][SYMBOL]["long"]["total"] == 1

    # A late replay of the same fill and a second reconcile never book it again.
    env.api.push(trade_event("T1", sys_id="5001"))
    broker.next()
    env.api.session_generation = 3
    broker.next()
    assert run_gap(broker)["applied_trades"] == 0
    assert broker.getposition(env.feed).size == 1
    assert _buy(env, broker).status == bt.Order.Submitted


def test_own_order_cancelled_during_the_gap_ends_cancelled(env):
    broker = _start(env)
    order, call = _working(env, broker, "5002")
    env.api.session_generation = 2
    _venue(env, orders=[order_event(call.identity, "cancelled", sys_id="5002")])
    broker.next()
    assert broker.direct_writes_blocked() == {"*": GAP}
    gap = run_gap(broker)
    assert gap["status"] == "completed" and gap["projected_orders"] == 1
    assert order.status == bt.Order.Canceled
    assert last_status(drain(broker)) == ["Canceled"]
    marker = env.state().pending.get(call.marker_id)
    assert marker["status"] == "TERMINAL" and marker["facts"]["final_status"] == "cancelled"


def test_partly_filled_then_cancelled_order_books_the_fill_then_cancels(env):
    broker = _start(env)
    order, call = _working(env, broker, "5003", size=2)
    env.api.session_generation = 2
    _venue(
        env,
        orders=[order_event(call.identity, "cancelled", sys_id="5003", qty=2, filled=1.0)],
        trades=[trade_event("T3", sys_id="5003")],
        positions=[position("long", 1, 1, 0)],
    )
    broker.next()
    gap = run_gap(broker)
    assert gap["applied_trades"] == 1
    assert order.status == bt.Order.Canceled and order.executed.size == 1
    assert last_status(drain(broker)) == ["Partial", "Canceled"]
    assert broker.getposition(env.feed).size == 1
    assert broker.direct_writes_blocked() == {}


def test_sent_order_absent_from_the_complete_list_is_rejected_not_resent(env):
    broker = _start(env)
    order = _buy(env, broker)  # sent, no return yet
    (call,) = env.api.place_calls
    drain(broker)
    env.api.session_generation = 2
    _venue(env)  # complete, same day: the identity is not there
    broker.next()
    gap = run_gap(broker)
    assert gap["status"] == "completed" and gap["not_found_at_venue"] == [call.marker_id]
    assert order.status == bt.Order.Rejected
    assert order.info["error_code"] == "not_found_at_venue"
    assert last_status(drain(broker)) == ["Rejected"]
    marker = env.state().pending.get(call.marker_id)
    assert marker["facts"]["final_status"] == "not_found_at_venue"
    assert marker["facts"]["resolution_evidence"] == "return_gap_complete_order_query"
    assert call.marker_id in broker.get_direct_reconcile_report()["not_found_at_venue"]
    broker.next()
    assert len(env.api.place_calls) == 1  # never re-sent
    assert broker.direct_writes_blocked() == {}


def test_unknown_send_absent_from_the_complete_list_unblocks_the_symbol(env):
    broker = _start(env)
    env.api.outcomes.append({"sent": None, "error_code": "timeout"})
    order = _buy(env, broker)
    assert broker.direct_writes_blocked() == {SYMBOL: "pending_unknown"}
    env.api.session_generation = 2
    _venue(env)
    broker.next()
    run_gap(broker)
    assert order.status == bt.Order.Rejected
    assert broker.direct_writes_blocked() == {}


def test_acknowledged_order_missing_from_the_list_is_kept_and_blocked(env):
    broker = _start(env)
    order, _call = _working(env, broker, "5004")
    env.api.session_generation = 2
    _venue(env)  # contradicts the venue's own acknowledgement
    broker.next()
    gap = run_gap(broker)
    assert gap["status"] == "completed" and len(gap["unverified_orders"]) == 1
    assert order.status == bt.Order.Accepted  # nothing concluded
    assert broker.direct_writes_blocked() == {SYMBOL: "return_gap_order_unverified"}


def test_foreign_orders_and_fills_of_the_account_are_never_adopted(env):
    from ._fakes import native_identity

    broker = _start(env)
    foreign = native_identity("000000000777")
    env.api.session_generation = 2
    _venue(
        env,
        orders=[order_event(foreign, "filled", sys_id="9001", filled=1.0)],
        trades=[trade_event("T9", sys_id="9001")],
    )
    broker.next()
    gap = run_gap(broker)
    assert gap["applied_trades"] == 0 and gap["projected_orders"] == 0
    assert broker.getposition(env.feed).size == 0
    assert "unmatched_trade_returns" not in broker.get_direct_reconcile_report()


# ---------------------------------------------------------------------------
# dropped events
# ---------------------------------------------------------------------------
def test_dropped_count_increase_triggers_the_same_reconcile(env):
    count = _counter(env, 4)  # drops before the startup observation: covered by it
    broker = _start(env)
    assert broker._direct_dropped_seen == 4
    order, call = _working(env, broker, "5005")
    assert "return_gap" not in broker.get_direct_reconcile_report()
    _venue(
        env,
        orders=[order_event(call.identity, "filled", sys_id="5005", filled=1.0)],
        trades=[trade_event("T5", sys_id="5005")],
        positions=[position("long", 1, 1, 0)],
    )
    count["value"] = 5  # the fill's return was dropped by the provider queue
    broker.next()
    gap = broker.get_direct_reconcile_report()["return_gap"]
    assert gap["detected_by"] == "dropped_events" and gap["dropped_events"] == 5
    assert broker.direct_writes_blocked() == {"*": GAP}
    gap = run_gap(broker)
    assert gap["status"] == "completed" and gap["applied_trades"] == 1
    assert order.status == bt.Order.Completed
    broker.next()  # the same count opens nothing new
    assert broker.get_direct_reconcile_report()["return_gap"]["status"] == "completed"


def test_a_lower_dropped_count_is_not_proof_of_no_loss(env):
    count = _counter(env, 7)
    broker = _start(env)
    count["value"] = 0  # e.g. a re-created provider
    broker.next()
    gap = broker.get_direct_reconcile_report()["return_gap"]
    assert gap["detected_by"] == "dropped_events_reset"


def test_a_drop_during_a_read_makes_that_read_stale(env):
    count = _counter(env, 0)
    broker = _start(env)
    count["value"] = 1
    broker.next()
    broker._direct_gap_due = 0.0
    broker._direct_return_gap_poll()  # read for the first signal
    count["value"] = 2  # another drop before the read is applied
    broker.next()  # drain: renewed signal, then the old read is stale
    gap = broker.get_direct_reconcile_report()["return_gap"]
    assert gap["status"] == "pending" and gap["attempts"] == 0
    assert broker.direct_writes_blocked() == {"*": GAP}
    assert run_gap(broker)["status"] == "completed"


@pytest.mark.parametrize(
    "install",
    [
        None,  # facade without the method
        lambda api: setattr(api, "direct_execution_dropped_events", lambda name: None),
        lambda api: setattr(
            api, "direct_execution_dropped_events", lambda name: (_ for _ in ()).throw(OSError())
        ),
    ],
    ids=["missing", "none", "raises"],
)
def test_without_a_dropped_count_the_broker_works_unchanged(env, install):
    if install is not None:
        install(env.api)
    broker = _start(env)
    order = _buy(env, broker)
    call = env.api.place_calls[-1]
    env.api.push(order_event(call.identity, "accepted", sys_id="5006"))
    env.api.push(trade_event("T6", sys_id="5006"))
    for _ in range(3):
        broker.next()
    assert order.status == bt.Order.Completed
    assert broker._direct_dropped_seen is None
    assert "return_gap" not in broker.get_direct_reconcile_report()
    assert broker.direct_writes_blocked() == {}
    assert _buy(env, broker).status == bt.Order.Submitted


# ---------------------------------------------------------------------------
# incomplete reads, backoff, quiet period
# ---------------------------------------------------------------------------
def test_incomplete_facts_keep_writes_blocked_and_retry_with_backoff(env):
    broker = _start(env, direct_return_gap_retry_interval=10.0)
    order, call = _working(env, broker, "5007")
    env.api.session_generation = 2
    _venue(
        env,
        orders=[order_event(call.identity, "filled", sys_id="5007", filled=1.0)],
        trades=[trade_event("T7", sys_id="5007")],
        positions=[position("long", 1, 1, 0)],
    )
    broker.next()
    env.api.incomplete_reads = 2
    env.api.blockers = ("orders_query_incomplete",)
    before = time.monotonic()
    gap = run_gap(broker)
    assert gap["status"] == "pending" and gap["last_reason"] == "account_facts_incomplete"
    assert gap["blockers"] == ["orders_query_incomplete"]
    assert broker._direct_gap_request is not None
    assert before + 10.0 <= broker._direct_gap_due <= time.monotonic() + 10.0
    assert order.status == bt.Order.Accepted  # nothing applied from incomplete facts
    assert broker.direct_writes_blocked() == {"*": GAP}
    reads = len(env.api.facts_calls)
    broker._direct_return_gap_poll()  # not due yet: no read
    assert len(env.api.facts_calls) == reads
    before = time.monotonic()
    gap = run_gap(broker)  # second failure: the delay doubles
    assert gap["failures"] == 2
    assert before + 20.0 <= broker._direct_gap_due <= time.monotonic() + 20.0
    gap = run_gap(broker)
    assert gap["status"] == "completed" and gap["attempts"] == 3
    assert order.status == bt.Order.Completed
    assert broker.direct_writes_blocked() == {}


def test_a_session_change_during_the_read_is_not_accepted(env):
    broker = _start(env)
    env.api.session_generation = 2
    broker.next()
    read = env.api.direct_account_facts

    def reconnect_while_reading(exchange_name, **sections):
        facts = read(exchange_name, **sections)
        env.api.session_generation = 3
        return facts

    env.api.direct_account_facts = reconnect_while_reading
    payload = broker._direct_return_gap_reads(broker._direct_gap_request)
    assert payload["ok"] is False and payload["reason"] == "session_changed"
    env.api.direct_account_facts = read
    broker._direct_facts_results.append(("return_gap", payload))
    broker.next()  # the drain renews the gap for generation 3 first
    gap = broker.get_direct_reconcile_report()["return_gap"]
    assert gap["status"] == "pending" and gap["generation"] == 3
    assert broker.direct_writes_blocked() == {"*": GAP}
    gap = run_gap(broker)
    assert gap["status"] == "completed" and broker._direct_session_generation == 3


def test_the_complete_query_waits_for_the_quiet_period_after_the_last_order(env):
    broker = _start(env, direct_return_gap_quiet_period=30.0)
    _buy(env, broker)
    env.api.session_generation = 2
    broker.next()
    reads = len(env.api.facts_calls)
    broker._direct_gap_due = 0.0
    broker._direct_return_gap_poll()
    assert len(env.api.facts_calls) == reads  # an insert just sent may not be listed yet
    assert broker._direct_gap_due >= broker._direct_last_place_at + 30.0 - 1e-6


def test_waiting_orders_are_held_not_rejected_during_the_gap(env, clock):
    broker = _start(env)
    env.api.schedule.phase = TradingPhase.CLOSED
    env.api.schedule.next_window = window(T0 + dt.timedelta(hours=1), T0 + dt.timedelta(hours=3))
    waiting = _buy(env, broker)
    assert waiting.info["waiting_session"] is True
    clock["value"] = T0 + dt.timedelta(hours=1)
    env.api.schedule.phase = TradingPhase.CONTINUOUS
    env.api.session_generation = 2
    broker.next()  # the gap is detected by the drain, before the waiting queue
    assert env.api.place_calls == []
    assert env.state().waiting.get(waiting.info["waiting_id"])["status"] == "WAITING"
    run_gap(broker)
    broker.next()
    assert len(env.api.place_calls) == 1


# ---------------------------------------------------------------------------
# trading-day switch: one path only
# ---------------------------------------------------------------------------
def test_a_session_change_with_a_new_trading_day_goes_through_the_switch(env):
    broker = _start(env)
    env.api.schedule.trading_day = NEW_DAY
    env.api.session_generation = 2
    env.api.trading_day = TOMORROW
    broker.next()
    report = broker.get_direct_reconcile_report()
    assert "return_gap" not in report and broker._direct_gap_request is None
    assert report["trading_day_switch"]["status"] == "pending"
    switch = run_day_switch(broker)
    assert switch["status"] == "completed" and switch["reconnected"] is True
    assert broker._direct_session_generation == 2
    broker.next()
    assert "return_gap" not in broker.get_direct_reconcile_report()
    assert broker.direct_writes_blocked() == {}


def test_a_pending_gap_is_superseded_when_its_read_finds_a_new_day(env):
    broker = _start(env)
    env.api.session_generation = 2
    broker.next()
    assert broker.direct_writes_blocked() == {"*": GAP}
    env.api.schedule.trading_day = NEW_DAY
    env.api.trading_day = TOMORROW
    gap = run_gap(broker)
    assert gap["status"] == "superseded" and gap["last_reason"] == "trading_day_switch"
    assert broker._direct_return_gap is None and broker._direct_gap_request is None
    assert broker.direct_writes_blocked() == {"*": "trading_day_switch_pending"}
    assert run_day_switch(broker)["status"] == "completed"
    broker.next()
    assert broker.direct_writes_blocked() == {}


def test_drops_counted_during_a_switch_open_a_gap_after_it(env):
    count = _counter(env, 0)
    broker = _start(env)
    env.api.schedule.trading_day = NEW_DAY
    env.api.trading_day = TOMORROW
    broker.next()
    assert broker._direct_day_switch_active()
    count["value"] = 3
    broker.next()
    assert broker._direct_return_gap is None  # the switch owns this moment
    assert run_day_switch(broker)["status"] == "completed"
    broker.next()  # the first drain after the switch compares the count
    gap = broker.get_direct_reconcile_report()["return_gap"]
    assert gap["status"] == "pending" and gap["detected_by"] == "dropped_events"
    assert gap["trading_day"] == TOMORROW
    assert run_gap(broker)["status"] == "completed"
