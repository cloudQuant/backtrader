#!/usr/bin/env python
"""Tests for the TradeAnalyzer.

This module contains tests for the TradeAnalyzer, which provides comprehensive
statistics about trades executed during a backtesting session, including:

* Total number of trades (open and closed)
* Win/loss statistics
* Streak information (winning and losing streaks)
* Profit and loss metrics

The test strategy uses a simple SMA crossover system to generate trades
for analysis by the TradeAnalyzer.
"""

import backtrader as bt

from . import testcommon


class RunStrategy(bt.Strategy):
    """A simple SMA crossover trading strategy for testing the TradeAnalyzer.

    This strategy generates buy signals when price crosses above the SMA
    and exits positions when price crosses below the SMA. This creates
    a series of trades that can be analyzed by the TradeAnalyzer.

    Attributes:
        sma: Simple Moving Average indicator with period 15.
        cross: CrossOver indicator that tracks when price crosses the SMA.

    Notes:
        * The strategy enters long only (no short selling)
        * One position max (closes before entering new position)
        * Uses default order sizes and commission structure
    """

    def __init__(self):
        """Initialize the strategy with indicators.

        Sets up the SMA and CrossOver indicators that will drive
        the trading logic in the next() method.
        """
        self.sma = bt.indicators.SMA(self.data, period=15)
        self.cross = bt.indicators.CrossOver(self.data.close, self.sma)

    def next(self):
        """Execute trading logic for each bar.

        The trading logic is:
        1. If not in a position, buy when price crosses above SMA
        2. If in a position, close when price crosses below SMA

        This creates a simple trend-following system that generates
        trades for the TradeAnalyzer to analyze.
        """
        if not self.position.size:
            if self.cross > 0.0:
                self.buy()
        elif self.cross < 0.0:
            self.close()


def test_run(main=False):
    """Run the TradeAnalyzer test.

    This test function:
    1. Creates a Cerebro instance with test data
    2. Attaches the RunStrategy and TradeAnalyzer
    3. Runs the backtest
    4. Validates the analyzer output structure and values

    Args:
        main (bool, optional): If True, runs in standalone mode with
            printed output. If False, runs assertions for automated
            testing. Defaults to False.

    Asserts (when main=False):
        * Analysis result is a dictionary
        * 'total' key exists in analysis
        * Total trades equals expected value (12)
        * Closed trades equals expected value (11)
        * Won trades equals expected value (5)
        * Lost trades equals expected value (6)

    Notes:
        The expected values are based on actual test runs with the
        provided test data. These values may change if the test data
        or strategy parameters are modified.
    """
    datas = [testcommon.getdata(0)]
    cerebros = testcommon.runtest(
        datas, RunStrategy, plot=main, analyzer=(bt.analyzers.TradeAnalyzer, {})
    )

    for cerebro in cerebros:
        strat = cerebro.runstrats[0][0]
        analyzer = strat.analyzers[0]
        analysis = analyzer.get_analysis()
        if main:
            # Standalone mode - print results for inspection
            pass
            print(analysis)
        else:
            # Automated testing mode - verify results
            assert isinstance(analysis, dict)
            assert "total" in analysis
            # Verify total trades from actual run
            assert hasattr(analysis.total, "total")
            expected_total = 12  # From actual run
            assert analysis.total.total == expected_total
            # Verify closed trades
            assert hasattr(analysis.total, "closed")
            assert analysis.total.closed == 11  # From actual run
            # Verify won/lost statistics
            assert "won" in analysis
            assert "lost" in analysis
            assert analysis.won.total == 5  # From actual run
            assert analysis.lost.total == 6  # From actual run


if __name__ == "__main__":
    test_run(main=True)
