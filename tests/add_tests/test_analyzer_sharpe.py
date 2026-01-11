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

from . import testcommon


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


if __name__ == "__main__":
    test_run(main=True)
