#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
"""Edge case unit tests for reports module.

Tests cover:
- Zero-value metrics (start_cash=0, rpl=0.0, drawdown=0)
- None/missing analyzer scenarios
- _get_analyzer_result exact vs substring matching
- get_risk_metrics pnl_metrics parameter forwarding
- sqn_to_rating additional edge cases
- _make_json_serializable with NaN, Inf, datetime, complex objects
- _fmt_metric helper
- _build_context user/memo parameter passing (no instance state)
- plot_equity_curve handles invalid initial values without producing non-finite normalized points
"""

import math
import pytest
from datetime import datetime
from unittest.mock import MagicMock, PropertyMock

from backtrader.reports.charts import MATPLOTLIB_AVAILABLE, ReportChart
from backtrader.reports.performance import PerformanceCalculator
from backtrader.reports.reporter import ReportGenerator


# ---------------------------------------------------------------------------
# Helpers: lightweight mock strategy / analyzer
# ---------------------------------------------------------------------------

class FakeAnalyzer:
    """Minimal analyzer mock with configurable name and result."""

    def __init__(self, cls_name, result, custom_name=""):
        # Dynamically create a type with the given class name
        self.__class__ = type(cls_name, (), {
            "get_analysis": lambda self_: result,
            "__name__": cls_name,
        })
        self._name = custom_name
        self._result = result

    def get_analysis(self):
        return self._result


def _make_strategy(
    start_cash=100000,
    end_value=100000,
    analyzers=None,
    data=None,
):
    """Build a minimal mock strategy for PerformanceCalculator."""
    strategy = MagicMock()
    strategy.__class__.__name__ = "MockStrategy"

    broker = MagicMock()
    broker.startingcash = start_cash
    broker.getvalue.return_value = end_value
    strategy.broker = broker

    if analyzers is not None:
        strategy.analyzers = analyzers
    else:
        strategy.analyzers = []

    if data is not None:
        strategy.data = data
    else:
        # No data attribute
        del strategy.data

    strategy.observers = []

    return strategy


# ===========================================================================
# PerformanceCalculator tests
# ===========================================================================


class TestPnlMetricsZeroValues:
    """Test that zero-value metrics are computed, not treated as None/falsy."""

    def test_zero_rpl_is_computed(self):
        """When end_value == start_cash, rpl should be 0.0 not None."""
        strategy = _make_strategy(start_cash=100000, end_value=100000)
        calc = PerformanceCalculator(strategy)
        metrics = calc.get_pnl_metrics()
        assert metrics["rpl"] == 0.0
        assert metrics["total_return"] == 0.0

    def test_zero_start_cash_no_division_error(self):
        """When start_cash is 0, total_return should remain None (no ZeroDivisionError)."""
        strategy = _make_strategy(start_cash=0, end_value=0)
        calc = PerformanceCalculator(strategy)
        metrics = calc.get_pnl_metrics()
        assert metrics["rpl"] == 0.0
        assert metrics["total_return"] is None  # Cannot compute return from 0

    def test_annual_return_skips_non_positive_compound_ratio(self):
        """When total_return <= -100%, annual_return should remain None."""
        strategy = _make_strategy(start_cash=100000, end_value=0)

        class _DateTimeLine:
            def __getitem__(self, idx):
                values = [1.0, 2.0]
                return values[idx]

        class _DataStub:
            datetime = _DateTimeLine()

            def __len__(self):
                return 2

        strategy.data = _DataStub()
        calc = PerformanceCalculator(strategy)
        metrics = calc.get_pnl_metrics()

        assert metrics["total_return"] == -100.0
        assert metrics["annual_return"] is None

    def test_zero_profit_factor(self):
        """Won_trades=0.0 and lost_trades!=0 should produce profit_factor=0.0."""
        trade_analysis = {
            "pnl": {"net": {"total": -500}},
            "won": {"total": 0, "pnl": {"total": 0.0}},
            "lost": {"total": 2, "pnl": {"total": -500.0}},
            "total": {"total": 2, "closed": 2},
        }
        analyzer = FakeAnalyzer("TradeAnalyzer", trade_analysis)
        strategy = _make_strategy(analyzers=[analyzer])
        calc = PerformanceCalculator(strategy)
        metrics = calc.get_pnl_metrics()
        assert metrics["profit_factor"] == 0.0

    def test_rpl_per_trade_with_zero_rpl(self):
        """rpl=0.0 with closed>0 should produce rpl_per_trade=0.0."""
        trade_analysis = {
            "pnl": {"net": {"total": 0.0}},
            "won": {"total": 1, "pnl": {"total": 100.0}},
            "lost": {"total": 1, "pnl": {"total": -100.0}},
            "total": {"total": 2, "closed": 2},
        }
        analyzer = FakeAnalyzer("TradeAnalyzer", trade_analysis)
        strategy = _make_strategy(analyzers=[analyzer])
        calc = PerformanceCalculator(strategy)
        metrics = calc.get_pnl_metrics()
        assert metrics["rpl"] == 0.0
        assert metrics["rpl_per_trade"] == 0.0


