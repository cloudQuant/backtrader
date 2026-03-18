#!/usr/bin/env python
"""Regression tests for bbroker.py edge-case fixes.

Covers:
- P0: orderstatus() — self.orders.index(order) returned int, not order object
- P0: _get_value() — division by zero when _fundshares is 0
"""

import collections

import pytest

from backtrader.brokers.bbroker import BackBroker
from backtrader.order import Order
from backtrader.position import Position


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
