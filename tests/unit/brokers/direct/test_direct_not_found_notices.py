"""D63-38 a closure: Rejected notices of orders not found at the venue (2026-11-07).

User decisions 2026-11-07: a complete same-day order query without a marker's
strong native identity means "not at the venue": the marker is resolved
``not_found_at_venue``, the owning strategy is told with a Rejected order, the
instrument is unblocked and nothing is ever re-sent automatically; an
incomplete query or another trading day keeps UNKNOWN.  Plain (non-waiting)
orders get a restored Rejected order rebuilt from the marker's request summary.

* (a) the notice (plain marker or restart-rejected waiting order) is
  re-delivered on every restart of the same trading day until the strategy
  took it over; the takeover is durable (``facts.taken_over_at_utc``), so a
  taken-over notice is never delivered twice;
* (b) plain markers: rebuilt from the marker (side, size, price, offset,
  local_seq, bt_ref), handed over like other restored orders, deferred until
  the symbol's feed exists, never dispatched;
* (c) same-day markers already UNKNOWN are resolved by the complete order
  query (found: restored or terminal with missing fills; absent:
  ``not_found_at_venue``); incomplete query keeps UNKNOWN;
* (d) only with a strong native identity (CTP session triple or ExchangeID +
  OrderSysID); client-order-id routes (OKX/Binance) keep today's recovery.

UNIT/FAKE: fake facade, real ``backtrader.live_state`` in ``tmp_path``.
"""

import dataclasses
import datetime as dt

import pytest

pytest.importorskip("bt_api_py", reason="direct mode needs the bt_api_py SDK DTOs")

import backtrader as bt
from backtrader.live_state import PendingCommandStore, read_audit
from bt_api_base.direct_write_protocol import NativeOrderIdentity
from bt_api_base.trading_session_protocol import TradingPhase

from ._fakes import (
    EXCHANGE,
    SYMBOL,
    T0,
    TODAY,
    YESTERDAY,
    crash,
    drain,
    last_status,
    order_event,
    position,
    quiet,
    trade_event,
    window,
)

HOUR = dt.timedelta(hours=1)
NOT_FOUND = "not_found_at_venue"
WAITING_REASON = "restart_not_found_at_venue"


def _summary(**overrides):
    summary = {"bt_ref": 7, "side": "buy", "size": 2.0, "price": 3490.0, "offset": "open"}
    summary.update(overrides)
    return summary


def _buy(env, broker, size=1):
    return broker.buy(
        env.strategy, env.feed, size, price=3500.0, exectype=bt.Order.Limit, offset="open"
    )


def _notice(broker):
    restored = broker.get_restored_orders()
    assert len(restored) == 1, restored
    return restored[0]


# ---------------------------------------------------------------------------
# (b) plain markers: a rebuilt Rejected order
# ---------------------------------------------------------------------------
def test_plain_marker_not_found_at_startup_is_handed_over_rejected(env):
    env.init_flat()
    marker_id, _ = env.seed_marker("000000000501", local_seq=3, bt_ref=7, summary=_summary())
    broker = env.start()
    marker = env.state().pending.get(marker_id)
    assert marker["status"] == "TERMINAL" and marker["facts"]["final_status"] == NOT_FOUND
    assert broker.direct_writes_blocked() == {}

    notice = _notice(broker)
    assert notice.status == bt.Order.Rejected and notice.isbuy()
    assert (notice.size, notice.price) == (2.0, 3490.0)
    assert notice.info["restored"] is True and notice.info["error_code"] == NOT_FOUND
    assert notice.info["original_ref"] == 7 and notice.info["local_seq"] == 3
    assert notice.info["offset"] == "open" and notice.info["marker_id"] == marker_id
    assert notice.owner is None
    refused = _buy(env, broker)  # like any restored order: taken over first
    assert refused.info["error_code"] == "restored_orders_not_taken_over"
    drain(broker)

    assert broker.take_over_restored_orders(env.strategy) == [notice]
    assert last_status(drain(broker)) == ["Rejected"]
    assert env.state().pending.get(marker_id)["facts"]["taken_over_at_utc"]
    broker.next()
    broker.next()
    assert env.api.place_calls == []  # never dispatched
    assert notice.ref not in broker._direct_meta
    assert _buy(env, broker).status == bt.Order.Submitted


