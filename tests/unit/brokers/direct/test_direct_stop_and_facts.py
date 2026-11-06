"""Normal stop (D62-19) and funds refresh / position audit (D62-06a/06b).

UNIT/FAKE: fake facade + real ``backtrader.live_state`` in ``tmp_path``.
"""

import datetime as dt
import time

import pytest

pytest.importorskip("bt_api_py", reason="direct mode needs the bt_api_py SDK DTOs")

import backtrader as bt
from backtrader import live_state as ls
from bt_api_base.trading_session_protocol import TradingPhase

from ._fakes import (
    EXCHANGE,
    SYMBOL,
    T0,
    TOMORROW,
    balance,
    native_identity,
    order_event,
    position,
    quiet,
    run_day_switch,
    trade_event,
    window,
)


def _buy(env, broker, size=1, **kwargs):
    kwargs.setdefault("offset", "open")
    return broker.buy(env.strategy, env.feed, size, price=3500.0, exectype=bt.Order.Limit, **kwargs)


def _working(env, broker, sys_id, size=1):
    order = _buy(env, broker, size)
    call = env.api.place_calls[-1]
    env.api.push(order_event(call.identity, "accepted", sys_id=sys_id, qty=size))
    broker.next()
    assert order.status == bt.Order.Accepted
    return order, call


def _filled(env, broker, sys_id, size=1, trade_prefix="T"):
    order, call = _working(env, broker, sys_id, size)
    env.api.push(trade_event(f"{trade_prefix}{sys_id}", sys_id=sys_id, qty=size))
    broker.next()
    assert order.status == bt.Order.Completed
    return order, call


# ---------------------------------------------------------------------------
# stop
# ---------------------------------------------------------------------------
def test_stop_cancels_only_own_working_orders_and_never_flattens(env, clock):
    env.init_flat()
    foreign = native_identity("000000000999")
    env.api.active_orders = [order_event(foreign, "accepted", sys_id="9999", side="sell")]
    broker = env.start()
    assert broker.get_direct_reconcile_report()["foreign_working_orders"] == 1
    _filled(env, broker, "7001", size=2)
    working, working_call = _working(env, broker, "7002")
    env.api.schedule.phase = TradingPhase.CLOSED
    env.api.schedule.next_window = window(T0 + dt.timedelta(hours=1), T0 + dt.timedelta(hours=3))
    waiting = _buy(env, broker)
    assert waiting.info["waiting_session"] is True
    # Venue open again (the waiting order still waits for its window): any
    # closing order created by stop() would be dispatched and seen below.
    env.api.schedule.phase = TradingPhase.CONTINUOUS
    env.api.auto_cancel_events = True
    places = len(env.api.place_calls)

    summary = broker.stop()

    assert summary == {
        "status": "STOPPED",
        "cancelled_requested": 1,
        "unresolved_working_orders": 0,
        "waiting_orders_kept": 1,
    }
    (cancel,) = env.api.cancel_calls  # never the foreign order
    assert cancel.target.client_order_id == working_call.identity.client_order_id
    assert len(env.api.place_calls) == places  # no closing order was submitted
    assert working.status == bt.Order.Canceled
    assert waiting.alive() and waiting.status == bt.Order.Submitted
    assert env.state().waiting.get(waiting.info["waiting_id"])["status"] == "WAITING"
    snapshot = env.state().snapshot.read()
    assert snapshot["positions"][SYMBOL]["long"]["total"] == 2  # position kept
    assert broker._direct_active() is False
    assert env.store.stop_calls >= 2  # init_flat stop + this stop
    env.state().acquire_run_lock().release()


def test_stop_wait_is_bounded_and_keeps_unresolved_identities(env):
    broker = env.start(first_init=True, stop_cancel_timeout=0.3)
    working, call = _working(env, broker, "7101")
    env.api.cancel_sent = None  # cancel outcome unknown, and no return arrives
    started = time.monotonic()
    summary = broker.stop()
    assert time.monotonic() - started < 2.0
    assert summary["status"] == "STOPPED_WITH_WORKING_ORDERS"
    assert summary["unresolved_working_orders"] == 1
    assert working.alive()
    state = env.state()
    assert state.pending.get(call.marker_id)["status"] == "ACCEPTED"  # identity kept
    cancel_marker = state.pending.get(env.api.cancel_calls[0].marker_id)
    assert cancel_marker["status"] == "DISPATCHED"
    assert cancel_marker["facts"]["send_outcome"] == "unknown"
    state.acquire_run_lock().release()


def test_stop_without_orders_writes_snapshot_and_releases_lock(env):
    broker = env.start(first_init=True)
    _filled(env, broker, "7201")
    path = env.strategy_dir / "logs" / "current_position.yaml"
    path.unlink()
    summary = broker.stop()
    assert summary["status"] == "STOPPED" and summary["cancelled_requested"] == 0
    assert env.api.cancel_calls == []
    assert env.state().snapshot.read()["positions"][SYMBOL]["long"]["total"] == 1
    with ls.StrategyStateDir(str(env.strategy_dir)).acquire_run_lock():
        pass


