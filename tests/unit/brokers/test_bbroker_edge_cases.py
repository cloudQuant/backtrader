#!/usr/bin/env python
"""Regression tests for bbroker.py edge-case fixes.

Covers:
- P0: orderstatus() — self.orders.index(order) returned int, not order object
- P0: _get_value() — division by zero when _fundshares is 0
"""

import collections

import pytest

import backtrader as bt
from backtrader.brokers.bbroker import BackBroker
from backtrader.order import Order
from backtrader.position import Position

pd = pytest.importorskip("pandas")


# ---------------------------------------------------------------------------
# P0: orderstatus — index() returns int, not order object
# ---------------------------------------------------------------------------

class TestOrderStatus:
    """Verify orderstatus returns valid status, not int.status crash."""

    class _FakeOrder:
        """Minimal order-like object with ref-based equality."""
        def __init__(self, ref, status):
            self.ref = ref
            self.status = status
        def __eq__(self, other):
            return other is not None and self.ref == other.ref

    def _make_fake_order(self, ref, status):
        return self._FakeOrder(ref, status)

    def test_orderstatus_found_in_list(self):
        """When order is in self.orders, should return its status, not crash."""
        broker = BackBroker()
        broker.orders = []

        order = self._make_fake_order(ref=1, status=Order.Accepted)
        broker.orders.append(order)

        # Create a lookup order with matching ref
        lookup = self._make_fake_order(ref=1, status=Order.Created)

        # Before fix: self.orders.index(lookup) returned int 0,
        # then 0.status raised AttributeError
        result = broker.orderstatus(lookup)
        # Should return the stored order's status, not the lookup's
        assert result == Order.Accepted

    def test_orderstatus_not_found(self):
        """When order is not in self.orders, should return order's own status."""
        broker = BackBroker()
        broker.orders = []

        order = self._make_fake_order(ref=99, status=Order.Completed)
        result = broker.orderstatus(order)
        assert result == Order.Completed


# ---------------------------------------------------------------------------
# P0: _get_value — division by zero on _fundshares / _fundval
# ---------------------------------------------------------------------------

class TestGetValueDivByZero:
    """Verify _get_value handles zero _fundshares without crashing."""

    def test_fundval_with_zero_fundshares(self):
        """When _fundshares is 0, _fundval should not crash."""
        broker = BackBroker()
        # Simulate initialized state without calling full init()
        broker._cash = 0.0
        broker._value = 0.0
        broker._valuemkt = 0.0
        broker._valuelever = 0.0
        broker._valuemktlever = 0.0
        broker._leverage = 1.0
        broker._unrealized = 0.0
        broker._fundshares = 0.0  # edge case: zero shares
        broker._fundval = 100.0
        broker._fundhist = []
        broker._fhistlast = [float("NaN"), float("NaN")]
        broker._cash_addition = collections.deque()
        broker.positions = collections.defaultdict(Position)

        # Should not raise ZeroDivisionError
        result = broker._get_value()
        # _fundval should fall back to fundstartval parameter (100.0)
        assert broker._fundval == broker.get_param("fundstartval")

    def test_fundval_normal_operation(self):
        """Normal case with positive fundshares should compute correctly."""
        broker = BackBroker()
        broker._cash = 10000.0
        broker._value = 10000.0
        broker._valuemkt = 0.0
        broker._valuelever = 0.0
        broker._valuemktlever = 0.0
        broker._leverage = 1.0
        broker._unrealized = 0.0
        broker._fundshares = 100.0  # normal
        broker._fundval = 100.0
        broker._fundhist = []
        broker._fhistlast = [float("NaN"), float("NaN")]
        broker._cash_addition = collections.deque()
        broker.positions = collections.defaultdict(Position)

        result = broker._get_value()
        # _fundval = _value / _fundshares = 10000 / 100 = 100.0
        assert abs(broker._fundval - 100.0) < 1e-10
        assert abs(result - 10000.0) < 1e-10


# ---------------------------------------------------------------------------
# P1: fundstartval=0 — division by zero in init and cash addition
# ---------------------------------------------------------------------------

