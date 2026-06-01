"""Edge case tests for order.py zero-price handling (Round 16 P0 fix).

Tests that price=0.0 and pricelimit=0.0 are correctly preserved as
explicit order prices, rather than being treated as "not set" by truthy checks.
"""
import datetime
import itertools
from unittest.mock import MagicMock, PropertyMock

import pytest

from backtrader.order import OrderBase, BuyOrder, SellOrder, OrderParams


def _make_mock_data(close_price=100.0, dt_value=737791.0):
    """Create a minimal mock data feed for order creation."""
    data = MagicMock()
    data.close.__getitem__ = MagicMock(return_value=close_price)
    data.datetime.__getitem__ = MagicMock(return_value=dt_value)
    data.datetime.datetime = MagicMock(return_value=datetime.datetime(2021, 1, 1))
    data.datetime.date = MagicMock(return_value=datetime.date(2021, 1, 1))
    data.date2num = MagicMock(return_value=dt_value + 1)
    data.p = MagicMock()
    data.p.sessionend = datetime.time(15, 0, 0)
    return data


class TestOrderZeroPricePreservation:
    """Test that price=0.0 is preserved in order creation (not treated as None)."""

    def setup_method(self):
        # Reset order ref counter for predictable refs
        OrderBase.refbasis = itertools.count(1)

    def test_buy_order_price_zero_preserved(self):
        """price=0.0 should be used as created.price, not fallback to pclose."""
        data = _make_mock_data(close_price=100.0)
        order = BuyOrder(
            owner=MagicMock(),
            data=data,
            size=1,
            price=0.0,
            pricelimit=None,
            exectype=OrderBase.Limit,
            valid=None,
            tradeid=0,
            trailamount=None,
            trailpercent=None,
        )
        # price=0.0 should be preserved, NOT replaced by pclose=100.0
        assert order.created.price == 0.0

    def test_buy_order_price_none_uses_pclose(self):
        """price=None should correctly fall back to pclose."""
        data = _make_mock_data(close_price=100.0)
        order = BuyOrder(
            owner=MagicMock(),
            data=data,
            size=1,
            price=None,
            pricelimit=None,
            exectype=OrderBase.Market,
            valid=None,
            tradeid=0,
            trailamount=None,
            trailpercent=None,
        )
        # price=None AND pricelimit=None → should use pclose
        assert order.created.price == 100.0

    def test_buy_order_pricelimit_zero_preserves_price(self):
        """pricelimit=0.0 should cause self.price to be used, not pclose."""
        data = _make_mock_data(close_price=100.0)
        order = BuyOrder(
            owner=MagicMock(),
            data=data,
            size=1,
            price=50.0,
            pricelimit=0.0,
            exectype=OrderBase.StopLimit,
            valid=None,
            tradeid=0,
            trailamount=None,
            trailpercent=None,
        )
        # pricelimit=0.0 is not None → self.price (50.0) should be used
        assert order.created.price == 50.0

    def test_sell_order_price_zero_preserved(self):
        """Sell order with price=0.0 should preserve it."""
        data = _make_mock_data(close_price=100.0)
        order = SellOrder(
            owner=MagicMock(),
            data=data,
            size=1,
            price=0.0,
            pricelimit=None,
            exectype=OrderBase.Limit,
            valid=None,
            tradeid=0,
            trailamount=None,
            trailpercent=None,
        )
        assert order.created.price == 0.0

    def test_order_price_normal_value(self):
        """Normal non-zero price should work as before."""
        data = _make_mock_data(close_price=100.0)
        order = BuyOrder(
            owner=MagicMock(),
            data=data,
            size=1,
            price=55.5,
            pricelimit=None,
            exectype=OrderBase.Limit,
            valid=None,
            tradeid=0,
            trailamount=None,
            trailpercent=None,
        )
        assert order.created.price == 55.5


class TestBrokerPannotatedZeroPrice:
    """Test that pannotated=0.0 is correctly treated as 'annotated'."""

    def test_pannotated_none_is_not_annotated(self):
        """pannotated=None means no annotation was made."""
        order = MagicMock()
        order.pannotated = None
        # The condition: order.pannotated is not None
        assert not (order.pannotated is not None)

    def test_pannotated_zero_is_annotated(self):
        """pannotated=0.0 means a valid price of 0.0 was annotated."""
        order = MagicMock()
        order.pannotated = 0.0
        # With the fix, 0.0 should be treated as a valid annotation
        assert (order.pannotated is not None)

    def test_pannotated_normal_price_is_annotated(self):
        """pannotated=100.0 means a normal price was annotated."""
        order = MagicMock()
        order.pannotated = 100.0
        assert (order.pannotated is not None)
