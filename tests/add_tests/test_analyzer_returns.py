#!/usr/bin/env python
"""Test module for the Returns analyzer in Backtrader.

This module contains tests for the bt.analyzers.Returns analyzer, which calculates
various return metrics for trading strategies including total return, average return,
and normalized return metrics.

The test strategy uses a Simple Moving Average (SMA) crossover system to generate
trades, and the analyzer verifies that the returns are calculated correctly.
"""

import backtrader as bt

from . import testcommon


class RunStrategy(bt.Strategy):
    """A simple moving average crossover trading strategy.

    This strategy uses a 15-period Simple Moving Average (SMA) and generates
    buy/sell signals based on price crossovers with the SMA.

    Attributes:
        sma (bt.indicators.SMA): The 15-period simple moving average indicator.
        cross (bt.indicators.CrossOver): Crossover indicator detecting when price
            crosses above (bullish) or below (bearish) the SMA.
    """

    def __init__(self):
        """Initialize the strategy with SMA and crossover indicators.

        Sets up a 15-period SMA on the close price and a crossover indicator
        to detect when the close price crosses above or below the SMA.
        """
        self.sma = bt.indicators.SMA(self.data, period=15)
        self.cross = bt.indicators.CrossOver(self.data.close, self.sma)

    def next(self):
        """Execute trading logic for the current bar.

        Implements a simple trend-following strategy:
        - If no position exists, buy when price crosses above SMA (bullish signal)
        - If a position exists, close it when price crosses below SMA (bearish signal)

        The strategy only holds long positions and exits when the trend reverses.
        """
        if not self.position.size:
            if self.cross > 0.0:
                self.buy()
        elif self.cross < 0.0:
            self.close()


def test_run(main=False):
    """Run the Returns analyzer test.

    This test executes the RunStrategy with the Returns analyzer attached
    and verifies that the analyzer correctly calculates return metrics.

    The test validates:
    - Total return (rtot)
    - Average return (ravg)
    - Normalized return (rnorm)
    - Normalized return as percentage (rnorm100)

    Args:
        main (bool, optional): If True, run in verbose mode and print results.
            If False (default), run in test mode and assert expected values.
            Defaults to False.

    Raises:
        AssertionError: If any of the expected return metrics are missing or
            if the calculated values deviate significantly from expected values.

    Returns:
        None: This function performs assertions but does not return a value.
    """
    datas = [testcommon.getdata(0)]
    cerebros = testcommon.runtest(
        datas, RunStrategy, plot=main, analyzer=(bt.analyzers.Returns, {})
    )

    for cerebro in cerebros:
        strat = cerebro.runstrats[0][0]
        analyzer = strat.analyzers[0]
        analysis = analyzer.get_analysis()
        if main:
            # print('Returns Analysis:')  # Removed for performance
            pass
            print(analysis)
        else:
            assert isinstance(analysis, dict)
            # Check for expected keys
            assert "rtot" in analysis
            assert "ravg" in analysis
            assert "rnorm" in analysis
            # Verify actual values from run
            expected_rtot = 0.028013920205183424
            assert abs(analysis["rtot"] - expected_rtot) < 0.01
            # Verify rnorm100 is percentage form
            assert "rnorm100" in analysis
            assert abs(analysis["rnorm100"] - 2.807111707414246) < 0.1


if __name__ == "__main__":
    test_run(main=True)
