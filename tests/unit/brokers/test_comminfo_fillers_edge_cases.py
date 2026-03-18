#!/usr/bin/env python
"""Regression tests for comminfo and fillers edge-case fixes.

Covers:
- P0: ComminfoDC.get_credit_interest uses total_seconds() instead of .seconds
- P1: BarPointPerc division-by-zero guard when parts <= 0
- P1: ComminfoFundingRate.get_credit_interest robust fallback chain
"""

import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from backtrader.comminfo import ComminfoDC, ComminfoFundingRate
from backtrader.fillers import BarPointPerc


# ---------------------------------------------------------------------------
# P0: ComminfoDC.get_credit_interest — total_seconds vs .seconds
# ---------------------------------------------------------------------------

class TestComminfoDCCreditInterest:
    """Verify that multi-day durations are computed correctly."""

    def _make_pos(self, size, price, dt):
        pos = SimpleNamespace(size=size, price=price, datetime=dt)
        return pos

    def test_multiday_duration_uses_total_seconds(self):
        """If position was opened 2.5 days ago, days should be ~2.5, not < 1."""
        comm = ComminfoDC(
            commission=0.001,
            mult=1.0,
            margin=0.1,
            interest=3.0,
        )
        dt_open = datetime.datetime(2025, 1, 1, 0, 0, 0)
        dt_now = datetime.datetime(2025, 1, 3, 12, 0, 0)  # 2.5 days later

        pos = self._make_pos(size=-10, price=100.0, dt=dt_open)

        # Mock data (not used in this path)
        data = MagicMock()

        interest = comm.get_credit_interest(data, pos, dt_now)

        # With .seconds bug: gap_seconds = 43200 (only 12h component), days = 0.5
        # With .total_seconds() fix: gap_seconds = 216000 (2.5 days), days = 2.5
        # ComminfoDC formula for size<0: days * creditrate * position_value
        # position_value = size * price * mult (negative for short)
        expected_days = 2.5
        position_value = -10 * 100.0 * 1.0  # -1000.0
        expected = expected_days * (3.0 / 365.0) * position_value
        assert abs(interest - expected) < 1e-6, (
            f"Interest {interest} != expected {expected}; "
            "likely still using .seconds instead of .total_seconds()"
        )
        # Key check: magnitude should reflect 2.5 days, not 0.5 days
        wrong_days = 0.5  # what .seconds would give (only 12h component)
        wrong_expected = wrong_days * (3.0 / 365.0) * position_value
        assert abs(interest - wrong_expected) > 1e-6, "Result matches .seconds bug"

    def test_subday_duration_still_works(self):
        """Sub-day durations should still compute correctly."""
        comm = ComminfoDC(
            commission=0.001,
            mult=1.0,
            margin=0.1,
            interest=3.0,
        )
        dt_open = datetime.datetime(2025, 1, 1, 10, 0, 0)
        dt_now = datetime.datetime(2025, 1, 1, 16, 0, 0)  # 6 hours later

        pos = self._make_pos(size=-5, price=200.0, dt=dt_open)
        data = MagicMock()

        interest = comm.get_credit_interest(data, pos, dt_now)

        expected_days = 6.0 / 24.0  # 0.25 days
        position_value = -5 * 200.0 * 1.0  # -1000.0
        expected = expected_days * (3.0 / 365.0) * position_value
        assert abs(interest - expected) < 1e-6


# ---------------------------------------------------------------------------
# P1: BarPointPerc — division by zero guard
# ---------------------------------------------------------------------------

