"""Iteration 60, P0-2: every position entry point is strategy-scoped.

Shared account holds 5; strategy A's book owns 2 and strategy B's owns 3.
Every Strategy position query (by data, by name, collections, properties),
``close()``, ``order_target_size()`` and the percent sizer must see only the
strategy's own position; the explicit account-level API and an explicit other
Broker keep account semantics; per-side reads are refused; an unbound
strategy keeps plain Broker semantics (backtest compatibility).
"""

from __future__ import annotations

import itertools
from types import SimpleNamespace

import pytest

import backtrader as bt
from backtrader.metabase import OwnerContext
from backtrader.position import Position
from backtrader.sizers.percents_sizer import PercentSizer


class _Data:
    def __init__(self, name):
        self._name = name

    class _Close:
        def __getitem__(self, index):
            return 100.0

    close = _Close()


class _Book:
    """Strategy-owned positions keyed by data name."""

    def __init__(self, sizes):
        self.sizes = sizes

    def getposition(self, data):
        return Position(size=self.sizes.get(data._name, 0.0), price=0.0)


class _AccountBroker(bt.BrokerBase):
    """Account-wide Broker positions: 5 on X (A=2 + B=3)."""

    def __init__(self, sizes):
        super().__init__()
        self.sizes = sizes

    def getposition(self, data, side=None, **kwargs):
        return Position(size=self.sizes.get(data._name, 0.0), price=0.0)

    @property
    def positions(self):
        return {data: self.getposition(data) for data in self._datas}

    def getcash(self):
        return 1_000_000.0

    def getvalue(self, datas=None):
        return 1_000_000.0


class _Strategy(bt.Strategy):
    pass


X, Y = _Data("X"), _Data("Y")


def _make(book_sizes=None):
    broker = _AccountBroker({"X": 5.0, "Y": 0.0})
    broker._datas = [X, Y]
    cerebro = bt.Cerebro()
    cerebro.setbroker(broker)
    cerebro.stcount = itertools.count()
    cerebro.datas = [X, Y]
    cerebro.datasbyname = {"X": X, "Y": Y}
    with OwnerContext.set_owner(cerebro):
        strategy = _Strategy.__new__(_Strategy)
    strategy.datas = [X, Y]
    strategy.data = X
    if book_sizes is not None:
        strategy.account_book = _Book(book_sizes)
    orders = []
    strategy.__dict__["sell"] = lambda **kw: orders.append(("sell", kw["size"])) or "order"
    strategy.__dict__["buy"] = lambda **kw: orders.append(("buy", kw["size"])) or "order"
    return strategy, broker, orders


@pytest.fixture
def pair():
    a, _broker_a, orders_a = _make({"X": 2.0})
    b, _broker_b, orders_b = _make({"X": 3.0})
    return a, orders_a, b, orders_b


def test_every_query_entry_point_is_strategy_scoped(pair):
    a, _orders_a, b, _orders_b = pair
    for strategy, own in ((a, 2.0), (b, 3.0)):
        assert strategy.getposition(X).size == own
        assert strategy.getposition(X, strategy.broker).size == own
        assert strategy.position.size == own
        assert strategy.getpositionbyname("X").size == own
        assert strategy.positionbyname.size == own
        assert strategy.getpositions()[X].size == own
        assert strategy.positions[X].size == own
        assert strategy.getpositionsbyname()["X"].size == own
        assert strategy.positionsbyname["X"].size == own


def test_empty_strategy_position_is_zero_not_the_account(pair):
    a, *_ = pair
    assert a.getposition(Y).size == 0.0
    assert a.getpositionbyname("Y").size == 0.0
    assert a.getpositions()[Y].size == 0.0


def test_account_level_reads_are_explicit(pair):
    a, *_ = pair
    assert a.getaccountposition(X).size == 5.0
    assert a.getaccountpositions()[X].size == 5.0


def test_explicit_other_broker_keeps_its_semantics(pair):
    a, *_ = pair
    other = SimpleNamespace(
        getposition=lambda data, side=None, **kw: Position(size=9.0, price=0.0),
        positions={X: Position(size=9.0, price=0.0)},
    )
    assert a.getposition(X, other).size == 9.0
    assert a.getpositionbyname("X", other).size == 9.0
    assert a.getpositions(other)[X].size == 9.0


def test_per_side_reads_are_refused_on_every_scoped_entry(pair):
    a, *_ = pair
    with pytest.raises(ValueError, match="per-side"):
        a.getposition(X, side="long")
    with pytest.raises(ValueError, match="per-side"):
        a.getpositionbyname("X", side="long")


def test_close_uses_only_the_strategy_position(pair):
    a, orders_a, b, orders_b = pair
    assert a.close(data=X) == "order" and orders_a == [("sell", 2.0)]
    assert b.close(data=X) == "order" and orders_b == [("sell", 3.0)]


def test_close_cannot_exceed_the_strategy_position(pair):
    a, orders_a, *_ = pair
    # The account holds 5; A owns 2. Closing 5 would take B's 3.
    with pytest.raises(ValueError, match="exceeds the strategy-owned position"):
        a.close(data=X, size=5)
    assert orders_a == []
    assert a.close(data=X, size=1) == "order" and orders_a == [("sell", 1)]


def test_close_on_empty_strategy_position_does_nothing(pair):
    a, orders_a, *_ = pair
    assert a.close(data=Y) is None and orders_a == []
    with pytest.raises(ValueError, match="exceeds"):
        a.close(data=Y, size=1)


def test_order_target_size_targets_the_strategy_position(pair):
    a, orders_a, *_ = pair
    a.order_target_size(data=X, target=0)
    assert orders_a == [("sell", 2.0)]


def test_percent_sizer_reads_the_strategy_position(pair):
    a, *_ = pair
    sizer = PercentSizer()
    sizer.set(a, a.broker)
    assert sizer._getsizing(None, 1_000.0, X, False) == 2.0


def test_unbound_strategy_keeps_broker_semantics():
    strategy, _broker, orders = _make(None)
    assert strategy.getposition(X).size == 5.0
    assert strategy.getpositionbyname("X").size == 5.0
    assert strategy.getpositions()[X].size == 5.0
    assert strategy.close(data=X, size=5) == "order" and orders == [("sell", 5)]
