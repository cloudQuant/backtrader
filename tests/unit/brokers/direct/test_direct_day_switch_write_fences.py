"""Writes around a pending trading-day switch (R-3; D62-19/29/30).

* Stop versus the facts poller: no settlement confirmation starts after
  ``stop()`` began; one already committed is waited for (bounded), recorded,
  and only then the run lock is released.  Past the bound the run lock stays
  with the write and the marker stays as committed.
* Cancels while a switch is pending: an order whose identity's trading day is
  not the provider's current one is never cancelled automatically (its
  day-scoped CTP ids may be reused on the new day's session); stop reports it
  unresolved with its original identity.  Same-day orders and routes without
  venue offsets are unaffected.
* An order in a trusted closure during a pending switch becomes a durable
  local waiting order (D62-30); the queue stays held until the switch is
  verified.

UNIT/FAKE: fake facade and schedule, real ``backtrader.live_state`` in
``tmp_path``; the facts poller is driven on its own thread by the test.
"""

import datetime as dt
import threading
import time

import pytest

pytest.importorskip("bt_api_py", reason="direct mode needs the bt_api_py SDK DTOs")

import backtrader as bt
from backtrader import live_state as ls
from bt_api_base.direct_write_protocol import SettlementStatus
from bt_api_base.trading_session_protocol import TradingPhase

from ._fakes import (
    EXCHANGE,
    OTHER_SYMBOL,
    SYMBOL,
    T0,
    TODAY,
    TOMORROW,
    order_event,
    quiet,
    run_day_switch,
    window,
)

PENDING = "trading_day_switch_pending"
OLD_DAY = "previous_day_pending_unknown"
NEW_DAY = dt.date(2026, 11, 6)
HOUR = dt.timedelta(hours=1)


def _buy(env, broker, size=1, feed=None, price=3500.0):
    return broker.buy(
        env.strategy, feed or env.feed, size, price=price, exectype=bt.Order.Limit, offset="open"
    )


def _working(env, broker, sys_id, feed=None, price=3500.0, symbol=SYMBOL):
    order = _buy(env, broker, feed=feed, price=price)
    call = env.api.place_calls[-1]
    env.api.push(order_event(call.identity, "accepted", sys_id=sys_id, symbol=symbol))
    broker.next()
    assert order.status == bt.Order.Accepted
    return order, call


def _started(env, **params):
    broker = env.start(first_init=True, **params)
    quiet(broker)
    env.api.schedule.trading_day = NEW_DAY  # the venue calendar agrees with the new day
    return broker


def _detect_new_day(env, broker):
    """The provider moves to TOMORROW; one funds read reaches the strategy thread."""
    env.api.trading_day = TOMORROW
    facts = env.api.direct_account_facts(EXCHANGE, positions=False, active_orders=False)
    broker._direct_facts_results.append(("funds", facts))
    broker.next()
    assert broker.direct_writes_blocked() == {"*": PENDING}


def _poll_once(broker):
    """One facts-poller verification attempt, on its own thread."""
    broker._direct_day_switch_due = 0.0
    thread = threading.Thread(target=broker._direct_day_switch_poll, daemon=True)
    thread.start()
    return thread


def _run_lock_free(env) -> bool:
    try:
        lock = env.state().acquire_run_lock()
    except ls.LiveStateLocked:
        return False
    lock.release()
    return True


def _settlement_markers(env):
    return [m for m in env.state().pending.active() if m["operation"] == "settlement_confirm"]


# ---------------------------------------------------------------------------
# stop versus the facts poller's settlement step
# ---------------------------------------------------------------------------
def test_stop_during_the_switch_reads_starts_no_settlement(env):
    broker = _started(env)
    entered, release = threading.Event(), threading.Event()
    read = env.api.direct_account_facts

    def slow_switch_read(exchange_name, **sections):
        if sections.get("all_orders"):
            entered.set()
            release.wait(10)
        return read(exchange_name, **sections)

    env.api.direct_account_facts = slow_switch_read
    _detect_new_day(env, broker)
    poller = _poll_once(broker)
    assert entered.wait(5)
    calls = len(env.api.settlement_calls)

    summary = broker.stop()
    assert summary["status"] == "STOPPED" and "write_in_flight" not in summary
    assert broker._direct_run_lock is None  # nothing was in flight
    release.set()
    poller.join(5)
    assert not poller.is_alive()
    assert len(env.api.settlement_calls) == calls  # never called after stop() began
    kind, payload = broker._direct_facts_results[-1]
    assert kind == "day_switch" and payload["reason"] == "broker_stopping"
    assert payload["settlement"] is None


