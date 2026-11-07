"""A place marker absent from a complete same-day order query (D63-38 a, 2026-11-07).

The order is not at the venue: the marker is resolved TERMINAL
``not_found_at_venue`` and the instrument stays unblocked, but nothing is ever
re-sent automatically.  A closed-market waiting order whose dispatch committed
such a marker ends REJECTED (``restart_not_found_at_venue``) and is handed to
its strategy as a restored, Rejected order; the strategy decides.  Every such
marker is listed in the reconcile report and logged.  Without the complete
order list the marker stays and blocks the instrument (unchanged).

UNIT/FAKE: fake facade, real ``backtrader.live_state`` in ``tmp_path``.
"""

import dataclasses
import datetime as dt
import logging

import pytest

pytest.importorskip("bt_api_py", reason="direct mode needs the bt_api_py SDK DTOs")

import backtrader as bt
from bt_api_base.trading_session_protocol import TradingPhase

from ._fakes import SYMBOL, T0, crash, drain, window

HOUR = dt.timedelta(hours=1)
REASON = "restart_not_found_at_venue"


def _waiting_dispatching(env, order_ref="000000000401"):
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
    marker_id, _identity = env.seed_marker(
        order_ref, local_seq=order.info["local_seq"], bt_ref=order.ref
    )
    return order, waiting_id, marker_id


def test_dispatching_waiting_order_not_found_ends_rejected_and_is_never_resent(env, clock):
    order, waiting_id, marker_id = _waiting_dispatching(env)

    broker = env.start()

    record = env.state().waiting.get(waiting_id)
    assert record["status"] == "REJECTED"  # terminal, persisted before notifying
    assert record["facts"]["reason"] == REASON and record["facts"]["marker_id"] == marker_id
    assert env.state().waiting.active() == []
    marker = env.state().pending.get(marker_id)
    assert marker["status"] == "TERMINAL"
    assert marker["facts"]["final_status"] == "not_found_at_venue"
    assert broker.get_direct_reconcile_report()["not_found_at_venue"] == [marker_id]
    assert broker.direct_writes_blocked() == {}  # the instrument is not blocked

    # Reported to the strategy like any restored order: Rejected, with the reason.
    (restored,) = broker.take_over_restored_orders(env.strategy)
    assert restored.status == bt.Order.Rejected
    assert restored.info["restored"] is True and restored.info["waiting_session"] is True
    assert restored.info["error_code"] == REASON
    assert restored.info["original_ref"] == order.ref
    assert restored.info["local_seq"] == order.info["local_seq"]
    (note,) = drain(broker)
    assert note.status == bt.Order.Rejected and note.info["error_code"] == REASON

    # Inside the original target session it is still never dispatched again.
    clock["value"] = T0 + HOUR
    env.api.schedule.phase = TradingPhase.CONTINUOUS
    broker.next()
    broker.next()
    assert env.api.place_calls == []
    # The strategy may place a new order itself (nothing blocks it).
    again = broker.buy(
        env.strategy, env.feed, 1, price=3500.0, exectype=bt.Order.Limit, offset="open"
    )
    assert again.status == bt.Order.Submitted and len(env.api.place_calls) == 1


def test_waiting_order_adopted_when_its_feed_starts_is_rejected_too(env, clock):
    _order, waiting_id, _marker_id = _waiting_dispatching(env, "000000000402")
    env.store._data_feeds = [env.other_feed]
    broker = env.start()
    assert env.state().waiting.get(waiting_id)["status"] == "DISPATCHING"  # not adopted yet
    env.store._data_feeds = [env.feed, env.other_feed]
    broker.data_started(env.feed)
    assert env.state().waiting.get(waiting_id)["status"] == "REJECTED"
    (restored,) = broker.get_restored_orders()
    assert restored.status == bt.Order.Rejected and restored.info["error_code"] == REASON


def test_regular_marker_not_found_is_reported_and_logged(env, bt_caplog):
    env.init_flat()
    first, _ = env.seed_marker("000000000411", status="DISPATCHED")
    second, _ = env.seed_marker("000000000412", local_seq=2, bt_ref=2, status="PREPARED")
    with bt_caplog.at_level(logging.WARNING):
        broker = env.start()
    report = broker.get_direct_reconcile_report()
    assert sorted(report["not_found_at_venue"]) == sorted([first, second])
    assert report["unknown_markers"] == []
    assert broker.direct_writes_blocked() == {}
    logged = [
        r.getMessage()
        for r in bt_caplog.records
        if r.levelno == logging.WARNING and "not found at the venue" in r.getMessage()
    ]
    assert len(logged) == 2
    assert all(first in line or second in line for line in logged)
    assert all("simnow" not in line for line in logged)  # no account reference text


def test_incomplete_order_query_keeps_the_marker_and_blocks_the_symbol(env):
    """Unchanged guard: without the complete same-day order list nothing is concluded."""
    env.init_flat()
    marker_id, _ = env.seed_marker("000000000421", status="DISPATCHED")
    read = env.api.direct_account_facts

    def without_order_list(exchange_name, **sections):
        return dataclasses.replace(read(exchange_name, **sections), orders=None)

    env.api.direct_account_facts = without_order_list
    broker = env.start()
    assert env.state().pending.get(marker_id)["status"] == "DISPATCHED"
    report = broker.get_direct_reconcile_report()
    assert report["unknown_markers"] == [marker_id] and report["not_found_at_venue"] == []
    assert broker.direct_writes_blocked() == {SYMBOL: "pending_unverified"}