class TestBarPointPercDivisionByZero:
    """Verify that degenerate bar data doesn't cause ZeroDivisionError."""

    def _make_filler(self, minmov=0.01, perc=100.0):
        return BarPointPerc(minmov=minmov, perc=perc)

    def _make_order(self, volume, high, low, remsize=100):
        data = SimpleNamespace(
            volume=SimpleNamespace(**{"__getitem__": lambda self, i: volume}),
            high=SimpleNamespace(**{"__getitem__": lambda self, i: high}),
            low=SimpleNamespace(**{"__getitem__": lambda self, i: low}),
        )
        # Make indexable mocks
        data.volume = MagicMock()
        data.volume.__getitem__ = MagicMock(return_value=volume)
        data.high = MagicMock()
        data.high.__getitem__ = MagicMock(return_value=high)
        data.low = MagicMock()
        data.low.__getitem__ = MagicMock(return_value=low)

        executed = SimpleNamespace(remsize=remsize)
        order = SimpleNamespace(data=data, executed=executed)
        return order

    def test_normal_bar(self):
        """Normal bar with range > minmov should work."""
        filler = self._make_filler(minmov=0.01, perc=100.0)
        order = self._make_order(volume=1000, high=10.0, low=9.0, remsize=50)
        result = filler(order, 9.5, 0)
        assert result >= 0

    def test_zero_range_bar(self):
        """Bar where high == low should not crash (parts = 1)."""
        filler = self._make_filler(minmov=0.01, perc=100.0)
        order = self._make_order(volume=1000, high=10.0, low=10.0, remsize=50)
        # Should not raise ZeroDivisionError
        result = filler(order, 10.0, 0)
        assert result >= 0

    def test_degenerate_high_less_than_low(self):
        """Corrupted data where high < low should not crash."""
        filler = self._make_filler(minmov=0.01, perc=100.0)
        # high < low by more than minmov → parts would be negative without guard
        order = self._make_order(volume=1000, high=9.0, low=10.0, remsize=50)
        # Should not raise ZeroDivisionError; parts clamped to 1
        result = filler(order, 9.5, 0)
        assert result >= 0

    def test_minmov_none(self):
        """When minmov is None, parts stays 1, no crash."""
        filler = self._make_filler(minmov=None, perc=100.0)
        order = self._make_order(volume=1000, high=10.0, low=9.0, remsize=50)
        result = filler(order, 9.5, 0)
        assert result >= 0


# ---------------------------------------------------------------------------
# P1: ComminfoFundingRate.get_credit_interest — robust fallback
# ---------------------------------------------------------------------------

class TestComminfoFundingRateFallback:
    """Verify that mark_price fallback chain handles missing/empty attrs."""

    def _make_comm(self):
        return ComminfoFundingRate(
            commission=0.001,
            mult=1.0,
            margin=0.1,
        )

    def _make_pos(self, size, price):
        return SimpleNamespace(size=size, price=price)

    def test_fallback_to_price_when_no_mark_attrs(self):
        """When data has no mark_price_* attrs, falls back to pos.price."""
        comm = self._make_comm()
        data = SimpleNamespace()  # no mark_price_open or mark_price_close
        pos = self._make_pos(size=10, price=50000.0)

        # Should not raise; falls back to price
        result = comm.get_credit_interest(data, pos, None)
        # With no funding_rate attr, funding_rate=0.0 → result=0.0
        assert result == 0.0

    def test_fallback_when_mark_price_close_empty(self):
        """When mark_price_close exists but is empty, falls back to price."""
        comm = self._make_comm()

        # mark_price_open raises IndexError, mark_price_close is empty list
        mark_open = MagicMock()
        mark_open.__getitem__ = MagicMock(side_effect=IndexError)
        mark_close = MagicMock()
        mark_close.__getitem__ = MagicMock(side_effect=IndexError)

        data = SimpleNamespace(
            mark_price_open=mark_open,
            mark_price_close=mark_close,
        )
        pos = self._make_pos(size=10, price=50000.0)

        # Should not raise
        result = comm.get_credit_interest(data, pos, None)
        assert result == 0.0

    def test_uses_mark_price_open_when_available(self):
        """When mark_price_open[1] is available, uses it."""
        comm = self._make_comm()

        mark_open = MagicMock()
        mark_open.__getitem__ = MagicMock(return_value=51000.0)
        funding = MagicMock()
        funding.__getitem__ = MagicMock(return_value=0.0001)

        data = SimpleNamespace(
            mark_price_open=mark_open,
            current_funding_rate=funding,
        )
        pos = self._make_pos(size=10, price=50000.0)

        result = comm.get_credit_interest(data, pos, None)
        # funding_rate * size * current_price * mult
        expected = 0.0001 * 10 * 51000.0 * 1.0
        assert abs(result - expected) < 1e-6