def test_stop_during_the_settlement_readback_refuses_the_commit(env):
    """The SDK reads the status first; the host refuses the later commit, so nothing is sent."""
    broker = _started(env)
    reading, release = threading.Event(), threading.Event()
    confirm = env.api.ensure_settlement_confirmed

    def readback_then_confirm(*args, **kwargs):
        reading.set()
        release.wait(10)  # the provider's settlement status readback
        return confirm(*args, **kwargs)  # commits through the host port, then sends

    env.api.ensure_settlement_confirmed = readback_then_confirm
    _detect_new_day(env, broker)
    poller = _poll_once(broker)
    assert reading.wait(5)
    started = time.monotonic()
    summary = broker.stop()
    assert time.monotonic() - started < 2.0  # nothing committed: not waited for
    assert summary["status"] == "STOPPED" and broker._direct_run_lock is None
    release.set()
    poller.join(5)
    call = env.api.settlement_calls[-1]
    assert call.trading_day == TOMORROW and call.marker_id is None  # refused: not sent
    assert _settlement_markers(env) == []


@pytest.mark.parametrize(
    "result, status, recorded",
    [
        (SettlementStatus.CONFIRMED, "TERMINAL", ("final_status", "confirmed")),
        (SettlementStatus.UNKNOWN, "UNKNOWN", ("reason", "settlement_outcome_unknown")),
    ],
)
def test_stop_waits_for_a_committed_settlement_and_records_it(env, result, status, recorded):
    broker = _started(env)
    env.api.settlement_result = result
    committed, release = threading.Event(), threading.Event()
    lock_free_while_in_flight = []
    confirm = env.api.ensure_settlement_confirmed

    def confirm_in_flight(*args, **kwargs):
        outcome = confirm(*args, **kwargs)  # marker committed, confirmation sent
        committed.set()
        release.wait(10)  # waiting for the venue's answer
        lock_free_while_in_flight.append(_run_lock_free(env))
        return outcome

    env.api.ensure_settlement_confirmed = confirm_in_flight
    _detect_new_day(env, broker)
    poller = _poll_once(broker)
    assert committed.wait(5)
    marker_id = env.api.settlement_calls[-1].marker_id
    assert env.state().pending.get(marker_id)["status"] == "PREPARED"
    threading.Timer(0.3, release.set).start()

    summary = broker.stop()
    assert lock_free_while_in_flight == [False]  # never released under the write
    marker = env.state().pending.get(marker_id)
    assert marker["status"] == status  # recorded before stop() returned
    assert marker["facts"][recorded[0]] == recorded[1]
    assert summary["status"] == "STOPPED" and "write_in_flight" not in summary
    assert broker._direct_run_lock is None and _run_lock_free(env)
    poller.join(5)
    assert len(env.api.settlement_calls) == 2  # startup + the one switch confirmation

    if status == "TERMINAL":  # an UNKNOWN marker is the next start's reconciliation
        env.api.ensure_settlement_confirmed = confirm
        assert env.start().direct_writes_blocked() == {}