# ---------------------------------------------------------------------------
# funds refresh and position audit (fed through the result queue)
# ---------------------------------------------------------------------------
def test_funds_result_updates_cash_and_value(env):
    broker = env.start(first_init=True)
    assert broker.getcash() == 900_000.0 and broker.getvalue() == 1_000_000.0
    env.api.balance = balance(total=1_234_567.0, available=1_000_001.0)
    facts = env.api.direct_account_facts(EXCHANGE, positions=False, active_orders=False)
    broker._direct_facts_results.append(("funds", facts))
    broker.next()
    assert broker.getcash() == 1_000_001.0
    assert broker.getvalue() == 1_234_567.0
    assert broker.direct_writes_blocked() == {}


def test_audit_mismatch_blocks_the_symbol(env):
    broker = env.start(first_init=True)
    _filled(env, broker, "8001")
    env.api.positions = [position("long", 2, 2, 0)]
    broker._direct_facts_results.append(("audit", env.api.direct_account_facts(EXCHANGE)))
    broker.next()
    assert broker.direct_writes_blocked() == {SYMBOL: "position_audit_mismatch"}
    assert _buy(env, broker).info["error_code"] == "position_audit_mismatch"


def test_audit_match_adopts_the_venue_split(env):
    broker = env.start(first_init=True)
    _filled(env, broker, "8101", size=2)
    env.api.positions = [position("long", 2, 1, 1)]
    broker._direct_facts_results.append(("audit", env.api.direct_account_facts(EXCHANGE)))
    broker.next()
    assert broker.direct_writes_blocked() == {}
    view = broker.get_closable(env.feed, "long")
    assert view["today"] == 1 and view["yesterday"] == 1


def test_audit_skips_symbols_with_in_flight_orders(env):
    broker = env.start(first_init=True)
    _working(env, broker, "8201")
    env.api.positions = [position("long", 1, 1, 0)]  # the fill may be racing the audit
    broker._direct_facts_results.append(("audit", env.api.direct_account_facts(EXCHANGE)))
    broker.next()
    assert broker.direct_writes_blocked() == {}


def test_audit_on_a_new_trading_day_freezes_then_adopts_the_venue_split(env):
    """R-3: the audit only detects the new day; the verified switch rolls it."""
    broker = env.start(first_init=True)
    quiet(broker)
    _filled(env, broker, "8301", size=2)
    assert broker.get_closable(env.feed, "long")["today"] == 2
    env.api.trading_day = TOMORROW
    env.api.positions = [position("long", 2, 0, 2)]
    broker._direct_facts_results.append(("audit", env.api.direct_account_facts(EXCHANGE)))
    broker.next()
    assert broker._direct_trading_day != TOMORROW  # nothing adopted before verification
    assert broker.direct_writes_blocked() == {"*": "trading_day_switch_pending"}
    run_day_switch(broker)
    assert broker._direct_trading_day == TOMORROW
    view = broker.get_closable(env.feed, "long")
    assert view["today"] == 0 and view["yesterday"] == 2
    assert broker.direct_writes_blocked() == {}
    snapshot = env.state().snapshot.read()
    assert snapshot["trading_day"] == TOMORROW
    assert snapshot["positions"][SYMBOL]["long"] == {"total": 2, "today": 0, "yesterday": 2}


def test_new_trading_day_with_a_venue_total_mismatch_blocks_the_symbol(env):
    broker = env.start(first_init=True)
    quiet(broker)
    _filled(env, broker, "8401", size=1)
    env.api.trading_day = TOMORROW
    env.api.positions = []  # mismatch on the new day: switched, then blocked
    broker._direct_facts_results.append(("audit", env.api.direct_account_facts(EXCHANGE)))
    broker.next()
    run_day_switch(broker)
    assert broker._direct_trading_day == TOMORROW
    assert broker.direct_writes_blocked() == {SYMBOL: "trading_day_switch_position_mismatch"}


def test_background_poller_reads_funds_only_and_queues_the_result(env):
    broker = env.start(
        first_init=True, direct_funds_refresh_interval=0.01, direct_position_audit_interval=0
    )
    env.api.balance = balance(total=5.0, available=4.0)  # first poll is >= 1 s later
    deadline = time.monotonic() + 5.0
    while broker.get_direct_refresh_counts()["funds"] < 1 and time.monotonic() < deadline:
        time.sleep(0.05)
    assert broker.get_direct_refresh_counts()["funds"] >= 1
    assert broker.get_direct_refresh_counts()["audit"] == 0
    polled = env.api.facts_calls[1]
    assert polled["positions"] is False and polled["active_orders"] is False
    assert polled["balance"] is True and polled["trades"] is False
    assert broker.getcash() == 900_000.0  # applied only on the strategy thread
    broker.next()
    assert broker.getcash() == 4.0 and broker.getvalue() == 5.0


def test_refresh_counts_include_the_provider_catalog_counters_when_available(env):
    broker = env.start(first_init=True)
    assert "instrument_catalog" not in broker.get_direct_refresh_counts()
    provider = env.api.direct_writes().provider("CTP___FUTURE")
    provider.instrument_catalog_counters = lambda: {"full_queries": 1, "memory_hits": 4}
    counts = broker.get_direct_refresh_counts()
    assert counts["instrument_catalog"] == {"full_queries": 1, "memory_hits": 4}
    assert counts["funds"] == 0  # the framework counts are unchanged