def test_plain_notice_waits_for_the_feed_of_its_symbol(env):
    env.init_flat()
    env.seed_marker("000000000502", summary=_summary(side="sell", price=None, offset="close"))
    env.store._data_feeds = [env.other_feed]
    broker = env.start()
    assert broker.get_restored_orders() == []
    broker.next()  # no feed yet: nothing blocked, nothing dispatched
    assert broker.direct_writes_blocked() == {}
    env.store._data_feeds = [env.feed, env.other_feed]
    broker.data_started(env.feed)
    notice = _notice(broker)
    assert notice.status == bt.Order.Rejected and notice.issell()
    assert notice.exectype == bt.Order.Market and notice.info["offset"] == "close"


def test_notice_built_after_the_takeover_is_notified_and_recorded(env):
    """The strategy took over before the feed started: told by notification, once."""
    env.init_flat()
    marker_id, _ = env.seed_marker("000000000505", summary=_summary())
    env.store._data_feeds = [env.other_feed]
    broker = env.start()
    assert broker.take_over_restored_orders(env.strategy) == []
    env.store._data_feeds = [env.feed, env.other_feed]
    broker.data_started(env.feed)
    (notice,) = [order for order in broker.notifs if order.info.get("restored")]
    assert notice.status == bt.Order.Rejected and notice.owner is env.strategy
    assert broker.get_restored_orders() == []
    assert env.state().pending.get(marker_id)["facts"]["taken_over_at_utc"]
    crash(broker)
    assert env.start().get_restored_orders() == []


def test_marker_without_a_request_summary_is_reported_not_rebuilt(env):
    env.init_flat()
    marker_id, _ = env.seed_marker("000000000503")  # older marker: no side/size
    broker = env.start()
    assert broker.get_restored_orders() == []
    assert broker.direct_writes_blocked() == {}
    report = broker.get_direct_reconcile_report()
    assert report["not_found_without_notice"] == [marker_id]


# ---------------------------------------------------------------------------
# (a) crash-safe notices
# ---------------------------------------------------------------------------
def test_plain_notice_is_redelivered_after_a_crash_until_taken_over(env):
    first = env.start(first_init=True)
    order = _buy(env, first, size=1)
    (call,) = env.api.place_calls
    crash(first)  # sent, no return: the venue never got it

    second = env.start()
    assert _notice(second).info["original_ref"] == order.ref
    crash(second)  # after the terminal transition, before any takeover

    third = env.start()
    notice = _notice(third)
    assert notice.status == bt.Order.Rejected and notice.info["error_code"] == NOT_FOUND
    assert notice.info["original_ref"] == order.ref
    assert notice.info["local_seq"] == order.info["local_seq"]
    third.take_over_restored_orders(env.strategy)
    assert env.state().pending.get(call.marker_id)["facts"]["taken_over_at_utc"]
    third.stop()

    fourth = env.start()
    assert fourth.get_restored_orders() == []  # never delivered twice


def test_an_earlier_trading_days_untaken_notice_is_not_redelivered(env):
    """Its day order ended with that day: reported then, not repeated on a later day."""
    env.init_flat()
    marker_id, _ = env.seed_marker("000000000504", trading_day=YESTERDAY, summary=_summary())
    state = env.state()
    assert state.pending.mark(marker_id, "TERMINAL", final_status=NOT_FOUND)
    broker = env.start()
    assert broker.get_restored_orders() == []
    assert "taken_over_at_utc" not in state.pending.get(marker_id)["facts"]


def _waiting_dispatching(env, order_ref="000000000601"):
    """A waiting order whose dispatch committed a marker, then the process died."""
    first = env.start(first_init=True)
    env.api.schedule.phase = TradingPhase.CLOSED
    env.api.schedule.next_window = window(T0 + HOUR, T0 + 3 * HOUR)
    order = first.buy(
        env.strategy, env.feed, 1, price=3500.0, exectype=bt.Order.Limit, offset="open"
    )
    crash(first)
    waiting_id = order.info["waiting_id"]
    assert env.state().waiting.transition(waiting_id, "WAITING", "DISPATCHING")
    # The dispatch's marker carries the full request summary, like any plain
    # order's: the waiting path alone tells the strategy (one notice).
    summary = _summary(bt_ref=order.ref, size=1.0, price=3500.0)
    env.seed_marker(order_ref, local_seq=order.info["local_seq"], bt_ref=order.ref, summary=summary)
    return order, waiting_id