def test_stop_past_its_bound_keeps_the_run_lock_until_the_write_ends(env):
    broker = _started(env, direct_stop_write_timeout=0.2)
    committed, release, ended = threading.Event(), threading.Event(), threading.Event()
    confirm = env.api.ensure_settlement_confirmed

    def confirm_in_flight(*args, **kwargs):
        outcome = confirm(*args, **kwargs)
        committed.set()
        release.wait(10)
        ended.set()
        return outcome

    env.api.ensure_settlement_confirmed = confirm_in_flight
    _detect_new_day(env, broker)
    poller = _poll_once(broker)
    assert committed.wait(5)
    marker_id = env.api.settlement_calls[-1].marker_id

    started = time.monotonic()
    summary = broker.stop()
    assert time.monotonic() - started < 2.0  # bounded
    assert not ended.is_set()
    assert summary["status"] == "STOPPED_WITH_WRITE_IN_FLIGHT"
    assert summary["write_in_flight"] == {
        "operation": "settlement_confirm",
        "marker_id": marker_id,
        "run_lock_held": True,
    }
    assert env.state().pending.get(marker_id)["status"] == "PREPARED"  # not faked
    assert broker._direct_active() is False
    assert not _run_lock_free(env)  # no other owner while the write may reach the venue
    with pytest.raises(ls.LiveStateLocked):
        env.start()

    release.set()
    poller.join(5)
    marker = env.state().pending.get(marker_id)
    assert marker["status"] == "TERMINAL" and marker["facts"]["final_status"] == "confirmed"
    assert _run_lock_free(env)  # released by the write's end
    assert broker.get_shutdown_summary()["status"] == "STOPPED_WITH_WRITE_IN_FLIGHT"
    env.api.ensure_settlement_confirmed = confirm
    assert env.start().direct_writes_blocked() == {}


def test_stop_records_a_finished_settlement_the_strategy_thread_never_applied(env):
    broker = _started(env)
    _detect_new_day(env, broker)
    broker._direct_day_switch_due = 0.0
    broker._direct_day_switch_poll()  # attempt done; its result waits for ``next``
    marker_id = env.api.settlement_calls[-1].marker_id
    assert env.state().pending.get(marker_id)["status"] == "PREPARED"
    assert broker.stop()["status"] == "STOPPED"
    marker = env.state().pending.get(marker_id)
    assert marker["status"] == "TERMINAL" and marker["facts"]["final_status"] == "confirmed"


# ---------------------------------------------------------------------------
# cancels while a switch is pending
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("detected_by", ["facts_read", "stop_probe"])
def test_stop_during_a_pending_switch_sends_no_old_day_cancel(env, detected_by):
    broker = _started(env)
    working, call = _working(env, broker, "7201")
    if detected_by == "facts_read":
        _detect_new_day(env, broker)
    else:
        env.api.trading_day = TOMORROW  # unnoticed until stop() probes the session

    summary = broker.stop()
    assert env.api.cancel_calls == []
    assert summary["status"] == "STOPPED_WITH_WORKING_ORDERS"
    assert summary["cancelled_requested"] == 0 and summary["unresolved_working_orders"] == 1
    assert summary["cancel_refused"] == {OLD_DAY: 1}
    assert working.alive() and working.info["cancel_error"] == OLD_DAY
    marker = env.state().pending.get(call.marker_id)
    assert marker["status"] == "ACCEPTED"  # its original identity, nothing faked
    assert marker["native_identity"]["trading_day"] == TODAY
    again = env.start()  # the new day's session cannot query it: UNKNOWN, blocked
    assert again.direct_writes_blocked() == {SYMBOL: "pending_unknown"}
    assert env.state().pending.get(call.marker_id)["status"] == "UNKNOWN"


def test_same_day_orders_are_cancelled_during_a_pending_switch(env):
    broker = _started(env)
    old, _old_call = _working(env, broker, "7301")
    send = env.api.make_order

    def provider_moves_before_the_send(*args, **kwargs):
        env.api.trading_day = TOMORROW  # the session moved after the precheck
        return send(*args, **kwargs)

    env.api.make_order = provider_moves_before_the_send
    new, new_call = _working(
        env, broker, "1", feed=env.other_feed, price=3300.0, symbol=OTHER_SYMBOL
    )
    assert new_call.identity.fields["trading_day"] == TOMORROW
    _detect_new_day(env, broker)
    env.api.auto_cancel_events = True

    broker.cancel(old)
    assert env.api.cancel_calls == [] and old.info["cancel_error"] == OLD_DAY
    broker.cancel(new)
    (cancel,) = env.api.cancel_calls
    assert cancel.target.fields["trading_day"] == TOMORROW
    summary = broker.stop()
    assert len(env.api.cancel_calls) == 1  # the old-day order took no write
    assert new.status == bt.Order.Canceled and old.alive()
    assert summary["cancelled_requested"] == 1 and summary["unresolved_working_orders"] == 1
    assert summary["cancel_refused"] == {OLD_DAY: 1}


