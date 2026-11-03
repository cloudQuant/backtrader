"""Iteration 60 (acceptance report G5, direct mode): ledger events survive a restart.

A ledger-bound Strategy receives its own SDK ledger events at least once via
``bind_direct_strategy_ledger(..., event_cursor_path=...)`` ->
``Strategy.notify_ledger_event``. The cursor is the SDK
``SqliteEventCursorStore``; a crash before it is saved redelivers the same
event (same ``event_id``). Product path: real ``BtApiBroker`` + SDK ledger.
"""

from __future__ import annotations

import itertools

import pytest

pytest.importorskip("bt_api_py.strategy_event_feed")

import backtrader as bt  # noqa: E402
from backtrader.brokers._btapi_strategy_events import StrategyLedgerEventError  # noqa: E402
from backtrader.brokers.btapibroker import BtApiBroker  # noqa: E402
from backtrader.metabase import OwnerContext  # noqa: E402

from tests.integration import test_iter60_direct_strategy_account_book as base  # noqa: E402


class _Recording(base._IdentifiedStrategy):
    def notify_ledger_event(self, event):
        crash_on = self.__dict__.get("crash_on")
        if crash_on is not None and event.action == crash_on:
            self.__dict__["crash_on"] = None
            raise RuntimeError("process crashed inside the hook")
        self.__dict__.setdefault("received", []).append(event)


def _strategy(broker, data, ref):
    cerebro = bt.Cerebro()
    cerebro.setbroker(broker)
    cerebro.stcount = itertools.count()
    cerebro.datas = [data]
    cerebro.datasbyname = {base.INSTRUMENT: data}
    with OwnerContext.set_owner(cerebro):
        strategy = _Recording.__new__(_Recording, strategy_ref=ref, account_ref=base.ACCOUNT)
    strategy.datas = [data]
    strategy.data = data
    return strategy


@pytest.fixture
def env(tmp_path):
    ledger = base._ledger(tmp_path / "ledger.sqlite3")
    base._seed(ledger, "seed-a", "strategy-a", "2")
    base._seed(ledger, "seed-b", "strategy-b", "3")
    handoffs = []

    def broker():
        # One owner process holds the host owner lock; its Brokers share it.
        item = BtApiBroker(store=base._Store())
        if handoffs:
            item.bind_account_owner(handoffs[0], "direct")
        else:
            handoffs.append(base._owner(item, tmp_path / "owner.sqlite3"))
        return item

    try:
        yield ledger, broker, tmp_path / "events-a.sqlite3", base._data()
    finally:
        for handoff in handoffs:
            handoff.close()
        ledger.close()


def _actions(strategy):
    return [(event.intent_id, event.action) for event in strategy.__dict__.get("received", [])]


def test_pending_events_are_delivered_at_bind_and_only_the_strategys_own(env):
    ledger, broker, cursor, data = env
    item = broker()
    a = _strategy(item, data, "strategy-a")
    item.bind_direct_strategy_ledger(a, ledger, unreconciled=True, event_cursor_path=cursor)
    assert _actions(a) == [("seed-a", "RESERVE"), ("seed-a", "EXECUTION")]
    assert all(event.strategy_ref == "strategy-a" for event in a.received)


def test_order_lifecycle_events_follow_ledger_updates(env):
    ledger, broker, cursor, data = env
    item = broker()
    a = _strategy(item, data, "strategy-a")
    item.bind_direct_strategy_ledger(a, ledger, unreconciled=True, event_cursor_path=cursor)
    order = a.close(data=data, price=1500.0, exectype=bt.Order.Limit)
    base._fill(item, order, 2)
    intent = order.info["strategy_ledger_intent_id"]
    assert (intent, "EXECUTION") in _actions(a)
    assert item.deliver_strategy_ledger_events(a) == 0  # nothing pending, nothing repeated


def test_crash_before_the_cursor_commit_redelivers_the_same_event(env):
    ledger, broker, cursor, data = env
    first = broker()
    a = _strategy(first, data, "strategy-a")
    a.__dict__["crash_on"] = "EXECUTION"
    with pytest.raises(RuntimeError, match="crashed"):
        first.bind_direct_strategy_ledger(a, ledger, unreconciled=True, event_cursor_path=cursor)
    delivered = [event.event_id for event in a.received]
    assert _actions(a) == [("seed-a", "RESERVE")]
    first.close_strategy_ledger_events()

    # Restart: a new Broker and Strategy on the same ledger and cursor file.
    restarted = broker()
    a2 = _strategy(restarted, data, "strategy-a")
    restarted.bind_direct_strategy_ledger(a2, ledger, unreconciled=True, event_cursor_path=cursor)
    assert _actions(a2) == [("seed-a", "EXECUTION")]  # RESERVE is not repeated
    replayed = a2.received[0].event_id
    assert replayed not in delivered
    third = broker()
    a3 = _strategy(third, data, "strategy-a")
    third.bind_direct_strategy_ledger(a3, ledger, unreconciled=True, event_cursor_path=cursor)
    assert _actions(a3) == []  # everything committed now


def test_hook_failure_in_order_processing_is_retried_not_lost(env):
    ledger, broker, cursor, data = env
    item = broker()
    a = _strategy(item, data, "strategy-a")
    item.bind_direct_strategy_ledger(a, ledger, unreconciled=True, event_cursor_path=cursor)
    a.__dict__["crash_on"] = "EXECUTION"
    order = a.close(data=data, price=1500.0, exectype=bt.Order.Limit)
    base._fill(item, order, 2)  # the hook raises: logged, cursor kept
    intent = order.info["strategy_ledger_intent_id"]
    assert (intent, "EXECUTION") not in _actions(a)
    assert item._trading_enabled is not False  # a hook error never disables trading
    item.deliver_strategy_ledger_events(a)
    assert (intent, "EXECUTION") in _actions(a)


def test_cursor_from_another_ledger_generation_requires_resync(env, tmp_path):
    ledger, broker, cursor, data = env
    item = broker()
    a = _strategy(item, data, "strategy-a")
    item.bind_direct_strategy_ledger(a, ledger, unreconciled=True, event_cursor_path=cursor)
    item.close_strategy_ledger_events()
    rebuilt = base._ledger(tmp_path / "rebuilt.sqlite3")
    try:
        base._seed(rebuilt, "seed-a", "strategy-a", "2")
        other = broker()  # same account owner; one coordination store per host
        a2 = _strategy(other, data, "strategy-a")
        with pytest.raises(StrategyLedgerEventError) as info:
            other.bind_direct_strategy_ledger(
                a2, rebuilt, unreconciled=True, event_cursor_path=cursor
            )
        assert info.value.code == "RESYNC_REQUIRED"
        assert _actions(a2) == []
    finally:
        rebuilt.close()


def test_without_a_cursor_path_no_events_are_delivered(env):
    ledger, broker, _cursor, data = env
    item = broker()
    a = _strategy(item, data, "strategy-a")
    item.bind_direct_strategy_ledger(a, ledger, unreconciled=True)
    assert _actions(a) == [] and item.deliver_strategy_ledger_events() == 0
