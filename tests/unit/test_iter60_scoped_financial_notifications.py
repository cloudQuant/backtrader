"""Bound strategy notifications must never broadcast account-wide values."""

import itertools
import math
from types import SimpleNamespace

import pytest

import backtrader as bt
from backtrader.analyzer import Analyzer
from backtrader.metabase import OwnerContext
from backtrader.service.service_strategy_account_book import ServiceStrategyAccountBookError


class _RecordingStrategy(bt.Strategy):
    def notify_cashvalue(self, cash, value):
        self.calls.append(("cashvalue", cash, value))

    def notify_fund(self, cash, value, fundvalue, shares):
        self.calls.append(("fund", cash, value, fundvalue, shares))


class _Book:
    def __init__(self, cash, value):
        self.cash = cash
        self.value = value

    def getcash(self):
        if isinstance(self.cash, Exception):
            raise self.cash
        return self.cash

    def getvalue(self):
        if isinstance(self.value, Exception):
            raise self.value
        return self.value


class _Analyzer:
    _notify_cashvalue = Analyzer._notify_cashvalue
    _notify_fund = Analyzer._notify_fund
    _notify_financial_tree = Analyzer._notify_financial_tree

    def __init__(self, name, calls, children=()):
        self.name = name
        self.calls = calls
        self._children = list(children)

    def notify_cashvalue(self, cash, value):
        self.calls.append((self.name, "cashvalue", cash, value))

    def notify_fund(self, cash, value, fundvalue, shares):
        self.calls.append((self.name, "fund", cash, value, fundvalue, shares))


class _Broker(bt.BrokerBase):
    def __init__(self, *, deny_reads):
        super().__init__()
        self.deny_reads = deny_reads
        self.reads = []

    def _read(self, name, value):
        self.reads.append(name)
        if self.deny_reads:
            raise AssertionError("bound strategy accessed broker account value")
        return value

    def getcash(self):
        return self._read("cash", 7777.0)

    def getvalue(self):
        return self._read("value", 9999.0)

    @property
    def fundvalue(self):
        return self._read("fundvalue", 8888.0)

    @property
    def fundshares(self):
        return self._read("fundshares", 4444.0)


def _make(book=None, *, quicknotify=False):
    broker = _Broker(deny_reads=book is not None)
    cerebro = bt.Cerebro()
    cerebro.setbroker(broker)
    cerebro.stcount = itertools.count()
    cerebro.datas = [SimpleNamespace(_name="X")]
    with OwnerContext.set_owner(cerebro):
        strategy = _RecordingStrategy.__new__(_RecordingStrategy)
    strategy.calls = []
    strategy._quicknotify = quicknotify
    strategy._orderspending = []
    strategy._tradespending = []
    strategy._notify_cashvalue_default = False
    strategy._notify_fund_default = False
    child_calls, all_calls = [], []
    child = _Analyzer("child", child_calls)
    primary = _Analyzer("primary", all_calls, [child])
    slave = _Analyzer("slave", all_calls)
    strategy._all_analyzers_cache = [primary, slave]
    if book is not None:
        strategy.account_book = book
    return strategy, broker, all_calls, child_calls


def test_bound_a_b_callbacks_use_each_strategy_and_never_account_values():
    for cash, value in ((100.0, 200.0), (300.0, 400.0)):
        strategy, broker, calls, child_calls = _make(_Book(cash, value))
        strategy._notify()
        assert broker.reads == []
        assert all(math.isnan(number) for number in strategy.calls[0][1:])
        assert all(math.isnan(number) for number in strategy.calls[1][1:])
        assert [call[:2] for call in calls] == [
            ("primary", "cashvalue"), ("primary", "fund"),
            ("slave", "cashvalue"), ("slave", "fund"),
        ]
        assert [call[:2] for call in child_calls] == [
            ("child", "cashvalue"), ("child", "fund")
        ]
        assert all(math.isnan(number) for number in calls[0][2:])
        assert all(math.isnan(number) for number in child_calls[0][2:])
        assert all(math.isnan(number) for number in calls[1][2:])
        assert strategy.strategy_financial_unavailable == {
            "cash": "STRATEGY_CASH_CURRENCY_REQUIRED",
            "value": "STRATEGY_VALUE_UNAVAILABLE",
            "fundvalue": "STRATEGY_FUND_VALUE_UNAVAILABLE",
            "fundshares": "STRATEGY_FUND_SHARES_UNAVAILABLE",
        }


