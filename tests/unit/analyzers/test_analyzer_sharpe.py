#!/usr/bin/env python
"""Test module for Sharpe Ratio analyzer.

This module contains test cases for the Sharpe Ratio analyzer in backtrader.
The Sharpe Ratio is a measure of risk-adjusted return that calculates the
excess return per unit of risk (standard deviation).

Example:
    Run the test directly:
    $ python test_analyzer_sharpe.py

    Or run via pytest:
    $ pytest tests/add_tests/test_analyzer_sharpe.py -v
"""

import backtrader as bt
import pytest
from types import SimpleNamespace
from unittest.mock import patch

import testcommon


class RunStrategy(bt.Strategy):
    """A simple moving average crossover strategy for testing Sharpe Ratio analyzer.

    This strategy uses a Simple Moving Average (SMA) crossover signal to generate
    buy and sell signals. It buys when price crosses above the SMA and closes
    the position when price crosses below the SMA.

    Attributes:
        sma: Simple Moving Average indicator with 15-period window.
        cross: Crossover indicator tracking price vs SMA crossings.
    """

    def __init__(self):
        """Initialize the strategy with indicators.

        Sets up a 15-period Simple Moving Average (SMA) and a crossover
        indicator to detect when the closing price crosses the SMA.
        """
        self.sma = bt.indicators.SMA(self.data, period=15)
        self.cross = bt.indicators.CrossOver(self.data.close, self.sma)

    def next(self):
        """Execute trading logic on each bar.

        Implements a simple trend-following strategy:
        - If no position exists, buy when price crosses above SMA
        - If position exists, close it when price crosses below SMA

        This creates long-only trades that capture upward price movements.
        """
        if not self.position.size:
            if self.cross > 0.0:
                self.buy()
        elif self.cross < 0.0:
            self.close()


def _build_nonlegacy_sharpe_analyzer(**overrides):
    analyzer = bt.analyzers.SharpeRatio.__new__(bt.analyzers.SharpeRatio)
    params = dict(
        legacyannual=False,
        riskfreerate=0.0,
        timeframe=bt.TimeFrame.Years,
        daysfactor=None,
        factor=None,
        convertrate=True,
        annualize=False,
        stddev_sample=False,
    )
    params.update(overrides)
    analyzer.p = SimpleNamespace(**params)
    analyzer.timereturn = SimpleNamespace(get_analysis=lambda: {"a": 0.05, "b": 0.1})
    analyzer.rets = {}
    return analyzer


def test_run(main=False):
    """Run Sharpe Ratio analyzer test.

    This function tests the Sharpe Ratio analyzer by running a simple moving
    average crossover strategy and verifying that the analyzer produces valid
    output. The test checks that the analysis dictionary contains the expected
    'sharperatio' key with a valid value.

    Args:
        main (bool): If True, run in standalone mode and print analysis results.
            If False (default), run in test mode and perform assertions.

    Raises:
        AssertionError: If the analysis output is not a dictionary, does not
            contain 'sharperatio' key, or contains invalid value types when
            running in test mode (main=False).

    Note:
        The Sharpe Ratio may be None for short test periods or when there is
        no variance in returns. This is expected behavior and the test accounts
        for it by accepting None as a valid value.
    """
    datas = [testcommon.getdata(0)]
    cerebros = testcommon.runtest(
        datas, RunStrategy, plot=main, analyzer=(bt.analyzers.SharpeRatio, {})
    )

    for cerebro in cerebros:
        strat = cerebro.runstrats[0][0]
        analyzer = strat.analyzers[0]
        analysis = analyzer.get_analysis()
        if main:
            # print('SharpeRatio Analysis:')  # Removed for performance
            pass
            print(analysis)
        else:
            assert isinstance(analysis, dict)
            assert "sharperatio" in analysis
            # SharpeRatio may be None for short periods or no variance
            # Just verify it exists and is a valid type
            assert analysis["sharperatio"] is None or isinstance(
                analysis["sharperatio"], (int, float)
            )


def test_legacyannual_zero_variance_returns_none():
    analyzer = bt.analyzers.SharpeRatio.__new__(bt.analyzers.SharpeRatio)
    analyzer.p = SimpleNamespace(legacyannual=True, riskfreerate=0.0)
    analyzer.anret = SimpleNamespace(rets=[0.1, 0.1])
    analyzer.rets = {}

    with patch.object(type(analyzer).__mro__[1], "stop", return_value=None):
        analyzer.stop()

    assert analyzer.rets["sharperatio"] is None


