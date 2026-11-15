"""The status file's Broker facts (iteration 66, §5.2 B2): non-blocking, finite.

``backtrader.live_trading.direct_run_facts`` runs on the heartbeat thread.  It
must never wait for the strategy thread's lock (a deadlock would freeze the
heartbeat and make a healthy process look unresponsive) and it must never
invent a zero count when it cannot read: ``None`` means UNKNOWN.

Evidence: UNIT/FAKE.
"""

from __future__ import annotations

import threading

import pytest

pytest.importorskip("bt_api_py", reason="direct mode needs the bt_api_py SDK DTOs")

import backtrader as bt
from backtrader.live_trading import direct_run_facts

from ._fakes import SYMBOL, order_event


def _accepted(env, broker, sys_id: str):
    order = broker.buy(
        env.strategy, env.feed, 1, price=3500.0, exectype=bt.Order.Limit, offset="open"
    )
    call = env.api.place_calls[-1]
    env.api.push(order_event(call.identity, "accepted", sys_id=sys_id, qty=1))
    broker.next()
    assert order.status == bt.Order.Accepted
    return order


def test_publishable_facts_of_a_running_direct_broker(env):
    broker = env.start(first_init=True)
    _accepted(env, broker, "7301")
    facts = direct_run_facts(broker)
    assert facts.active_order_count == 1
    assert facts.write_block_reasons == ()  # proven: nothing blocks writes
    assert facts.unknown_unresolved_count == 0
    assert facts.last_error_code is None

    broker._direct_global_block = "settlement_unconfirmed"
    blocked = direct_run_facts(broker)
    assert blocked.write_block_reasons == ("settlement_unconfirmed",)
    assert blocked.active_order_count == 1


def test_a_contended_lock_yields_unknown_not_a_zero(env):
    broker = env.start(first_init=True)
    _accepted(env, broker, "7302")
    holding = threading.Event()
    release = threading.Event()

    def hold():
        with broker._direct_lock:
            holding.set()
            release.wait(5.0)

    thread = threading.Thread(target=hold)
    thread.start()
    try:
        assert holding.wait(5.0)
        facts = direct_run_facts(broker)
        assert facts.active_order_count is None
        assert facts.unknown_unresolved_count is None
        assert facts.write_block_reasons is None
    finally:
        release.set()
        thread.join(5.0)
    assert direct_run_facts(broker).active_order_count == 1


def test_a_broker_that_is_not_running_yields_unknown(env):
    broker = env.broker()
    facts = direct_run_facts(broker)
    assert facts.active_order_count is None and facts.write_block_reasons is None


def test_unresolved_states_are_counted(env):
    broker = env.start(first_init=True)
    order = broker.buy(
        env.strategy, env.feed, 1, price=3500.0, exectype=bt.Order.Limit, offset="open"
    )
    call = env.api.place_calls[-1]
    env.api.push(order_event(call.identity, "accepted", sys_id="7303", qty=1))
    broker.next()
    meta = broker._direct_meta[order.ref]
    meta["unknown"] = True
    broker._direct_fill_gaps["marker-x"] = {"state": "unknown", "symbol": SYMBOL}
    broker._direct_settlement = {"status": "manual_required", "trading_day": "20261105"}
    facts = direct_run_facts(broker)
    assert facts.unknown_unresolved_count == 3
    assert facts.active_order_count == 1
