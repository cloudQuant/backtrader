"""Edge case tests for drawdown, timereturn, calmar zero-value fixes (Round 20).

Tests:
- DrawDown: zero peak value should not cause ZeroDivisionError
- TimeReturn: zero start value should not cause ZeroDivisionError
- Calmar: zero/negative values should not cause ZeroDivisionError/ValueError
"""
import math
from unittest.mock import MagicMock, patch, PropertyMock

import pytest


class TestDrawdownZeroPeak:
    """Test DrawDown analyzer with zero peak value."""

    def _make_analyzer(self):
        from backtrader.analyzers.drawdown import TimeDrawDown
        analyzer = TimeDrawDown.__new__(TimeDrawDown)
        analyzer.dd = 0.0
        analyzer.maxdd = 0.0
        analyzer.maxddlen = 0
        analyzer.peak = 0.0
        analyzer.ddlen = 0
        analyzer._fundmode = False
        analyzer.strategy = MagicMock()
        return analyzer

    def test_zero_peak_no_crash(self):
        """peak=0 should produce dd=0, not ZeroDivisionError."""
        analyzer = self._make_analyzer()
        analyzer.peak = 0.0
        analyzer.strategy.broker.getvalue.return_value = 0.0
        analyzer.on_dt_over()
        assert analyzer.dd == 0.0

    def test_zero_peak_positive_value(self):
        """peak=0 but value > 0 should update peak, dd=0."""
        analyzer = self._make_analyzer()
        analyzer.peak = 0.0
        analyzer.strategy.broker.getvalue.return_value = 100.0
        analyzer.on_dt_over()
        # value > peak → peak updated to 100
        assert analyzer.peak == 100.0
        assert analyzer.dd == 0.0

    def test_normal_drawdown(self):
        """Normal drawdown calculation should work correctly."""
        analyzer = self._make_analyzer()
        analyzer.peak = 100.0
        analyzer.strategy.broker.getvalue.return_value = 90.0
        analyzer.on_dt_over()
        assert analyzer.dd == pytest.approx(10.0)

    def test_no_drawdown(self):
        """No drawdown when value equals peak."""
        analyzer = self._make_analyzer()
        analyzer.peak = 100.0
        analyzer.strategy.broker.getvalue.return_value = 100.0
        analyzer.on_dt_over()
        assert analyzer.dd == pytest.approx(0.0)


class TestTimeReturnZeroStart:
    """Test TimeReturn analyzer with zero start value."""

    def _make_analyzer(self):
        from backtrader.analyzers.timereturn import TimeReturn
        analyzer = TimeReturn.__new__(TimeReturn)
        analyzer.rets = {}
        analyzer.dtkey = "2021-01-01"
        analyzer._lastvalue = None
        return analyzer

    def test_zero_start_value(self):
        """_value_start=0 should return 0.0, not ZeroDivisionError."""
        analyzer = self._make_analyzer()
        analyzer._value = 100.0
        analyzer._value_start = 0.0
        with patch.object(type(analyzer).__mro__[1], "next", return_value=None):
            analyzer.next()
        assert analyzer.rets["2021-01-01"] == 0.0

    def test_normal_return(self):
        """Normal return calculation should work."""
        analyzer = self._make_analyzer()
        analyzer._value = 110.0
        analyzer._value_start = 100.0
        with patch.object(type(analyzer).__mro__[1], "next", return_value=None):
            analyzer.next()
        assert analyzer.rets["2021-01-01"] == pytest.approx(0.1)

    def test_negative_return(self):
        """Negative return should work."""
        analyzer = self._make_analyzer()
        analyzer._value = 90.0
        analyzer._value_start = 100.0
        with patch.object(type(analyzer).__mro__[1], "next", return_value=None):
            analyzer.next()
        assert analyzer.rets["2021-01-01"] == pytest.approx(-0.1)


class TestCalmarZeroValue:
    """Test Calmar analyzer with zero/edge values."""

    def _make_analyzer(self):
        import collections
        from backtrader.analyzers.calmar import Calmar
        analyzer = Calmar.__new__(Calmar)
        analyzer._mdd = 0.0
        analyzer._maxdd = MagicMock()
        analyzer._maxdd.maxdd = 0.0
        analyzer._fundmode = False
        analyzer.strategy = MagicMock()
        analyzer._values = collections.deque(maxlen=12 * 21)
        analyzer.rets = {}
        analyzer.dtkey = "2021-01-01"
        analyzer.calmar = 0.0
        return analyzer

    def test_zero_start_value(self):
        """_values[0]=0 should not cause ZeroDivisionError."""
        analyzer = self._make_analyzer()
        analyzer._values.append(0.0)
        analyzer.strategy.broker.getvalue.return_value = 100.0
        analyzer.on_dt_over()
        # Should not crash; calmar should be 0 / Inf = 0
        assert analyzer.calmar == 0.0

    def test_negative_ratio(self):
        """Negative value ratio should not cause math.log ValueError."""
        analyzer = self._make_analyzer()
        analyzer._values.append(100.0)
        analyzer.strategy.broker.getvalue.return_value = -50.0
        analyzer.on_dt_over()
        # math.log of negative → caught, rann=0 → calmar=0
        assert analyzer.calmar == 0.0

    def test_normal_calmar(self):
        """Normal Calmar calculation should work."""
        analyzer = self._make_analyzer()
        analyzer._values.append(100.0)
        analyzer._mdd = 10.0
        analyzer._maxdd.maxdd = 10.0
        analyzer.strategy.broker.getvalue.return_value = 110.0
        analyzer.on_dt_over()
        # rann = log(110/100) / 2
        expected_rann = math.log(110.0 / 100.0) / 2
        expected_calmar = expected_rann / 10.0
        assert analyzer.calmar == pytest.approx(expected_calmar)
