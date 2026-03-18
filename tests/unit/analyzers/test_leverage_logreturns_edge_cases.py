"""Edge case tests for analyzer fixes (Round 19).

Tests:
- GrossLeverage: zero portfolio value should not cause ZeroDivisionError
- LogReturnsRolling: failed log calculation should log and return 0
- AnnualReturn: date conversion failure should log and skip
"""
import logging
from unittest.mock import MagicMock, patch

import pytest

from backtrader.analyzers.annualreturn import AnnualReturn
from backtrader.analyzers.leverage import GrossLeverage


class TestGrossLeverageZeroValue:
    """Test GrossLeverage with zero portfolio value."""

    def _make_analyzer(self, value=0.0, cash=0.0):
        """Create a minimal GrossLeverage analyzer with mocked internals."""
        analyzer = GrossLeverage.__new__(GrossLeverage)
        analyzer._value = value
        analyzer._cash = cash
        analyzer._fundmode = False
        analyzer.rets = {}
        # Mock data0.datetime.datetime()
        analyzer.data0 = MagicMock()
        analyzer.data0.datetime.datetime.return_value = "2021-01-01"
        return analyzer

    def test_zero_value_returns_zero_leverage(self):
        """Portfolio value=0 should produce leverage=0, not ZeroDivisionError."""
        analyzer = self._make_analyzer(value=0.0, cash=0.0)
        analyzer.next()
        assert analyzer.rets["2021-01-01"] == 0.0

    def test_normal_value_all_cash(self):
        """100% cash → leverage = 0."""
        analyzer = self._make_analyzer(value=10000.0, cash=10000.0)
        analyzer.next()
        assert analyzer.rets["2021-01-01"] == pytest.approx(0.0)

    def test_normal_value_fully_invested(self):
        """0% cash → leverage = 1."""
        analyzer = self._make_analyzer(value=10000.0, cash=0.0)
        analyzer.next()
        assert analyzer.rets["2021-01-01"] == pytest.approx(1.0)

    def test_normal_value_half_invested(self):
        """50% cash → leverage = 0.5."""
        analyzer = self._make_analyzer(value=10000.0, cash=5000.0)
        analyzer.next()
        assert analyzer.rets["2021-01-01"] == pytest.approx(0.5)

    def test_leveraged_position(self):
        """Cash negative → leverage > 1."""
        analyzer = self._make_analyzer(value=10000.0, cash=-5000.0)
        analyzer.next()
        assert analyzer.rets["2021-01-01"] == pytest.approx(1.5)

    def test_nonfinite_value_downgrades_to_zero(self):
        """NaN portfolio value should downgrade leverage to 0.0."""
        analyzer = self._make_analyzer(value=float("nan"), cash=1000.0)
        analyzer.next()
        assert analyzer.rets["2021-01-01"] == 0.0


class TestLogReturnsRollingLogging:
    """Test that LogReturnsRolling logs errors instead of silently swallowing."""

    def test_log_return_failure_is_logged(self):
        """When log calculation fails, it should log a debug message."""
        import math
        from backtrader.analyzers.logreturnsrolling import LogReturnsRolling

        analyzer = LogReturnsRolling.__new__(LogReturnsRolling)
        analyzer.rets = {}
        analyzer.dtkey = "2021-01-01"
        analyzer._value = -100.0  # negative value → math.log of negative → ValueError
        analyzer._values = [100.0]
        analyzer._lastvalue = None

        # Mock super().next() to be a no-op
        with patch.object(type(analyzer).__mro__[1], "next", return_value=None):
            with patch("backtrader.analyzers.logreturnsrolling.logger") as mock_logger:
                analyzer.next()

        assert analyzer.rets["2021-01-01"] == 0
        mock_logger.debug.assert_called_once()

    def test_log_return_nan_ratio_is_logged(self):
        """NaN ratios should be treated as invalid and downgraded to 0."""
        from backtrader.analyzers.logreturnsrolling import LogReturnsRolling

        analyzer = LogReturnsRolling.__new__(LogReturnsRolling)
        analyzer.rets = {}
        analyzer.dtkey = "2021-01-01"
        analyzer._value = float("nan")
        analyzer._values = [100.0]
        analyzer._lastvalue = None

        with patch.object(type(analyzer).__mro__[1], "next", return_value=None):
            with patch("backtrader.analyzers.logreturnsrolling.logger") as mock_logger:
                analyzer.next()

        assert analyzer.rets["2021-01-01"] == 0
        mock_logger.debug.assert_called_once()


class TestAnnualReturnLogging:
    """Test AnnualReturn defensive behavior on invalid cached dates."""

    def test_all_invalid_dates_do_not_create_negative_year_entry(self):
        analyzer = AnnualReturn.__new__(AnnualReturn)
        analyzer._dt_cache = ["bad-date-1", "bad-date-2"]
        analyzer._value_cache = [100.0, 110.0]

        with patch("backtrader.analyzers.annualreturn.logger") as mock_logger:
            analyzer.stop()

        assert analyzer.rets == []
        assert analyzer.ret == {}
        assert -1 not in analyzer.ret
        assert mock_logger.debug.call_count == 2

    def test_log_return_zero_denominator_is_logged(self):
        """Division by zero in log return should be logged."""
        from backtrader.analyzers.logreturnsrolling import LogReturnsRolling

        analyzer = LogReturnsRolling.__new__(LogReturnsRolling)
        analyzer.rets = {}
        analyzer.dtkey = "2021-01-01"
        analyzer._value = 100.0
        analyzer._values = [0.0]  # division by zero
        analyzer._lastvalue = None

        with patch.object(type(analyzer).__mro__[1], "next", return_value=None):
            with patch("backtrader.analyzers.logreturnsrolling.logger") as mock_logger:
                analyzer.next()

        assert analyzer.rets["2021-01-01"] == 0
        mock_logger.debug.assert_called_once()