class TestRiskMetricsZeroValues:
    """Test risk metrics with zero drawdown and Calmar ratio edge cases."""

    def test_zero_drawdown_no_calmar(self):
        """When max_pct_drawdown=0, calmar_ratio should stay None (no division)."""
        dd_analyzer = FakeAnalyzer("DrawDown", {
            "max": {"moneydown": 0.0, "drawdown": 0.0}
        })
        strategy = _make_strategy(
            start_cash=100000, end_value=110000, analyzers=[dd_analyzer]
        )
        calc = PerformanceCalculator(strategy)
        metrics = calc.get_risk_metrics()
        assert metrics["max_pct_drawdown"] == 0.0
        assert metrics["max_money_drawdown"] == 0.0
        assert metrics["calmar_ratio"] is None

    def test_invalid_drawdown_or_annual_return_skips_calmar(self):
        """Non-finite or non-positive Calmar inputs should keep calmar_ratio as None."""
        dd_analyzer = FakeAnalyzer("DrawDown", {
            "max": {"moneydown": 1000.0, "drawdown": float("nan")}
        })
        strategy = _make_strategy(
            start_cash=100000,
            end_value=110000,
            analyzers=[dd_analyzer],
        )
        calc = PerformanceCalculator(strategy)
        metrics = calc.get_risk_metrics(pnl_metrics={"annual_return": float("inf")})

        assert math.isnan(metrics["max_pct_drawdown"])
        assert metrics["calmar_ratio"] is None

    def test_pnl_metrics_forwarding(self):
        """get_risk_metrics(pnl_metrics=...) uses provided dict, not recomputes."""
        dd_analyzer = FakeAnalyzer("DrawDown", {
            "max": {"moneydown": 5000.0, "drawdown": 5.0}
        })
        strategy = _make_strategy(analyzers=[dd_analyzer])
        calc = PerformanceCalculator(strategy)

        fake_pnl = {"annual_return": 10.0}
        metrics = calc.get_risk_metrics(pnl_metrics=fake_pnl)
        assert metrics["calmar_ratio"] == pytest.approx(2.0)

    def test_pnl_metrics_none_triggers_recompute(self):
        """get_risk_metrics() without pnl_metrics falls back to get_pnl_metrics()."""
        strategy = _make_strategy(start_cash=100000, end_value=100000)
        calc = PerformanceCalculator(strategy)
        metrics = calc.get_risk_metrics()
        # Should not raise, calmar_ratio stays None (no drawdown analyzer)
        assert metrics["calmar_ratio"] is None


class TestAnalyzerResultMatching:
    """Test _get_analyzer_result exact vs substring matching."""

    def test_exact_match_preferred(self):
        """Exact class name match is returned before substring match."""
        # Both "TimeReturn" and "AnnualReturn" contain "return"
        time_return = FakeAnalyzer("TimeReturn", {"daily": 0.01})
        annual_return = FakeAnalyzer("AnnualReturn", {"yearly": 0.10})

        strategy = _make_strategy(analyzers=[time_return, annual_return])
        calc = PerformanceCalculator(strategy)

        # Exact match for "timereturn"
        result = calc._get_analyzer_result("timereturn")
        assert result == {"daily": 0.01}

        # Exact match for "annualreturn"
        result = calc._get_analyzer_result("annualreturn")
        assert result == {"yearly": 0.10}

    def test_custom_name_exact_match(self):
        """_name attribute exact match works."""
        analyzer = FakeAnalyzer("SQN", {"sqn": 3.5}, custom_name="sqn")
        strategy = _make_strategy(analyzers=[analyzer])
        calc = PerformanceCalculator(strategy)

        result = calc._get_analyzer_result("sqn")
        assert result == {"sqn": 3.5}

    def test_substring_fallback(self):
        """When no exact match, substring match is used as fallback."""
        analyzer = FakeAnalyzer("MySharpeRatioCustom", {"sharperatio": 1.5})
        strategy = _make_strategy(analyzers=[analyzer])
        calc = PerformanceCalculator(strategy)

        result = calc._get_analyzer_result("sharpe")
        assert result == {"sharperatio": 1.5}

    def test_no_match_returns_none(self):
        """Unknown analyzer name returns None."""
        strategy = _make_strategy(analyzers=[])
        calc = PerformanceCalculator(strategy)

        result = calc._get_analyzer_result("nonexistent")
        assert result is None

    def test_none_analyzers_returns_none(self):
        """Strategy without analyzers attribute returns None."""
        strategy = MagicMock()
        strategy.analyzers = None
        strategy.broker = MagicMock()
        calc = PerformanceCalculator(strategy)

        result = calc._get_analyzer_result("anything")
        assert result is None


