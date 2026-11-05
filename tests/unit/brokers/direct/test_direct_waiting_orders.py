"""Orders waiting for the next trading session (D62-30/31/34/35/36, plan 5.3c).

UNIT/FAKE: fake facade and schedule, controlled clock, real ``backtrader.live_state``.
"""

import datetime as dt

import pytest

pytest.importorskip("bt_api_py", reason="direct mode needs the bt_api_py SDK DTOs")

import backtrader as bt
from bt_api_base.trading_session_protocol import TradingPhase

from ._fakes import (
    order_event,
    not_live,
    SYMBOL,
    T0,
    crash,
    drain,
    last_status,
    not_qualified,
    position,
    qualified,
    snap,
    window,
)

HOUR = dt.timedelta(hours=1)


def _closed(env, start=T0 + HOUR, end=T0 + 3 * HOUR):
    env.api.schedule.phase = TradingPhase.CLOSED
    env.api.schedule.next_window = window(start, end)


def _buy(env, broker, **kwargs):
    kwargs.setdefault("offset", "open")
    return broker.buy(env.strategy, env.feed, 1, price=3500.0, exectype=bt.Order.Limit, **kwargs)


def _open(env, clock, at):
    clock["value"] = at
    env.api.schedule.phase = TradingPhase.CONTINUOUS


def _seqs(env):
    return [call.summary["local_seq"] for call in env.api.place_calls]


def test_closed_session_order_is_persisted_and_not_sent(env, clock):
    broker = env.start(first_init=True)
    _closed(env)
    not_qualified(env.feed, "SOURCE_STALE")  # no fresh ticks while closed: still waits
    order = _buy(env, broker, valid=bt.Order.DAY)
    assert order.status == bt.Order.Submitted
    assert order.info["waiting_session"] is True
    record = env.state().waiting.get(order.info["waiting_id"])
    assert record["status"] == "WAITING"
    assert record["local_seq"] == order.info["local_seq"] == 1
    assert record["bt_ref"] == order.ref
    assert record["offset"] == "open" and record["exectype"] == "Limit"
    assert record["price"] == 3500.0
    assert record["valid_intent"] == {"kind": "day", "value": None}
    assert record["target_session"] == {
        "trading_day": "20261106",
        "continuous_start_utc": "2026-11-05T08:00:00.000000Z",
        "session_end_utc": "2026-11-05T10:00:00.000000Z",
    }
    assert env.api.place_calls == []
    assert last_status(drain(broker)) == ["Submitted"]


def test_no_dispatch_before_window_or_during_auction(env, clock):
    broker = env.start(first_init=True)
    _closed(env)
    order = _buy(env, broker)
    broker.next()
    clock["value"] = T0 + HOUR - dt.timedelta(seconds=1)
    env.api.schedule.phase = TradingPhase.CONTINUOUS  # even if the calendar says so
    broker.next()
    assert env.api.place_calls == []

    clock["value"] = T0 + HOUR
    env.api.schedule.phase = TradingPhase.AUCTION
    broker.next()
    assert env.api.place_calls == []

    env.api.schedule.phase = TradingPhase.CONTINUOUS
    not_qualified(env.feed)
    broker.next()
    assert env.api.place_calls == []  # needs qualified real-time target data

    qualified(env.feed)
    broker.next()
    (call,) = env.api.place_calls
    assert call.summary["local_seq"] == order.info["local_seq"]
    assert order.status == bt.Order.Submitted
    record = env.state().waiting.get(order.info["waiting_id"])
    assert record["status"] == "DISPATCHED" and record["facts"]["marker_id"] == call.marker_id
    broker.next()
    assert len(env.api.place_calls) == 1


def test_waiting_orders_dispatch_fifo_by_local_seq(env, clock):
    broker = env.start(first_init=True)
    _closed(env, start=T0 + 2 * HOUR, end=T0 + 4 * HOUR)
    first = _buy(env, broker)
    _closed(env, start=T0 + HOUR, end=T0 + 4 * HOUR)
    second = _buy(env, broker)
    assert first.info["local_seq"] < second.info["local_seq"]

    _open(env, clock, T0 + HOUR + HOUR / 2)
    broker.next()
    assert env.api.place_calls == []  # the later order may not overtake the earlier one

    _open(env, clock, T0 + 2 * HOUR)
    broker.next()
    assert _seqs(env) == [first.info["local_seq"], second.info["local_seq"]]


