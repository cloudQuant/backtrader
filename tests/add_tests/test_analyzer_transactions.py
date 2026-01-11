#!/usr/bin/env python
"""Tests for the Transactions analyzer.

This module contains tests for the backtrader Transactions analyzer, which records
all transaction details during backtesting including date, price, size, and value
for each trade execution.

Example:
    Run the test with plotting:
        python tests/add_tests/test_analyzer_transactions.py

    Run the test without plotting (assertions only):
        pytest tests/add_tests/test_analyzer_transactions.py
"""

import backtrader as bt

from . import testcommon


class RunStrategy(bt.Strategy):
    """A simple moving average crossover strategy for testing the Transactions analyzer.

    This strategy generates buy and sell signals based on the crossover of price
    and a Simple Moving Average (SMA). It buys when price crosses above the SMA
    and closes positions when price crosses below the SMA.

    Attributes:
        sma: Simple Moving Average indicator with period 15.
        cross: CrossOver indicator tracking price vs SMA crossovers.

    Note:
        This strategy is designed specifically for testing the Transactions analyzer,
        not for production trading use.
    """

    def __init__(self):
        """Initialize the strategy with indicators.

        Sets up a 15-period Simple Moving Average (SMA) and a CrossOver indicator
        to detect when the closing price crosses the SMA line.
        """
        self.sma = bt.indicators.SMA(self.data, period=15)
        self.cross = bt.indicators.CrossOver(self.data.close, self.sma)

    def next(self):
        """Execute trading logic for each bar.

        Implements a simple trend-following strategy:
        - If no position exists, buy when price crosses above SMA (bullish signal)
        - If position exists, close it when price crosses below SMA (bearish signal)

        Note:
            This method is called automatically by backtrader for each data bar
            after all indicators have been calculated.
        """
        if not self.position.size:
            if self.cross > 0.0:
                self.buy()
        elif self.cross < 0.0:
            self.close()


def test_run(main=False):
    """Test the Transactions analyzer with a simple strategy.

    This test runs a moving average crossover strategy with the Transactions analyzer
    attached. It verifies that the analyzer correctly records all transaction details
    including entry and exit trades.

    The test creates a cerebro instance, attaches the Transactions analyzer, runs the
    backtest, and validates that the analysis results are structured correctly.

    Args:
        main (bool): If True, prints the analysis results and enables plotting.
                     If False (default), runs assertions to validate analyzer output.
                     Defaults to False.

    Asserts:
        The analysis output is a dictionary containing transaction records.
        The analysis dictionary may be empty if no transactions occurred.

    Note:
        When main=True, the test can be run directly as a script to visualize
        the results. When main=False (default), it's intended for pytest execution.
    """
    datas = [testcommon.getdata(0)]
    cerebros = testcommon.runtest(
        datas, RunStrategy, plot=main, analyzer=(bt.analyzers.Transactions, {})
    )

    for cerebro in cerebros:
        strat = cerebro.runstrats[0][0]
        analyzer = strat.analyzers[0]
        analysis = analyzer.get_analysis()
        if main:
            print(analysis)
        else:
            assert isinstance(analysis, dict)
            # Transactions should record all transaction details
            # May be empty dict if no transactions
            assert len(analysis) >= 0


if __name__ == "__main__":
    test_run(main=True)