def test_unavailable_strategy_amounts_are_nan_with_finite_reasons():
    book = _Book(
        ServiceStrategyAccountBookError("STRATEGY_CASH_CURRENCY_REQUIRED"),
        ServiceStrategyAccountBookError("STRATEGY_VALUE_UNAVAILABLE"),
    )
    strategy, broker, calls, _ = _make(book)
    strategy._notify()
    assert broker.reads == []
    assert all(math.isnan(number) for number in strategy.calls[0][1:])
    assert all(math.isnan(number) for number in calls[1][2:])
    assert strategy.strategy_financial_unavailable == {
        "cash": "STRATEGY_CASH_CURRENCY_REQUIRED",
        "value": "STRATEGY_VALUE_UNAVAILABLE",
        "fundvalue": "STRATEGY_FUND_VALUE_UNAVAILABLE",
        "fundshares": "STRATEGY_FUND_SHARES_UNAVAILABLE",
    }
    strategy.strategy_financial_unavailable.clear()
    assert len(strategy.strategy_financial_unavailable) == 4


def test_callback_errors_still_propagate():
    strategy, broker, _, _ = _make(_Book(100, 200))
    def callback(cash, value):
        raise RuntimeError("callback failed")

    strategy.notify_cashvalue = callback
    with pytest.raises(RuntimeError, match="callback failed"):
        strategy._notify()
    assert broker.reads == []


@pytest.mark.parametrize("transition", ["unbound_to_bound", "bound_to_unbound", "book_a_to_b"])
def test_strategy_callback_binding_change_stops_subsequent_delivery(transition):
    first = None if transition == "unbound_to_bound" else _Book(100, 200)
    replacement = None if transition == "bound_to_unbound" else _Book(300, 400)
    strategy, broker, calls, child_calls = _make(first)

    def rebind(cash, value):
        strategy.account_book = replacement

    strategy.notify_cashvalue = rebind
    with pytest.raises(RuntimeError, match="STRATEGY_FINANCIAL_SCOPE_CHANGED"):
        strategy._notify()
    assert strategy.calls == []
    assert calls == [] and child_calls == []
    if first is not None:
        assert broker.reads == []


def test_analyzer_binding_change_stops_next_analyzer_and_fund_delivery():
    strategy, broker, calls, _ = _make()
    first, second = strategy._all_analyzers_cache

    def rebind(cash, value):
        strategy.account_book = _Book(100, 200)

    first.notify_cashvalue = rebind
    with pytest.raises(RuntimeError, match="STRATEGY_FINANCIAL_SCOPE_CHANGED"):
        strategy._notify()
    assert not any(call[0] == "slave" for call in calls)
    assert not any(call[1] == "fund" for call in calls)


def test_unbound_strategy_preserves_account_callbacks_and_order():
    strategy, broker, calls, child_calls = _make()
    strategy._notify()
    assert broker.reads == ["cash", "value", "fundvalue", "fundshares"]
    assert strategy.calls == [
        ("cashvalue", 7777.0, 9999.0),
        ("fund", 7777.0, 9999.0, 8888.0, 4444.0),
    ]
    assert calls[0][2:] == (7777.0, 9999.0)
    assert child_calls[1][2:] == (7777.0, 9999.0, 8888.0, 4444.0)


def test_quick_order_notification_does_not_emit_financial_values():
    strategy, broker, calls, _ = _make(_Book(1, 2), quicknotify=True)
    strategy.notify_order = lambda order: None
    strategy._notify_order_to_observers = lambda order: None
    strategy._all_analyzers_cache = []
    order = SimpleNamespace(exectype=0, Historical=1, histnotify=False, info={})
    strategy._notify(qorders=[order], qtrades=[])
    assert strategy.calls == [] and calls == [] and broker.reads == []


@pytest.mark.parametrize("fail_callback", [False, True])
def test_recovery_receipt_ack_and_callback_failure_semantics(fail_callback):
    strategy, broker, _, _ = _make(_Book(100, 200))
    strategy._all_analyzers_cache = []
    observed, acknowledged, released = [], [], []
    strategy.notify_order = observed.append
    strategy._notify_order_to_observers = lambda order: None
    broker.acknowledge_service_execution_recovery_receipt = acknowledged.append
    broker.release_service_execution_recovery_receipt = released.append
    order = SimpleNamespace(
        exectype=0, Historical=1, histnotify=False,
        info={"service_execution_recovery_receipt_id": "receipt-1"},
    )
    strategy._orderspending = [order]
    if fail_callback:
        def fail(cash, value):
            raise RuntimeError("callback failed")

        strategy.notify_cashvalue = fail
        with pytest.raises(RuntimeError, match="callback failed"):
            strategy._notify()
        assert acknowledged == [] and released == ["receipt-1"]
    else:
        strategy._notify()
        assert acknowledged == ["receipt-1"] and released == []
    assert observed == [order]
    assert broker.reads == []