def test_waiting_order_expires_after_its_session_without_blocking_later_ones(env, clock):
    broker = env.start(first_init=True)
    _closed(env, start=T0 + HOUR, end=T0 + 2 * HOUR)
    expired = _buy(env, broker)
    _closed(env, start=T0 + HOUR, end=T0 + 5 * HOUR)
    later = _buy(env, broker)
    drain(broker)

    clock["value"] = T0 + HOUR
    env.api.schedule.phase = TradingPhase.AUCTION
    broker.next()
    _open(env, clock, T0 + 2 * HOUR)
    broker.next()
    assert expired.status == bt.Order.Expired
    assert not expired.alive()
    record = env.state().waiting.get(expired.info["waiting_id"])
    assert record["status"] == "EXPIRED"
    assert record["facts"]["reason"] == "target_session_ended"
    assert _seqs(env) == [later.info["local_seq"]]
    statuses = [(n.ref, bt.Order.Status[n.status]) for n in drain(broker)]
    assert (expired.ref, "Expired") in statuses
    broker.next()
    assert len(env.api.place_calls) == 1


def test_strategy_cancel_of_a_waiting_order_is_local(env, clock):
    broker = env.start(first_init=True)
    _closed(env)
    order = _buy(env, broker)
    drain(broker)
    broker.cancel(order)
    assert order.status == bt.Order.Canceled
    assert env.api.cancel_calls == [] and env.api.place_calls == []
    record = env.state().waiting.get(order.info["waiting_id"])
    assert record["status"] == "CANCELLED" and record["facts"]["reason"] == "strategy_cancel"
    assert last_status(drain(broker)) == ["Canceled"]
    _open(env, clock, T0 + HOUR)
    broker.next()
    assert env.api.place_calls == []


def test_market_closed_without_waiting_orders_is_refused(env, clock):
    broker = env.start(first_init=True, waiting_orders=False)
    _closed(env)
    assert _buy(env, broker).info["error_code"] == "market_closed"


def test_closed_without_a_known_next_session_is_refused(env, clock):
    broker = env.start(first_init=True)
    _closed(env)
    env.api.schedule.next_window = None
    assert _buy(env, broker).info["error_code"] == "target_session_unknown"


def test_precheck_failure_at_dispatch_rejects_the_waiting_order(env, clock):
    broker = env.start(first_init=True)
    _closed(env)
    order = _buy(env, broker)
    broker._direct_blocked[SYMBOL] = "position_audit_mismatch"
    _open(env, clock, T0 + HOUR)
    broker.next()
    assert order.status == bt.Order.Rejected
    assert order.info["error_code"] == "position_audit_mismatch"
    assert env.state().waiting.get(order.info["waiting_id"])["status"] == "REJECTED"
    assert env.api.place_calls == []


def test_waiting_full_close_is_dispatched_not_frozen_against_itself(env, clock):
    env.init_flat()
    env.write_snapshot({SYMBOL: snap(long=(1, 0, 1))})
    env.api.positions = [position("long", 1, 0, 1)]
    broker = env.start()
    _closed(env)
    close = broker.sell(
        env.strategy, env.feed, 1, price=3500.0, exectype=bt.Order.Limit, offset="close_yesterday"
    )
    assert close.info.get("waiting_session") is True, close.info.get("error_code")
    _open(env, clock, T0 + HOUR)
    broker.next()
    assert len(env.api.place_calls) == 1
    assert env.api.place_calls[0].request.offset == "close_yesterday"


# ---------------------------------------------------------------------------
# restart
# ---------------------------------------------------------------------------
def test_restart_restores_waiting_orders_as_restored_orders(env, clock):
    first = env.start(first_init=True)
    _closed(env)
    original = _buy(env, first, offset="open")
    crash(first)

    broker = env.start()
    (restored,) = broker.get_restored_orders()
    assert restored.status == bt.Order.Submitted
    assert restored.info["restored"] is True and restored.info["waiting_session"] is True
    assert restored.info["original_ref"] == original.ref
    assert restored.info["local_seq"] == original.info["local_seq"]
    assert restored.info["offset"] == "open" and restored.price == 3500.0
    assert _buy(env, broker).info["error_code"] == "restored_orders_not_taken_over"

    _open(env, clock, T0 + HOUR)
    broker.next()
    assert env.api.place_calls == []  # not before the strategy took it over

    broker.take_over_restored_orders(env.strategy)
    broker.next()
    assert _seqs(env) == [original.info["local_seq"]]
    record = env.state().waiting.get(original.info["waiting_id"])
    assert record["status"] == "DISPATCHED"