def test_waiting_notice_is_redelivered_after_a_crash_until_taken_over(env, clock):
    order, waiting_id = _waiting_dispatching(env)
    broker = env.start()
    assert env.state().waiting.get(waiting_id)["status"] == "REJECTED"
    assert _notice(broker).info["error_code"] == WAITING_REASON
    crash(broker)  # the REJECTED transition is durable, the notice was never taken over

    again = env.start()
    notice = _notice(again)
    assert notice.status == bt.Order.Rejected and notice.info["error_code"] == WAITING_REASON
    assert notice.info["waiting_id"] == waiting_id and notice.info["original_ref"] == order.ref
    again.take_over_restored_orders(env.strategy)
    assert env.state().waiting.get(waiting_id)["facts"]["taken_over_at_utc"]
    clock["value"] = T0 + HOUR
    env.api.schedule.phase = TradingPhase.CONTINUOUS
    again.next()
    assert env.api.place_calls == []  # never re-sent
    crash(again)

    last = env.start()
    assert last.get_restored_orders() == []  # never delivered twice
    assert env.api.place_calls == []


def test_notice_of_a_return_gap_rejection_is_kept_until_recorded(env, monkeypatch):
    """Running: the in-process Rejected notification records the takeover."""
    broker = env.start(first_init=True, direct_return_gap_quiet_period=0.0)
    quiet(broker)
    rejected = _buy(env, broker)
    first_call = env.api.place_calls[-1]
    env.api.session_generation = 2
    broker.next()
    broker._direct_gap_due = 0.0
    broker._direct_return_gap_poll()
    broker.next()
    assert rejected.status == bt.Order.Rejected and rejected.info["error_code"] == NOT_FOUND
    assert env.state().pending.get(first_call.marker_id)["facts"]["taken_over_at_utc"]

    # A second one whose takeover could not be written before a crash.
    other = _buy(env, broker)
    second_call = env.api.place_calls[-1]
    monkeypatch.setattr(PendingCommandStore, "record_takeover", lambda self, marker_id: False)
    env.api.session_generation = 3
    broker.next()
    broker._direct_gap_due = 0.0
    broker._direct_return_gap_poll()
    broker.next()
    assert other.status == bt.Order.Rejected
    monkeypatch.undo()
    crash(broker)

    again = env.start()
    notice = _notice(again)  # only the one whose takeover was not recorded
    assert notice.info["marker_id"] == second_call.marker_id
    assert notice.info["original_ref"] == other.ref


# ---------------------------------------------------------------------------
# (c) same-day markers already UNKNOWN
# ---------------------------------------------------------------------------
def test_same_day_unknown_marker_absent_from_the_complete_query_is_not_found(env):
    env.init_flat()
    marker_id, _ = env.seed_marker("000000000701", status="UNKNOWN", summary=_summary())
    broker = env.start()
    marker = env.state().pending.get(marker_id)
    assert marker["status"] == "TERMINAL" and marker["facts"]["final_status"] == NOT_FOUND
    assert marker["resolution"]["kind"] == "complete_order_query"
    report = broker.get_direct_reconcile_report()
    assert report["unknown_markers"] == [] and report["not_found_at_venue"] == [marker_id]
    assert report["resolved_unknown_markers"] == [marker_id]
    assert broker.direct_writes_blocked() == {}
    assert _notice(broker).info["error_code"] == NOT_FOUND
    events = [r["event"] for r in read_audit(str(env.strategy_dir))]
    assert "pending_order_query_resolution" in events


def test_same_day_unknown_marker_of_a_working_order_is_restored(env):
    env.init_flat()
    marker_id, identity = env.seed_marker("000000000702", status="UNKNOWN")
    env.api.active_orders = [order_event(identity, "accepted", sys_id="7201", qty=2)]
    broker = env.start()
    marker = env.state().pending.get(marker_id)
    assert marker["status"] == "ACCEPTED" and marker["facts"]["order_sys_id"] == "7201"
    restored = _notice(broker)
    assert restored.status == bt.Order.Accepted and restored.size == 2
    assert broker.direct_writes_blocked() == {}
    assert broker.get_direct_reconcile_report()["foreign_working_orders"] == 0