class TestSqnToRating:
    """Additional edge cases for sqn_to_rating."""

    def test_negative_score(self):
        assert PerformanceCalculator.sqn_to_rating(-5.0) == "Poor"

    def test_zero_score(self):
        assert PerformanceCalculator.sqn_to_rating(0.0) == "Poor"

    def test_infinity(self):
        assert PerformanceCalculator.sqn_to_rating(float("inf")) == "Holy Grail"

    def test_negative_infinity(self):
        assert PerformanceCalculator.sqn_to_rating(float("-inf")) == "Poor"

    def test_nan_returns_na(self):
        assert PerformanceCalculator.sqn_to_rating(float("nan")) == "N/A"


class TestNoAnalyzersScenario:
    """Strategy with no analyzers — all metrics should be safe defaults."""

    def test_all_metrics_with_no_analyzers(self):
        strategy = _make_strategy(start_cash=50000, end_value=55000, analyzers=[])
        calc = PerformanceCalculator(strategy)
        metrics = calc.get_all_metrics()

        assert metrics["start_cash"] == 50000
        assert metrics["end_value"] == 55000
        assert metrics["rpl"] == 5000.0
        assert metrics["total_return"] == pytest.approx(10.0)
        assert metrics["sharpe_ratio"] is None
        assert metrics["sqn_score"] is None
        assert metrics["total_number_trades"] == 0


# ===========================================================================
# ReportGenerator tests
# ===========================================================================


class TestFmtMetric:
    """Test the _fmt_metric static helper."""

    def test_none_returns_na(self):
        assert ReportGenerator._fmt_metric(None) == "N/A"

    def test_non_finite_returns_na(self):
        assert ReportGenerator._fmt_metric(float("nan")) == "N/A"
        assert ReportGenerator._fmt_metric(float("inf")) == "N/A"
        assert ReportGenerator._fmt_metric(float("-inf")) == "N/A"

    def test_zero_is_formatted(self):
        result = ReportGenerator._fmt_metric(0.0)
        assert result == "0.00"

    def test_positive_with_suffix(self):
        result = ReportGenerator._fmt_metric(12.34, ".2f", "%")
        assert result == "12.34%"

    def test_negative_value(self):
        result = ReportGenerator._fmt_metric(-500.5, ",.2f")
        assert result == "-500.50"

    def test_non_numeric_fallback(self):
        result = ReportGenerator._fmt_metric("not-a-number", ".2f")
        assert result == "not-a-number"


@pytest.mark.skipif(not MATPLOTLIB_AVAILABLE, reason="matplotlib not available")
class TestReportChart:
    def test_plot_equity_curve_skips_invalid_initial_values(self):
        chart = ReportChart()
        dates = [datetime(2024, 1, d) for d in range(1, 6)]
        values = [float("nan"), None, float("inf"), 100.0, 110.0]

        fig = chart.plot_equity_curve(dates, values)

        assert fig is not None
        plotted = list(fig.axes[0].lines[0].get_ydata())
        assert plotted[0] == pytest.approx(100.0)
        assert plotted[1] == pytest.approx(100.0)
        assert plotted[2] == pytest.approx(100.0)
        assert plotted[3] == pytest.approx(100.0)
        assert plotted[4] == pytest.approx(110.0)

    def test_plot_equity_curve_sanitizes_invalid_benchmark_values(self):
        chart = ReportChart()
        dates = [datetime(2024, 1, d) for d in range(1, 6)]
        values = [100.0, 101.0, 102.0, 103.0, 104.0]
        benchmark_values = [100.0, float("nan"), None, float("inf"), 105.0]

        fig = chart.plot_equity_curve(dates, values, dates, benchmark_values)

        assert fig is not None
        benchmark_line = list(fig.axes[0].lines[1].get_ydata())
        assert benchmark_line[0] == pytest.approx(100.0)
        assert benchmark_line[1] == pytest.approx(100.0)
        assert benchmark_line[2] == pytest.approx(100.0)
        assert benchmark_line[3] == pytest.approx(100.0)
        assert benchmark_line[4] == pytest.approx(105.0)

    def test_plot_drawdown_skips_invalid_values(self):
        chart = ReportChart()
        dates = [datetime(2024, 1, d) for d in range(1, 6)]
        values = [float("nan"), 100.0, None, float("inf"), 90.0]

        fig = chart.plot_drawdown(dates, values)

        assert fig is not None
        plotted = list(fig.axes[0].lines[0].get_ydata())
        assert plotted[0] == pytest.approx(0.0)
        assert plotted[1] == pytest.approx(0.0)
        assert plotted[2] == pytest.approx(0.0)
        assert plotted[3] == pytest.approx(0.0)
        assert plotted[4] == pytest.approx(-10.0)

    def test_plot_return_bars_replaces_non_finite_returns(self):
        chart = ReportChart()
        dates = [datetime(2024, 1, d) for d in range(1, 6)]
        values = [100.0, 0.0, 100.0, float("inf"), 90.0]

        fig = chart.plot_return_bars(dates, values, period="daily")

        assert fig is not None
        heights = [patch.get_height() for patch in fig.axes[0].patches]
        assert heights[0] == pytest.approx(-100.0)
        assert heights[1] == pytest.approx(0.0)
        assert heights[2] == pytest.approx(0.0)
        assert heights[3] == pytest.approx(0.0)