def test_unreadable_provider_day_during_a_pending_switch_refuses_the_cancel(env):
    broker = _started(env)
    working, _call = _working(env, broker, "7401")
    _detect_new_day(env, broker)
    env.api.provider.trading_day = lambda: None  # the session day is not readable now
    broker.cancel(working)
    assert env.api.cancel_calls == []
    assert working.info["cancel_error"] == PENDING


def test_route_without_offsets_cancels_across_the_day(env):
    """OKX/Binance: the trading day is the UTC date; GTC orders span days."""
    broker = env.start(first_init=True, require_offset=False)
    quiet(broker)
    resting = broker.buy(env.strategy, env.feed, 1, price=3500.0, exectype=bt.Order.Limit)
    call = env.api.place_calls[-1]
    env.api.push(order_event(call.identity, "accepted", sys_id="9901"))
    broker.next()
    env.api.trading_day = TOMORROW
    env.api.auto_cancel_events = True
    summary = broker.stop()
    (cancel,) = env.api.cancel_calls
    assert cancel.target.fields["trading_day"] == TODAY
    assert summary["status"] == "STOPPED" and resting.status == bt.Order.Canceled
    assert "cancel_refused" not in summary


# ---------------------------------------------------------------------------
# orders in a trusted closure during a pending switch (D62-30)
# ---------------------------------------------------------------------------
def _closed(env):
    env.api.schedule.phase = TradingPhase.CLOSED
    env.api.schedule.next_window = window(T0 + HOUR, T0 + 3 * HOUR)


def test_closure_order_during_a_pending_switch_waits_then_dispatches(env, clock):
    broker = _started(env)
    _closed(env)
    env.api.trading_day = TOMORROW  # re-login for the night session, still closed
    order = _buy(env, broker)
    assert env.api.place_calls == []
    assert order.status == bt.Order.Submitted and order.info["waiting_session"] is True
    assert env.state().waiting.get(order.info["waiting_id"])["status"] == "WAITING"
    assert broker.direct_writes_blocked() == {"*": PENDING}

    clock["value"] = T0 + HOUR  # its window opens while the switch is still pending
    env.api.schedule.phase = TradingPhase.CONTINUOUS
    broker.next()
    assert env.api.place_calls == [] and order.status == bt.Order.Submitted
    assert env.state().waiting.get(order.info["waiting_id"])["status"] == "WAITING"

    assert run_day_switch(broker)["status"] == "completed"  # then the normal rules
    (call,) = env.api.place_calls
    assert call.summary["local_seq"] == order.info["local_seq"]
    assert call.identity.fields["trading_day"] == TOMORROW


@pytest.mark.parametrize("closed, waiting_orders", [(False, True), (True, False)])
def test_pending_switch_still_refuses_orders_that_would_not_wait(env, closed, waiting_orders):
    broker = _started(env, waiting_orders=waiting_orders)
    if closed:
        _closed(env)
    env.api.trading_day = TOMORROW
    refused = _buy(env, broker)
    assert refused.status == bt.Order.Rejected and refused.info["error_code"] == PENDING
    assert env.api.place_calls == [] and env.state().waiting.active() == []


def test_a_switch_seen_by_the_dispatch_check_holds_the_waiting_order(env, clock):
    broker = _started(env)
    _closed(env)
    waiting = _buy(env, broker)
    assert waiting.info["waiting_session"] is True
    clock["value"] = T0 + HOUR
    env.api.schedule.phase = TradingPhase.CONTINUOUS
    schedule = env.api.schedule
    session_state = schedule.session_state

    def provider_moves(instrument_id, at_utc):
        env.api.trading_day = TOMORROW  # between the hold check and the precheck
        return session_state(instrument_id, at_utc)

    schedule.session_state = provider_moves
    broker.next()
    assert env.api.place_calls == []
    assert waiting.status == bt.Order.Submitted  # held, not rejected
    assert env.state().waiting.get(waiting.info["waiting_id"])["status"] == "WAITING"
    assert broker.direct_writes_blocked() == {"*": PENDING}
    schedule.session_state = session_state
    run_day_switch(broker)
    (call,) = env.api.place_calls
    assert call.identity.fields["trading_day"] == TOMORROW
