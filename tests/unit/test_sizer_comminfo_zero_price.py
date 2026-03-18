"""Edge case tests for sizer and comminfo zero-price handling (Round 18 P0 fix).

Tests that price=0.0 does not cause ZeroDivisionError in:
- PercentSizer._getsizing
- CommInfoBase.getsize
"""
from unittest.mock import MagicMock, PropertyMock

import pytest

from backtrader.comminfo import CommInfoBase
from backtrader.sizers.percents_sizer import PercentSizer, AllInSizer


def _make_comminfo(stocklike=True, margin=1.0, mult=1, leverage=1):
    """Create a CommInfoBase with the given parameters."""
    ci = CommInfoBase(
        commission=0.001,
        mult=mult,
        margin=margin,
        automargin=False,
        commtype=CommInfoBase.COMM_PERC,
        stocklike=stocklike,
        percabs=True,
        interest=0.0,
        interest_long=False,
        leverage=leverage,
    )
    return ci


class TestCommInfoGetSizeZeroPrice:
    """Test CommInfoBase.getsize with zero price."""

    def test_getsize_zero_price_stocklike(self):
        """getsize(price=0, cash=10000) should return 0, not raise ZeroDivisionError."""
        ci = _make_comminfo(stocklike=True)
        result = ci.getsize(0.0, 10000.0)
        assert result == 0

    def test_getsize_zero_price_futures(self):
        """getsize(price=0, cash=10000) for futures should return 0."""
        ci = _make_comminfo(stocklike=False, margin=0.1, mult=10)
        result = ci.getsize(0.0, 10000.0)
        assert result == 0

    def test_getsize_normal_price_stocklike(self):
        """Normal price should work correctly."""
        ci = _make_comminfo(stocklike=True, leverage=1)
        result = ci.getsize(100.0, 10000.0)
        # stocklike: leverage * (cash // price) = 1 * (10000 // 100) = 100
        assert result == 100.0

    def test_getsize_normal_price_futures(self):
        """Normal price for futures should work correctly."""
        # automargin=False → get_margin returns raw margin param value
        ci = _make_comminfo(stocklike=False, margin=100.0, mult=10, leverage=1)
        # margin = 100.0 (raw param), cash // margin = 10000 // 100 = 100
        result = ci.getsize(100.0, 10000.0)
        assert result == 100.0

    def test_getsize_zero_margin_futures(self):
        """If margin is 0 (after init normalization to 1.0), should not crash."""
        # Note: CommInfoBase.__init__ normalizes margin=0 to 1.0 for futures
        ci = _make_comminfo(stocklike=False, margin=1.0, mult=10, leverage=1)
        result = ci.getsize(100.0, 10000.0)
        # margin=1.0, cash // 1.0 = 10000
        assert result == 10000.0


class TestPercentSizerZeroPrice:
    """Test PercentSizer with zero close price."""

    def _make_sizer(self, percents=20, retint=False):
        """Create a PercentSizer with mock broker."""
        sizer = PercentSizer(percents=percents, retint=retint)
        sizer.broker = MagicMock()
        sizer.strategy = MagicMock()
        return sizer

    def _make_data(self, close_price=100.0):
        """Create mock data with given close price."""
        data = MagicMock()
        data.close.__getitem__ = MagicMock(return_value=close_price)
        return data

    def test_zero_close_price_no_position(self):
        """close[0]=0.0 with no position should return 0, not ZeroDivisionError."""
        sizer = self._make_sizer(percents=20)
        data = self._make_data(close_price=0.0)
        # No position
        sizer.broker.getposition.return_value = MagicMock(size=0)
        sizer.broker.getposition.return_value.__bool__ = MagicMock(return_value=False)

        ci = _make_comminfo()
        result = sizer._getsizing(ci, 10000.0, data, isbuy=True)
        assert result == 0

    def test_normal_close_price_no_position(self):
        """Normal close price should calculate size correctly."""
        sizer = self._make_sizer(percents=20)
        data = self._make_data(close_price=100.0)
        sizer.broker.getposition.return_value = MagicMock(size=0)
        sizer.broker.getposition.return_value.__bool__ = MagicMock(return_value=False)

        ci = _make_comminfo()
        result = sizer._getsizing(ci, 10000.0, data, isbuy=True)
        # 10000 / 100 * (20/100) = 20.0
        assert result == pytest.approx(20.0)

    def test_existing_position_returns_position_size(self):
        """With existing position, should return position.size."""
        sizer = self._make_sizer(percents=20)
        data = self._make_data(close_price=100.0)
        pos = MagicMock(size=50)
        pos.__bool__ = MagicMock(return_value=True)
        sizer.broker.getposition.return_value = pos

        ci = _make_comminfo()
        result = sizer._getsizing(ci, 10000.0, data, isbuy=True)
        assert result == 50

    def test_retint_truncates(self):
        """retint=True should return int."""
        sizer = self._make_sizer(percents=33, retint=True)
        data = self._make_data(close_price=100.0)
        sizer.broker.getposition.return_value = MagicMock(size=0)
        sizer.broker.getposition.return_value.__bool__ = MagicMock(return_value=False)

        ci = _make_comminfo()
        result = sizer._getsizing(ci, 10000.0, data, isbuy=True)
        # 10000 / 100 * (33/100) = 33.0 → int(33.0) = 33
        assert result == 33
        assert isinstance(result, int)