class TestMakeJsonSerializable:
    """Test _make_json_serializable with edge cases."""

    @pytest.fixture
    def generator(self):
        strategy = _make_strategy()
        return ReportGenerator(strategy)

    def test_nan_becomes_none(self, generator):
        assert generator._make_json_serializable(float("nan")) is None

    def test_inf_becomes_none(self, generator):
        assert generator._make_json_serializable(float("inf")) is None
        assert generator._make_json_serializable(float("-inf")) is None

    def test_normal_float_unchanged(self, generator):
        assert generator._make_json_serializable(3.14) == 3.14

    def test_datetime_to_isoformat(self, generator):
        dt = datetime(2024, 1, 15, 10, 30)
        result = generator._make_json_serializable(dt)
        assert result == "2024-01-15T10:30:00"

    def test_nested_dict(self, generator):
        data = {"a": float("nan"), "b": [1.0, float("inf")], "c": "text"}
        result = generator._make_json_serializable(data)
        assert result == {"a": None, "b": [1.0, None], "c": "text"}

    def test_object_with_dict_becomes_str(self, generator):
        class Custom:
            pass
        obj = Custom()
        result = generator._make_json_serializable(obj)
        assert isinstance(result, str)


class TestBuildContextNoInstanceState:
    """Verify _build_context receives user/memo as parameters, not from instance."""

    def test_user_memo_passed_through(self):
        strategy = _make_strategy()
        gen = ReportGenerator(strategy)

        ctx = gen._build_context(user="Alice", memo="Test note")
        assert ctx["user"] == "Alice"
        assert ctx["memo"] == "Test note"

    def test_no_user_memo(self):
        strategy = _make_strategy()
        gen = ReportGenerator(strategy)

        ctx = gen._build_context()
        assert ctx["user"] is None
        assert ctx["memo"] is None

    def test_no_state_leak_between_calls(self):
        strategy = _make_strategy()
        gen = ReportGenerator(strategy)

        ctx1 = gen._build_context(user="Alice", memo="First")
        ctx2 = gen._build_context(user="Bob", memo="Second")
        ctx3 = gen._build_context()

        assert ctx1["user"] == "Alice"
        assert ctx2["user"] == "Bob"
        assert ctx3["user"] is None
        # Verify no _user/_memo instance attribute leaking
        assert not hasattr(gen, "_user")

    def test_non_finite_values_are_sanitized(self):
        strategy = _make_strategy()
        gen = ReportGenerator(strategy)
        gen.calculator.get_all_metrics = MagicMock(return_value={
            "total_return": float("nan"),
            "annual_return": float("inf"),
        })
        gen.calculator.get_strategy_info = MagicMock(return_value={
            "strategy_name": "MockStrategy",
            "params": {},
        })
        gen.calculator.get_data_info = MagicMock(return_value={
            "data_name": "Data",
            "start_date": None,
            "end_date": None,
            "bars": 0,
        })
        gen.calculator.get_equity_curve = MagicMock(return_value=([], []))
        gen.calculator.get_buynhold_curve = MagicMock(return_value=([], []))

        ctx = gen._build_context(extra_metric=float("-inf"))

        assert ctx["total_return"] is None
        assert ctx["annual_return"] is None
        assert ctx["extra_metric"] is None
        assert not hasattr(gen, "_memo")
