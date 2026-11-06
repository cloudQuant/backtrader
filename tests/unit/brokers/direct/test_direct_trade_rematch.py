"""A fill that arrives before its order return (decision 8 of the continuity analysis).

User decision 2026-11-06: "short buffer then re-match".  A trade return that
matches no own order is held for ``direct_trade_match_window`` seconds
(default 5) and re-matched after later order returns are processed; it is
applied exactly once.  Still unmatched when its window has passed (checked
after each event poll), at buffer overflow or at stop, it is handled as
before (not ours, never adopted) and counted in the reconcile report
(``unmatched_trade_returns``; ``trade_match_buffer`` has the counters).
Nothing held is applied after stop.

UNIT/FAKE: fake facade + real ``backtrader.live_state`` in ``tmp_path``; the
monotonic clock of the window is patched.
"""

import pytest

pytest.importorskip("bt_api_py", reason="direct mode needs the bt_api_py SDK DTOs")

import backtrader as bt
from backtrader.brokers import _btapi_direct_mode as direct_mode
from backtrader.brokers._btapi_direct_mode import DirectModeError
from bt_api_base.direct_write_protocol import DirectExecutionEvent, DirectExecutionEventKind

from ._fakes import EXCHANGE, SYMBOL, order_event, quiet, trade_event


@pytest.fixture
def now(monkeypatch):
    value = {"t": 1000.0}
    monkeypatch.setattr(direct_mode, "_monotonic", lambda: value["t"])
    return value


@pytest.fixture
def broker(env, now):
    started = env.start(first_init=True)
    quiet(started)
    return started


def _buy(env, broker, size=1):
    order = broker.buy(
        env.strategy, env.feed, size, price=3500.0, exectype=bt.Order.Limit, offset="open"
    )
    assert order.status == bt.Order.Submitted
    return order, env.api.place_calls[-1]


def _report(broker):
    return broker.get_direct_reconcile_report()


def test_order_return_one_second_after_the_fill_applies_it_exactly_once(env, broker, now):
    order, call = _buy(env, broker)
    env.api.push(trade_event("T1", sys_id="1001"))  # the fill overtakes its order return
    broker.next()
    assert order.status == bt.Order.Submitted and order.executed.size == 0
    assert broker.getposition(env.feed, side="long").size == 0
    assert _report(broker)["trade_match_buffer"]["pending"] == 1
    now["t"] += 1.0
    env.api.push(order_event(call.identity, "accepted", sys_id="1001"))
    broker.next()
    assert order.status == bt.Order.Completed and order.executed.size == 1
    assert broker.getposition(env.feed, side="long").size == 1
    env.api.push(trade_event("T1", sys_id="1001"))  # a repeated return of the same fill
    broker.next()
    now["t"] += 10.0
    broker.next()
    assert order.executed.size == 1
    assert broker.getposition(env.feed, side="long").size == 1
    report = _report(broker)
    assert report["trade_match_buffer"] == {
        "buffered": 1,
        "matched_late": 1,
        "expired": 0,
        "pending": 0,
    }
    assert "unmatched_trade_returns" not in report


def test_fill_and_order_return_in_one_poll_in_the_wrong_order(env, broker):
    order, call = _buy(env, broker, size=2)
    env.api.push(trade_event("T1", sys_id="1001"))
    env.api.push(order_event(call.identity, "accepted", sys_id="1001", qty=2))
    env.api.push(trade_event("T2", sys_id="1001"))
    broker.next()
    assert order.status == bt.Order.Completed and order.executed.size == 2
    assert _report(broker)["trade_match_buffer"]["matched_late"] == 1