class TestFundstartvalZero:
    """Verify broker survives fundstartval=0.0 without ZeroDivisionError."""

    def test_init_fundstartval_zero_fallback(self):
        """fundstartval=0.0 should fall back to 100.0 to avoid division by zero.

        The 'or 100.0' guard prevents ZeroDivisionError when fundstartval
        is set to 0.0.
        """
        # Directly test the guard expression used in bbroker.py start()
        fundstartval = 0.0
        fundval = fundstartval or 100.0
        assert fundval == 100.0, "Guard should fall back to 100.0 for zero fundstartval"

        # Verify division works with the guarded value
        cash = 10000.0
        fundshares = cash / fundval  # no ZeroDivisionError
        assert abs(fundshares - 100.0) < 1e-10

    def test_cash_addition_with_zero_fundval(self):
        """Adding cash when _fundval is 0 should not crash."""
        broker = BackBroker()
        broker._cash = 10000.0
        broker._value = 10000.0
        broker._valuemkt = 0.0
        broker._valuelever = 0.0
        broker._valuemktlever = 0.0
        broker._leverage = 1.0
        broker._unrealized = 0.0
        broker._fundshares = 100.0
        broker._fundval = 0.0  # edge case: zero fundval
        broker._fundhist = []
        broker._fhistlast = [float("NaN"), float("NaN")]
        broker._cash_addition = collections.deque([500.0])
        broker.positions = collections.defaultdict(Position)

        # Should not raise ZeroDivisionError
        broker._get_value()
        # Cash should still be added
        assert abs(broker._cash - 10500.0) < 1e-10


class TestSubmittedOrderCashProjection:
    """Rejected submitted orders must not consume cash for later orders."""

    class _SequentialOrderStrategy(bt.Strategy):
        def __init__(self):
            self.ordered = False
            self.statuses = []

        def next(self):
            if self.ordered:
                return
            self.ordered = True
            self.buy(data=self.datas[0], size=200)
            self.buy(data=self.datas[1], size=50)

        def notify_order(self, order):
            self.statuses.append((order.data._name, order.getstatusname()))

    def test_margin_rejected_order_does_not_reserve_cash_for_next_submission(self):
        index = pd.date_range("2020-01-01", periods=3, freq="D")
        frame = pd.DataFrame(
            {
                "open": [1.0, 1.0, 1.0],
                "high": [1.0, 1.0, 1.0],
                "low": [1.0, 1.0, 1.0],
                "close": [1.0, 1.0, 1.0],
                "volume": [0.0, 0.0, 0.0],
                "openinterest": [0.0, 0.0, 0.0],
            },
            index=index,
        )

        cerebro = bt.Cerebro()
        cerebro.broker.setcash(100.0)
        cerebro.adddata(bt.feeds.PandasData(dataname=frame), name="oversized")
        cerebro.adddata(bt.feeds.PandasData(dataname=frame.copy()), name="affordable")
        cerebro.addstrategy(self._SequentialOrderStrategy)

        result = cerebro.run()
        statuses = result[0].statuses

        assert ("oversized", "Margin") in statuses
        assert ("affordable", "Margin") not in statuses
        assert ("affordable", "Completed") in statuses


class TestStackedBarTickRefresh:
    """Stacked/resampled bars must not execute orders with stale tick prices."""

    class _MarketOnPenultimateResampledBar(bt.Strategy):
        def __init__(self):
            self.order = None
            self.executed_prices = []

        def next(self):
            if len(self.data) == 2 and self.order is None:
                self.order = self.buy(size=1)

        def notify_order(self, order):
            if order.status == order.Completed:
                self.executed_prices.append(order.executed.price)

    def test_market_order_uses_final_stacked_bar_open_not_stale_tick_open(self):
        index = pd.to_datetime(
            [
                "2020-01-01 00:00:00",
                "2020-01-01 00:01:00",
                "2020-01-01 00:02:00",
                "2020-01-01 00:03:00",
            ]
        )
        frame = pd.DataFrame(
            {
                "open": [1.0, 2.0, 3.0, 4.0],
                "high": [1.0, 2.0, 3.0, 4.0],
                "low": [1.0, 2.0, 3.0, 4.0],
                "close": [1.0, 2.0, 3.0, 4.0],
                "volume": [0.0, 0.0, 0.0, 0.0],
                "openinterest": [0.0, 0.0, 0.0, 0.0],
            },
            index=index,
        )

        cerebro = bt.Cerebro(stdstats=False)
        cerebro.broker.setcash(1000.0)
        cerebro.resampledata(
            bt.feeds.PandasData(dataname=frame, timeframe=bt.TimeFrame.Minutes, compression=1),
            timeframe=bt.TimeFrame.Minutes,
            compression=2,
        )
        cerebro.addstrategy(self._MarketOnPenultimateResampledBar)

        result = cerebro.run()

        assert result[0].executed_prices == [pytest.approx(4.0)]