def test_restart_dispatching_with_committed_marker_becomes_dispatched(env, clock):
    first = env.start(first_init=True)
    _closed(env)
    order = _buy(env, first)
    crash(first)
    state = env.state()
    waiting_id = order.info["waiting_id"]
    assert state.waiting.transition(waiting_id, "WAITING", "DISPATCHING")
    marker_id, identity = env.seed_marker(
        "000000000301", local_seq=order.info["local_seq"], bt_ref=order.ref
    )
    # The venue holds the order (it was sent before the crash): terminal there.
    env.api.orders.append(order_event(identity, "filled", filled=1.0))

    broker = env.start()
    record = env.state().waiting.get(waiting_id)
    assert record["status"] == "DISPATCHED"
    assert record["facts"]["marker_id"] == marker_id
    assert record["facts"]["reason"] == "restart_marker_found"
    assert broker.get_restored_orders() == []


def test_restart_dispatching_marker_proven_unsent_waits_again(env, clock):
    """A committed marker absent from the complete same-day order list was never sent."""
    first = env.start(first_init=True)
    _closed(env)
    order = _buy(env, first)
    crash(first)
    waiting_id = order.info["waiting_id"]
    assert env.state().waiting.transition(waiting_id, "WAITING", "DISPATCHING")
    env.seed_marker("000000000302", local_seq=order.info["local_seq"], bt_ref=order.ref)

    broker = env.start()
    record = env.state().waiting.get(waiting_id)
    assert record["status"] == "WAITING"
    assert record["facts"]["reason"] == "restart_proven_unsent"
    restored = broker.get_restored_orders()
    assert len(restored) == 1 and restored[0].info["waiting_session"] is True


def test_restart_dispatching_without_marker_returns_to_waiting(env, clock):
    first = env.start(first_init=True)
    _closed(env)
    order = _buy(env, first)
    crash(first)
    waiting_id = order.info["waiting_id"]
    assert env.state().waiting.transition(waiting_id, "WAITING", "DISPATCHING")

    broker = env.start()
    record = env.state().waiting.get(waiting_id)
    assert record["status"] == "WAITING"
    assert record["facts"]["reason"] == "restart_not_committed"
    (restored,) = broker.get_restored_orders()
    assert restored.info["waiting_id"] == waiting_id


def test_waiting_record_without_feed_is_adopted_when_the_feed_starts(env, clock):
    first = env.start(first_init=True)
    _closed(env)
    order = _buy(env, first)
    crash(first)
    env.store._data_feeds = [env.other_feed]
    broker = env.start()
    assert broker.get_restored_orders() == []
    env.store._data_feeds = [env.feed, env.other_feed]
    broker.data_started(env.feed)
    (restored,) = broker.get_restored_orders()
    assert restored.info["waiting_id"] == order.info["waiting_id"]


def test_trusted_closure_queues_even_when_the_feed_is_not_live(env, clock):
    """5.3c: a real-time feed during a trusted closure waits; no LIVE/fresh quote needed now."""
    broker = env.start(first_init=True)
    _closed(env)
    not_live(env.feed)  # quiet market: never reached LIVE since the process started
    order = _buy(env, broker)
    assert order.status == bt.Order.Submitted
    assert order.info["waiting_session"] is True
    assert env.api.place_calls == []


def test_historical_warmup_is_refused_even_during_a_closure(env, clock):
    """D62-15a: orders from historical bars are refused, closure or not."""
    broker = env.start(first_init=True)
    _closed(env)
    env.feed.historical_warmup_active = lambda: True
    order = _buy(env, broker)
    assert order.status == bt.Order.Rejected
    assert order.info["error_code"] == "target_feed_warming_up"
    assert env.state().waiting.waiting() == []
    assert env.api.place_calls == []
