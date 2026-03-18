#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
"""Edge case unit tests for PerformanceCalculator contract consistency.

Tests cover:
- get_equity_curve with start_cash=0.0 (not silently replaced by 100000)
- get_pnl_metrics with start_cash=0 (division guard)
- get_risk_metrics with zero drawdown
- get_trade_metrics with zero closed trades
- get_kpi_metrics with missing analyzers
- sqn_to_rating boundary values
- _get_analyzer_result exact vs substring match
- get_strategy_info / get_data_info edge cases
- get_buynhold_curve with zero first_price
"""

import math
from unittest.mock import MagicMock, PropertyMock

import pytest

from backtrader.reports.performance import PerformanceCalculator


# ===========================================================================
# Helpers
# ===========================================================================


def _make_strategy(
    analyzers=None,
    broker_cash=100000.0,
    broker_value=110000.0,
    starting_cash=100000.0,
):
    """Create a minimal mock strategy for PerformanceCalculator."""
    strategy = MagicMock()
    strategy.__class__.__name__ = "TestStrategy"
    strategy.analyzers = analyzers or []
    strategy.broker = MagicMock()
    strategy.broker.startingcash = starting_cash
    strategy.broker.getvalue.return_value = broker_value
    # Remove data attribute by default (tests that need it add it)
    del strategy.data
    return strategy


def _make_analyzer(name, result):
    """Create a mock analyzer with given class name and result."""
    analyzer = MagicMock()
    analyzer.__class__.__name__ = name
    analyzer._name = ""
    analyzer.get_analysis.return_value = result
    return analyzer


# ===========================================================================
# P0: start_cash=0.0 truthy-or tests
# ===========================================================================


class TestStartCashZero:
    """Verify start_cash=0.0 is not silently replaced by 100000."""

    def test_get_pnl_metrics_with_zero_start_cash(self):
        """start_cash=0 should give rpl but skip total_return (div by zero guard)."""
        strategy = _make_strategy(starting_cash=0.0, broker_value=5000.0)
        calc = PerformanceCalculator(strategy)
        metrics = calc.get_pnl_metrics()

        assert metrics["start_cash"] == 0.0
        assert metrics["end_value"] == 5000.0
        assert metrics["rpl"] == 5000.0
        # total_return should be None because start_cash == 0
        assert metrics["total_return"] is None

    def test_get_equity_curve_timereturn_with_zero_cash(self):
        """Equity curve from TimeReturn should use start_cash=0, not 100000."""
        time_return_data = {1: 0.1, 2: 0.05, 3: -0.02}
        analyzer = _make_analyzer("TimeReturn", time_return_data)
        strategy = _make_strategy(
            analyzers=[analyzer],
            starting_cash=0.0,
            broker_value=0.0,
        )
        calc = PerformanceCalculator(strategy)
        dates, values = calc.get_equity_curve()

        # With start_cash=0.0, all cumulative values should be 0.0
        assert all(v == 0.0 for v in values)

    def test_get_equity_curve_timereturn_with_none_cash(self):
        """When _get_start_cash returns None, should fall back to 100000."""
        time_return_data = {1: 0.1}
        analyzer = _make_analyzer("TimeReturn", time_return_data)
        strategy = _make_strategy(analyzers=[analyzer], starting_cash=None)
        # _get_start_cash returns broker.startingcash which is None
        calc = PerformanceCalculator(strategy)
        dates, values = calc.get_equity_curve()

        # Should use fallback 100000 * 1.1 = 110000
        assert len(values) == 1
        assert values[0] == pytest.approx(110000.0)

    def test_get_equity_curve_skips_invalid_timereturn_values(self):
        """Invalid TimeReturn values should not poison the cumulative equity curve."""
        time_return_data = {
            1: 0.10,
            2: float("nan"),
            3: None,
            4: float("inf"),
            5: -0.05,
        }
        analyzer = _make_analyzer("TimeReturn", time_return_data)
        strategy = _make_strategy(
            analyzers=[analyzer],
            starting_cash=100000.0,
            broker_value=100000.0,
        )
        calc = PerformanceCalculator(strategy)
        dates, values = calc.get_equity_curve()

        assert dates == [1, 2, 3, 4, 5]
        assert values[0] == pytest.approx(110000.0)
        assert values[1] == pytest.approx(110000.0)
        assert values[2] == pytest.approx(110000.0)
        assert values[3] == pytest.approx(110000.0)
        assert values[4] == pytest.approx(104500.0)


# ===========================================================================
# get_risk_metrics edge cases
# ===========================================================================


