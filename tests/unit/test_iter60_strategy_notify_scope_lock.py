"""Strategy ``notify_cashvalue``/``notify_fund`` are atomic with account-book binding.

Iteration 60 (R2-D): ``Strategy._notify`` produces the financial values and
delivers them to the Strategy and its analyzer trees while holding
``analyzers._strategy_scope.FINANCIAL_SCOPE_LOCK`` - the lock
``bind_account_book`` takes. A binding made by another thread during delivery
therefore waits until every callback of that delivery has returned; no
callback can observe a bound strategy while receiving the account totals
that were produced for the unbound one.
"""

from __future__ import annotations

import math
import threading

from backtrader.analyzers._strategy_scope import FINANCIAL_SCOPE_LOCK, bind_account_book
from tests.unit import test_iter60_scoped_financial_notifications as notifications


def _binder(strategy, view):
    bound = threading.Event()
    thread = threading.Thread(target=lambda: (bind_account_book(strategy, view), bound.set()))
    return thread, bound


def _record_binding(strategy, seen):
    def notify_cashvalue(cash, value):
        seen.append(("cashvalue", strategy.__dict__.get("account_book"), cash, value))

    def notify_fund(cash, value, fundvalue, shares):
        seen.append(("fund", strategy.__dict__.get("account_book"), cash, value))

    strategy.__dict__["notify_cashvalue"] = notify_cashvalue
    strategy.__dict__["notify_fund"] = notify_fund


def test_binding_during_value_production_waits_for_the_whole_delivery():
    strategy, broker, analyzer_calls, child_calls = notifications._make()
    seen = []
    _record_binding(strategy, seen)
    view = notifications._Book(1.0, 2.0)
    thread, bound = _binder(strategy, view)
    produce_value = broker.getvalue

    def getvalue():
        # The account total is being produced: a concurrent bind starts now.
        thread.start()
        assert not bound.wait(0.2)
        return produce_value()

    broker.getvalue = getvalue
    strategy._notify()
    # Every callback of this delivery saw the unbound strategy it was produced for.
    assert [(kind, book) for kind, book, *_ in seen] == [("cashvalue", None), ("fund", None)]
    assert seen[0][2:] == (7777.0, 9999.0)
    assert len(analyzer_calls) == 4 and len(child_calls) == 2
    thread.join(5)
    assert bound.is_set() and strategy.__dict__["account_book"] is view
    # The next delivery is strategy-scoped: no account totals reach the callbacks.
    broker.deny_reads = True
    seen.clear()
    strategy._notify()
    assert [book for _kind, book, *_ in seen] == [view, view]
    assert all(math.isnan(number) for number in seen[0][2:])


def test_binding_from_inside_a_callback_waits_until_analyzers_are_done():
    strategy, _broker, analyzer_calls, _child_calls = notifications._make()
    view = notifications._Book(1.0, 2.0)
    thread, bound = _binder(strategy, view)
    observed = []

    def notify_cashvalue(cash, value):
        thread.start()
        assert not bound.wait(0.2)
        observed.append(("strategy", cash))

    strategy.__dict__["notify_cashvalue"] = notify_cashvalue
    original = notifications._Analyzer.notify_cashvalue

    def analyzer_cashvalue(self, cash, value):
        observed.append((self.name, strategy.__dict__.get("account_book"), cash))
        original(self, cash, value)

    notifications._Analyzer.notify_cashvalue = analyzer_cashvalue
    try:
        strategy._notify()
    finally:
        notifications._Analyzer.notify_cashvalue = original
    assert observed[0] == ("strategy", 7777.0)
    assert all(book is None and cash == 7777.0 for _name, book, cash in observed[1:])
    assert {name for name, *_ in observed[1:]} == {"child", "primary", "slave"}
    thread.join(5)
    assert bound.is_set() and strategy.__dict__["account_book"] is view


def test_delivery_holds_the_shared_financial_scope_lock():
    strategy, _broker, _calls, _child = notifications._make()
    held = []

    def notify_cashvalue(cash, value):
        # The lock is reentrant: owned by this thread, unavailable to others.
        acquired = []
        other = threading.Thread(
            target=lambda: acquired.append(FINANCIAL_SCOPE_LOCK.acquire(timeout=0.1))
        )
        other.start()
        other.join(5)
        held.append(acquired == [False])

    strategy.__dict__["notify_cashvalue"] = notify_cashvalue
    strategy._notify()
    assert held == [True]
    assert FINANCIAL_SCOPE_LOCK.acquire(timeout=1)
    FINANCIAL_SCOPE_LOCK.release()
