#!/usr/bin/env python
"""Regression tests for order.py edge-case fixes.

Covers:
- P0: OrderBase.__ne__ crashes on None (AttributeError)
- P0: OrderData.addbit division by zero when self.size becomes 0
"""

import pytest

from backtrader.order import OrderData, OrderExecutionBit


# ---------------------------------------------------------------------------
# P0: OrderBase.__ne__ — None comparison crash
# ---------------------------------------------------------------------------

class TestOrderBaseNoneComparison:
    """Verify __eq__ and __ne__ both handle None without crashing."""

    def _make_order(self):
        """Create a minimal Order-like object with ref attribute."""
        from backtrader.order import OrderBase
        # OrderBase.__init__ requires data/params; create a lightweight stub
        class FakeOrder:
            ref = 42
            __eq__ = OrderBase.__eq__
            __ne__ = OrderBase.__ne__
        return FakeOrder()

    def test_eq_none_returns_false(self):
        order = self._make_order()
        assert (order == None) is False  # noqa: E711

    def test_ne_none_returns_true(self):
        """Before fix: this raised AttributeError on None.ref access."""
        order = self._make_order()
        assert (order != None) is True  # noqa: E711

    def test_eq_same_ref(self):
        order1 = self._make_order()
        order2 = self._make_order()
        assert order1 == order2  # same ref=42

    def test_ne_different_ref(self):
        order1 = self._make_order()
        order2 = self._make_order()
        order2.ref = 99
        assert order1 != order2


# ---------------------------------------------------------------------------
# P0: OrderData.addbit — division by zero when size reaches 0
# ---------------------------------------------------------------------------

class TestOrderDataAddbitDivZero:
    """Verify addbit handles size reaching 0 without ZeroDivisionError."""

    def test_addbit_size_reaches_zero(self):
        """Two exbits that cancel out should not crash."""
        od = OrderData(size=0, price=0.0, remsize=100)

        # First execution: buy 100 @ 50
        bit1 = OrderExecutionBit(dt=1.0, size=100, price=50.0)
        od.addbit(bit1)
        assert od.size == 100
        assert od.price == 50.0

        # Second execution: sell 100 @ 55 (hypothetical cancel-out)
        # In practice this shouldn't happen on the same OrderData,
        # but the guard prevents a crash if it does.
        bit2 = OrderExecutionBit(dt=2.0, size=-100, price=55.0)
        od.addbit(bit2)  # Before fix: ZeroDivisionError
        assert od.size == 0
        assert od.price == 0.0  # guarded to 0.0 when size==0

    def test_addbit_normal_accumulation(self):
        """Normal same-direction accumulation still works correctly."""
        od = OrderData(size=0, price=0.0, remsize=200)

        bit1 = OrderExecutionBit(dt=1.0, size=100, price=50.0)
        od.addbit(bit1)
        assert od.size == 100
        assert od.price == 50.0

        bit2 = OrderExecutionBit(dt=2.0, size=100, price=60.0)
        od.addbit(bit2)
        assert od.size == 200
        # Weighted average: (100*50 + 100*60) / 200 = 55.0
        assert abs(od.price - 55.0) < 1e-10

    def test_addbit_single_execution(self):
        """Single execution from zero initial size."""
        od = OrderData(size=0, price=0.0, remsize=50)
        bit = OrderExecutionBit(dt=1.0, size=50, price=100.0)
        od.addbit(bit)
        assert od.size == 50
        assert od.price == 100.0