class TestRiskMetrics:
    """Test risk metric calculation edge cases."""

    def test_zero_drawdown_skips_calmar(self):
        """Calmar ratio should be None when max_pct_drawdown is 0."""
        dd_analyzer = _make_analyzer("DrawDown", {"max": {"moneydown": 0.0, "drawdown": 0.0}})
        strategy = _make_strategy(
            analyzers=[dd_analyzer],
            starting_cash=100000.0,
            broker_value=110000.0,
        )
        calc = PerformanceCalculator(strategy)
        metrics = calc.get_risk_metrics(pnl_metrics={"annual_return": 10.0})

        assert metrics["max_pct_drawdown"] == 0.0
        assert metrics["calmar_ratio"] is None  # Division by zero guard

    def test_calmar_ratio_computed(self):
        """Calmar ratio = abs(annual_return / max_pct_drawdown)."""
        dd_analyzer = _make_analyzer("DrawDown", {"max": {"moneydown": 5000.0, "drawdown": 10.0}})
        strategy = _make_strategy(analyzers=[dd_analyzer])
        calc = PerformanceCalculator(strategy)
        metrics = calc.get_risk_metrics(pnl_metrics={"annual_return": 20.0})

        assert metrics["calmar_ratio"] == pytest.approx(2.0)

    def test_no_drawdown_analyzer(self):
        """All risk metrics should be None when no DrawDown analyzer is present."""
        strategy = _make_strategy(analyzers=[])
        calc = PerformanceCalculator(strategy)
        metrics = calc.get_risk_metrics()

        assert metrics["max_money_drawdown"] is None
        assert metrics["max_pct_drawdown"] is None
        assert metrics["calmar_ratio"] is None


# ===========================================================================
# get_trade_metrics edge cases
# ===========================================================================


class TestTradeMetrics:
    """Test trade metric edge cases."""

    def test_zero_closed_trades(self):
        """Win/loss percentages should be None when no trades are closed."""
        ta = _make_analyzer("TradeAnalyzer", {
            "total": {"total": 0, "closed": 0},
            "won": {"total": 0, "pnl": {}},
            "lost": {"total": 0, "pnl": {}},
        })
        strategy = _make_strategy(analyzers=[ta])
        calc = PerformanceCalculator(strategy)
        metrics = calc.get_trade_metrics()

        assert metrics["trades_closed"] == 0
        assert metrics["pct_winning"] is None
        assert metrics["pct_losing"] is None

    def test_all_winning_trades(self):
        """100% win rate scenario."""
        ta = _make_analyzer("TradeAnalyzer", {
            "total": {"total": 5, "closed": 5},
            "won": {"total": 5, "pnl": {"total": 5000.0, "average": 1000.0, "max": 2000.0}},
            "lost": {"total": 0, "pnl": {"total": 0.0, "average": 0.0, "max": 0.0}},
        })
        strategy = _make_strategy(analyzers=[ta])
        calc = PerformanceCalculator(strategy)
        metrics = calc.get_trade_metrics()

        assert metrics["pct_winning"] == pytest.approx(100.0)
        assert metrics["pct_losing"] == pytest.approx(0.0)

    def test_no_trade_analyzer(self):
        """Default values when no TradeAnalyzer is available."""
        strategy = _make_strategy(analyzers=[])
        calc = PerformanceCalculator(strategy)
        metrics = calc.get_trade_metrics()

        assert metrics["total_number_trades"] == 0
        assert metrics["trades_closed"] == 0


# ===========================================================================
# get_kpi_metrics edge cases
# ===========================================================================


class TestKpiMetrics:
    """Test KPI metric edge cases."""

    def test_missing_all_kpi_analyzers(self):
        """All KPI metrics should be None when analyzers are missing."""
        strategy = _make_strategy(analyzers=[])
        calc = PerformanceCalculator(strategy)
        metrics = calc.get_kpi_metrics()

        assert metrics["sharpe_ratio"] is None
        assert metrics["sqn_score"] is None
        assert metrics["sqn_human"] is None
        assert metrics["sortino_ratio"] is None

    def test_sqn_with_nan_score(self):
        """NaN SQN should produce 'N/A' rating."""
        sqn_analyzer = _make_analyzer("SQN", {"sqn": float("nan")})
        strategy = _make_strategy(analyzers=[sqn_analyzer])
        calc = PerformanceCalculator(strategy)
        metrics = calc.get_kpi_metrics()

        assert math.isnan(metrics["sqn_score"])
        assert metrics["sqn_human"] == "N/A"

    def test_sqn_with_none_score(self):
        """None SQN should produce 'N/A' rating."""
        sqn_analyzer = _make_analyzer("SQN", {"sqn": None})
        strategy = _make_strategy(analyzers=[sqn_analyzer])
        calc = PerformanceCalculator(strategy)
        metrics = calc.get_kpi_metrics()

        assert metrics["sqn_score"] is None
        assert metrics["sqn_human"] == "N/A"