def test_legacyannual_nan_returns_none():
    analyzer = bt.analyzers.SharpeRatio.__new__(bt.analyzers.SharpeRatio)
    analyzer.p = SimpleNamespace(legacyannual=True, riskfreerate=0.0)
    analyzer.anret = SimpleNamespace(rets=[float("nan"), 0.1])
    analyzer.rets = {}

    with patch.object(type(analyzer).__mro__[1], "stop", return_value=None):
        analyzer.stop()

    assert analyzer.rets["sharperatio"] is None


@pytest.mark.parametrize("riskfreerate", ["bad", complex(0.01, 0.01)])
def test_legacyannual_invalid_riskfreerate_returns_none(riskfreerate):
    analyzer = bt.analyzers.SharpeRatio.__new__(bt.analyzers.SharpeRatio)
    analyzer.p = SimpleNamespace(legacyannual=True, riskfreerate=riskfreerate)
    analyzer.anret = SimpleNamespace(rets=[0.1, 0.2])
    analyzer.rets = {}

    with patch.object(type(analyzer).__mro__[1], "stop", return_value=None):
        analyzer.stop()

    assert analyzer.rets["sharperatio"] is None


@pytest.mark.parametrize("returns", [["bad", 0.1], [complex(0.1, 0.1), 0.1]])
def test_legacyannual_invalid_returns_none(returns):
    analyzer = bt.analyzers.SharpeRatio.__new__(bt.analyzers.SharpeRatio)
    analyzer.p = SimpleNamespace(legacyannual=True, riskfreerate=0.0)
    analyzer.anret = SimpleNamespace(rets=returns)
    analyzer.rets = {}

    with patch.object(type(analyzer).__mro__[1], "stop", return_value=None):
        analyzer.stop()

    assert analyzer.rets["sharperatio"] is None


def test_nonlegacy_nan_returns_none():
    analyzer = _build_nonlegacy_sharpe_analyzer()
    analyzer.timereturn = SimpleNamespace(get_analysis=lambda: {"a": float("nan"), "b": 0.1})

    with patch.object(type(analyzer).__mro__[1], "stop", return_value=None):
        analyzer.stop()

    assert analyzer.rets["sharperatio"] is None


@pytest.mark.parametrize("riskfreerate", ["bad", complex(0.01, 0.01)])
def test_nonlegacy_invalid_riskfreerate_returns_none(riskfreerate):
    analyzer = _build_nonlegacy_sharpe_analyzer(riskfreerate=riskfreerate)

    with patch.object(type(analyzer).__mro__[1], "stop", return_value=None):
        analyzer.stop()

    assert analyzer.rets["sharperatio"] is None


@pytest.mark.parametrize("returns", [["bad", 0.1], [complex(0.1, 0.1), 0.1]])
def test_nonlegacy_invalid_returns_none(returns):
    analyzer = _build_nonlegacy_sharpe_analyzer()
    analyzer.timereturn = SimpleNamespace(get_analysis=lambda: {"a": returns[0], "b": returns[1]})

    with patch.object(type(analyzer).__mro__[1], "stop", return_value=None):
        analyzer.stop()

    assert analyzer.rets["sharperatio"] is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"factor": 0},
        {"factor": -2},
        {"factor": float("nan")},
        {"timeframe": bt.TimeFrame.Days, "daysfactor": 0},
        {"timeframe": bt.TimeFrame.Days, "daysfactor": -5},
        {"timeframe": bt.TimeFrame.Days, "daysfactor": float("nan")},
    ],
)
def test_nonlegacy_invalid_factor_inputs_return_none(overrides):
    analyzer = _build_nonlegacy_sharpe_analyzer(**overrides)

    with patch.object(type(analyzer).__mro__[1], "stop", return_value=None):
        analyzer.stop()

    assert analyzer.rets["sharperatio"] is None


def test_nonlegacy_invalid_riskfreerate_conversion_returns_none():
    analyzer = _build_nonlegacy_sharpe_analyzer(timeframe=bt.TimeFrame.Days, factor=252, riskfreerate=-2.0)

    with patch.object(type(analyzer).__mro__[1], "stop", return_value=None):
        analyzer.stop()

    assert analyzer.rets["sharperatio"] is None


if __name__ == "__main__":
    test_run(main=True)