def test_still_unmatched_after_the_window_is_not_ours(env, broker, now):
    order, call = _buy(env, broker)
    env.api.push(trade_event("T1", sys_id="1001"))
    broker.next()
    now["t"] += 4.9
    broker.next()
    assert _report(broker)["trade_match_buffer"]["pending"] == 1
    now["t"] += 0.2
    broker.next()
    report = _report(broker)
    assert report["trade_match_buffer"]["pending"] == 0
    unmatched = report["unmatched_trade_returns"]
    assert (unmatched["count"], unmatched["reasons"]) == (1, {"window_expired": 1})
    assert (unmatched["last"]["trade_id"], unmatched["last"]["symbol"]) == ("T1", SYMBOL)
    env.api.push(order_event(call.identity, "accepted", sys_id="1001"))
    broker.next()
    assert order.status == bt.Order.Accepted and order.executed.size == 0  # never adopted


def test_repeated_returns_of_a_held_fill_are_held_once(env, broker, now):
    order, call = _buy(env, broker)
    env.api.push(trade_event("T1", sys_id="1001"))
    env.api.push(trade_event("T1", sys_id="1001"))
    broker.next()
    env.api.push(trade_event("T1", sys_id="1001"))
    broker.next()
    assert _report(broker)["trade_match_buffer"]["buffered"] == 1
    env.api.push(order_event(call.identity, "accepted", sys_id="1001"))
    broker.next()
    assert order.executed.size == 1


def test_nothing_held_is_applied_after_stop(env, broker):
    order, _call = _buy(env, broker)
    env.api.auto_cancel_events = False  # the cancel stays unresolved
    env.api.push(trade_event("T1", sys_id="1001"))
    broker.next()
    broker.stop()
    assert order.executed.size == 0
    assert broker.long_positions[SYMBOL].size == 0
    assert broker._direct_trade_buffer == {}
    unmatched = _report(broker)["unmatched_trade_returns"]
    assert unmatched["reasons"] == {"stopped": 1}


def test_the_buffer_is_bounded(env, broker, monkeypatch):
    monkeypatch.setattr(direct_mode, "_MAX_BUFFERED_TRADES", 2)
    for index in range(3):
        env.api.push(trade_event(f"T{index}", sys_id=f"90{index}"))  # nobody's orders
    broker.next()
    report = _report(broker)
    assert report["trade_match_buffer"]["pending"] == 2
    assert report["unmatched_trade_returns"]["reasons"] == {"buffer_full": 1}
    assert report["unmatched_trade_returns"]["last"]["trade_id"] == "T0"


def test_zero_window_keeps_only_the_same_poll(env, now):
    broker = env.start(first_init=True, direct_trade_match_window=0)
    quiet(broker)
    order, call = _buy(env, broker)
    env.api.push(trade_event("T1", sys_id="1001"))
    env.api.push(order_event(call.identity, "accepted", sys_id="1001"))
    broker.next()
    assert order.executed.size == 1
    env.api.push(trade_event("T9", sys_id="9999"))
    broker.next()
    assert _report(broker)["unmatched_trade_returns"]["reasons"] == {"window_expired": 1}


def test_trade_without_identity_is_not_held(env, broker):
    event = DirectExecutionEvent(
        kind=DirectExecutionEventKind.TRADE,
        exchange_name=EXCHANGE,
        symbol=SYMBOL,
        identity=None,
        exchange_order_id=None,
        side="buy",
        offset="open",
        trade_id="T1",
        trade_price=3500.0,
        trade_qty=1.0,
    )
    env.api.push(event)
    broker.next()
    report = _report(broker)
    assert report["unmatched_trade_returns"]["reasons"] == {"no_identity": 1}
    assert report["trade_match_buffer"]["buffered"] == 0


def test_matched_fills_never_enter_the_buffer(env, broker):
    order, call = _buy(env, broker)
    env.api.push(order_event(call.identity, "accepted", sys_id="1001"))
    env.api.push(trade_event("T1", sys_id="1001"))
    broker.next()
    assert order.executed.size == 1
    assert "trade_match_buffer" not in _report(broker)


@pytest.mark.parametrize("window", [-1, float("nan"), float("inf"), True, "5", None])
def test_invalid_window_refuses_to_start(env, window):
    with pytest.raises(DirectModeError) as info:
        env.start(first_init=True, direct_trade_match_window=window)
    assert info.value.code == "direct_trade_match_window_invalid"