# ===========================================================================
# sqn_to_rating boundary tests
# ===========================================================================


class TestSqnToRating:
    """Test SQN rating boundary values."""

    @pytest.mark.parametrize("score,expected", [
        (-1.0, "Poor"),
        (0.0, "Poor"),
        (1.59, "Poor"),
        (1.6, "Below Average"),
        (1.89, "Below Average"),
        (1.9, "Average"),
        (2.39, "Average"),
        (2.4, "Good"),
        (2.89, "Good"),
        (2.9, "Excellent"),
        (4.99, "Excellent"),
        (5.0, "Superb"),
        (6.89, "Superb"),
        (6.9, "Holy Grail"),
        (10.0, "Holy Grail"),
        (100.0, "Holy Grail"),
    ])
    def test_rating_boundaries(self, score, expected):
        assert PerformanceCalculator.sqn_to_rating(score) == expected

    def test_none_returns_na(self):
        assert PerformanceCalculator.sqn_to_rating(None) == "N/A"

    def test_nan_returns_na(self):
        assert PerformanceCalculator.sqn_to_rating(float("nan")) == "N/A"

    def test_inf_returns_holy_grail(self):
        assert PerformanceCalculator.sqn_to_rating(float("inf")) == "Holy Grail"

    def test_negative_inf_returns_poor(self):
        assert PerformanceCalculator.sqn_to_rating(float("-inf")) == "Poor"


# ===========================================================================
# _get_analyzer_result exact vs substring match
# ===========================================================================


class TestAnalyzerLookup:
    """Test analyzer name matching priority."""

    def test_exact_match_takes_priority(self):
        """Exact class name match should win over substring match."""
        exact = _make_analyzer("SharpeRatio", {"sharperatio": 1.5})
        substring = _make_analyzer("SharpeRatioStats", {"sharperatio": 2.5})
        strategy = _make_strategy(analyzers=[substring, exact])
        calc = PerformanceCalculator(strategy)

        result = calc._get_analyzer_result("sharperatio")
        assert result == {"sharperatio": 1.5}

    def test_substring_fallback(self):
        """When no exact match, substring should work."""
        analyzer = _make_analyzer("AnnualReturn", {"annualreturn": 0.1})
        strategy = _make_strategy(analyzers=[analyzer])
        calc = PerformanceCalculator(strategy)

        result = calc._get_analyzer_result("return")
        assert result == {"annualreturn": 0.1}

    def test_no_match_returns_none(self):
        """Missing analyzer should return None."""
        strategy = _make_strategy(analyzers=[])
        calc = PerformanceCalculator(strategy)

        assert calc._get_analyzer_result("nonexistent") is None

    def test_custom_name_match(self):
        """Analyzer with custom _name attribute should be matched."""
        analyzer = _make_analyzer("SomeClass", {"value": 42})
        analyzer._name = "myanalyzer"
        strategy = _make_strategy(analyzers=[analyzer])
        calc = PerformanceCalculator(strategy)

        result = calc._get_analyzer_result("myanalyzer")
        assert result == {"value": 42}

    def test_non_string_custom_name_is_ignored(self):
        """Non-string analyzer _name should not break lookup."""
        analyzer = _make_analyzer("SharpeRatio", {"sharperatio": 1.2})
        analyzer._name = None
        strategy = _make_strategy(analyzers=[analyzer])
        calc = PerformanceCalculator(strategy)

        result = calc._get_analyzer_result("sharperatio")
        assert result == {"sharperatio": 1.2}


# ===========================================================================
# get_strategy_info / get_data_info edge cases
# ===========================================================================


class TestStrategyInfo:
    """Test strategy info extraction edge cases."""

    def test_no_params(self):
        """Strategy without params attribute."""
        strategy = MagicMock(spec=[])
        strategy.__class__.__name__ = "EmptyStrategy"
        strategy.analyzers = []
        strategy.broker = None
        calc = PerformanceCalculator(strategy)
        info = calc.get_strategy_info()

        assert info["strategy_name"] == "EmptyStrategy"
        assert info["params"] == {}

    def test_data_info_no_data(self):
        """Strategy without data attribute."""
        strategy = MagicMock(spec=[])
        strategy.__class__.__name__ = "NoData"
        strategy.analyzers = []
        strategy.broker = None
        calc = PerformanceCalculator(strategy)
        info = calc.get_data_info()

        assert info["data_name"] is None
        assert info["bars"] == 0


# ===========================================================================
# get_pnl_metrics profit_factor edge cases
# ===========================================================================