def test_same_day_unknown_marker_of_a_filled_order_applies_its_fills(env):
    env.init_flat()
    marker_id, identity = env.seed_marker("000000000703", status="UNKNOWN")
    env.api.orders = [order_event(identity, "filled", sys_id="7301", filled=1.0)]
    env.api.trades = [trade_event("T1", sys_id="7301")]
    env.api.positions = [position("long", 1, 1, 0)]
    broker = env.start()
    marker = env.state().pending.get(marker_id)
    assert marker["status"] == "TERMINAL" and marker["facts"]["final_status"] == "filled"
    assert broker.get_direct_reconcile_report()["applied_missing_trades"] == 1
    assert broker.getposition(env.feed, side="long").size == 1
    assert broker.direct_writes_blocked() == {}


def test_unknown_marker_whose_resolution_cannot_be_written_stays_unknown(env, monkeypatch):
    env.init_flat()
    marker_id, identity = env.seed_marker("000000000705", status="UNKNOWN", summary=_summary())
    env.api.active_orders = [order_event(identity, "accepted", sys_id="7501")]
    monkeypatch.setattr(PendingCommandStore, "resolve_order_query", lambda *a, **k: False)
    broker = env.start()
    assert env.state().pending.get(marker_id)["status"] == "UNKNOWN"
    assert broker.direct_writes_blocked() == {SYMBOL: "pending_unknown"}
    report = broker.get_direct_reconcile_report()
    assert report["unknown_markers"] == [marker_id] and report["restored_orders"] == 0
    assert broker.get_restored_orders() == []


def test_same_day_unknown_marker_without_the_complete_order_list_stays_unknown(env):
    """Unchanged: an incomplete query proves nothing."""
    env.init_flat()
    marker_id, _ = env.seed_marker("000000000704", status="UNKNOWN", summary=_summary())
    read = env.api.direct_account_facts

    def without_order_list(exchange_name, **sections):
        return dataclasses.replace(read(exchange_name, **sections), orders=None)

    env.api.direct_account_facts = without_order_list
    broker = env.start()
    assert env.state().pending.get(marker_id)["status"] == "UNKNOWN"
    assert broker.direct_writes_blocked() == {SYMBOL: "pending_unknown"}
    assert broker.get_restored_orders() == []


# ---------------------------------------------------------------------------
# (d) client-order-id routes (OKX/Binance) keep today's recovery
# ---------------------------------------------------------------------------
def _client_identity(client_order_id):
    return NativeOrderIdentity(
        exchange_name=EXCHANGE,
        client_order_id=client_order_id,
        fields={"inst_id": SYMBOL, "trading_day": TODAY},
        session_generation=1,
    )


def test_client_order_id_route_keeps_todays_recovery(env):
    env.init_flat()
    absent, _ = env.seed_marker(
        "", identity=_client_identity("btabc0000000s1"), local_seq=1, summary=_summary()
    )
    unknown, _ = env.seed_marker(
        "",
        identity=_client_identity("btabc0000000s2"),
        local_seq=2,
        bt_ref=2,
        status="UNKNOWN",
        summary=_summary(),
    )
    working_identity = _client_identity("btabc0000000s3")
    env.seed_marker("", identity=working_identity, local_seq=3, bt_ref=3)
    # Filled 1 of 2 earlier; the venue's fill query no longer lists that fill.
    env.api.active_orders = [
        order_event(working_identity, "partially_filled", sys_id="OKX-9", qty=2, filled=1)
    ]
    env.api.positions = []
    broker = env.start(require_offset=False)
    state = env.state()
    marker = state.pending.get(absent)
    assert marker["status"] == "TERMINAL" and marker["facts"]["final_status"] == NOT_FOUND
    assert state.pending.get(unknown)["status"] == "UNKNOWN"
    assert broker.direct_writes_blocked() == {SYMBOL: "pending_unknown"}
    (restored,) = broker.get_restored_orders()  # the working order only, no notice
    assert restored.status == bt.Order.Accepted
    assert restored.size == 1 and restored.info["venue_filled_before"] == 1.0
    report = broker.get_direct_reconcile_report()
    assert report["not_found_at_venue"] == [absent] and report["unknown_markers"] == [unknown]
    assert "fill_gaps" not in report