class TestProfitFactor:
    """Test profit factor calculation edge cases."""

    def test_zero_losses_no_profit_factor(self):
        """Profit factor should be None when lost_trades total is 0."""
        ta = _make_analyzer("TradeAnalyzer", {
            "total": {"total": 5, "closed": 5},
            "won": {"total": 5, "pnl": {"total": 5000.0}},
            "lost": {"total": 0, "pnl": {"total": 0.0}},
            "pnl": {"net": {"total": 5000.0}},
        })
        strategy = _make_strategy(analyzers=[ta])
        calc = PerformanceCalculator(strategy)
        metrics = calc.get_pnl_metrics()

        # result_lost_trades == 0 → profit_factor stays None
        assert metrics["profit_factor"] is None

    def test_normal_profit_factor(self):
        """Profit factor = abs(won / lost)."""
        ta = _make_analyzer("TradeAnalyzer", {
            "total": {"total": 10, "closed": 10},
            "won": {"total": 6, "pnl": {"total": 6000.0}},
            "lost": {"total": 4, "pnl": {"total": -3000.0}},
            "pnl": {"net": {"total": 3000.0}},
        })
        strategy = _make_strategy(analyzers=[ta])
        calc = PerformanceCalculator(strategy)
        metrics = calc.get_pnl_metrics()

        assert metrics["profit_factor"] == pytest.approx(2.0)


# ===========================================================================
# broker access safety regressions
# ===========================================================================


class TestBrokerAccessFailures:
    """Test broker access failures degrade gracefully."""

    def test_get_pnl_metrics_handles_broker_getvalue_failure(self, caplog):
        """Broker getvalue failure should not crash PnL metric calculation."""
        strategy = _make_strategy()
        strategy.broker.getvalue.side_effect = RuntimeError("broker offline")
        calc = PerformanceCalculator(strategy)

        with caplog.at_level("DEBUG"):
            metrics = calc.get_pnl_metrics()

        assert metrics["start_cash"] == 100000.0
        assert metrics["end_value"] is None
        assert metrics["rpl"] is None
        assert any("Failed to get end value" in record.message for record in caplog.records)

    def test_get_pnl_metrics_skips_invalid_broker_values(self, caplog):
        """NaN/inf broker values should not poison rpl or total_return."""
        strategy = _make_strategy(starting_cash=float("nan"), broker_value=float("inf"))
        calc = PerformanceCalculator(strategy)

        with caplog.at_level("DEBUG"):
            metrics = calc.get_pnl_metrics()

        assert math.isnan(metrics["start_cash"])
        assert math.isinf(metrics["end_value"])
        assert metrics["rpl"] is None
        assert metrics["total_return"] is None
        assert any(
            "Skipping basic PnL metric calculation for invalid broker values" in record.message
            for record in caplog.records
        )

    def test_get_equity_curve_handles_startingcash_access_failure(self, caplog):
        """Starting cash access failure should fall back to the default curve base."""
        analyzer = _make_analyzer("TimeReturn", {1: 0.1})

        class BrokenBroker:
            @property
            def startingcash(self):
                raise RuntimeError("cash unavailable")

            def getvalue(self):
                return 110000.0

        strategy = _make_strategy(analyzers=[analyzer])
        strategy.broker = BrokenBroker()
        calc = PerformanceCalculator(strategy)

        with caplog.at_level("DEBUG"):
            dates, values = calc.get_equity_curve()

        assert dates == [1]
        assert values == pytest.approx([110000.0])
        assert any("Failed to get starting cash" in record.message for record in caplog.records)


class TestBuyAndHoldCurveEdgeCases:
    """Test get_buynhold_curve edge cases."""

    def test_get_buynhold_curve_skips_invalid_open_prices(self):
        """Invalid open prices should not poison the normalized buy-and-hold curve."""

        class _Line:
            def __init__(self, values):
                self._values = list(values)

            def __getitem__(self, idx):
                return self._values[idx]

        class _Data:
            def __init__(self):
                self.datetime = _Line([1.0, 2.0, 3.0, 4.0, 5.0])
                self.open = _Line([100.0, float("nan"), None, float("inf"), 110.0])

            def __len__(self):
                return 5

        strategy = _make_strategy()
        strategy.data = _Data()
        calc = PerformanceCalculator(strategy)
        dates, values = calc.get_buynhold_curve()

        assert len(dates) == 5
        assert values[0] == pytest.approx(100.0)
        assert values[1] == pytest.approx(100.0)
        assert values[2] == pytest.approx(100.0)
        assert values[3] == pytest.approx(100.0)
        assert values[4] == pytest.approx(90.9090909090909)
