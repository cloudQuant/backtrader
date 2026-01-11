#!/usr/bin/env python
"""Test module for the TotalValue analyzer.

This module contains tests for the TotalValue analyzer, which tracks and records
the portfolio's total value (cash + positions) over time during backtesting.
The analyzer is essential for understanding how portfolio value evolves
throughout a trading strategy's execution.

Example:
    Run the test with plotting::

        python test_analyzer_total_value.py

    Or run without plotting as part of the test suite::

        pytest tests/add_tests/test_analyzer_total_value.py
"""

import backtrader as bt

from . import testcommon


class RunStrategy(bt.Strategy):
    """A simple moving average crossover trading strategy.

    This strategy uses a Simple Moving Average (SMA) crossover system to generate
    buy and sell signals. It buys when price crosses above the SMA and closes
    the position when price crosses below the SMA.

    Attributes:
        sma: Simple Moving Average indicator with period of 15 bars.
        cross: Crossover indicator tracking when price crosses the SMA.
    """

    def __init__(self):
        """Initialize the strategy with indicators.

        Sets up the SMA indicator and crossover signal generator that will
        be used to make trading decisions in the next() method.
        """
        self.sma = bt.indicators.SMA(self.data, period=15)
        self.cross = bt.indicators.CrossOver(self.data.close, self.sma)

    def next(self):
        """Execute trading logic for each bar.

        Implements a simple trend-following strategy:
        - If no position exists, buy when price crosses above SMA
        - If position exists, close it when price crosses below SMA

        The crossover indicator returns positive values for upward crossovers
        and negative values for downward crossovers.
        """
        if not self.position.size:
            if self.cross > 0.0:
                self.buy()
        elif self.cross < 0.0:
            self.close()


def test_run(main=False):
    """Run the TotalValue analyzer test.

    This test function validates that the TotalValue analyzer correctly records
    portfolio value over time during strategy execution. It verifies that:
    - The analyzer returns a dictionary
    - The dictionary contains value recordings
    - All recorded values are positive

    Args:
        main (bool): If True, runs in standalone mode with plotting and prints
            analysis results. If False, runs assertions for automated testing.
            Defaults to False.

    Returns:
        None: This function performs assertions and prints results but does
        not return a value.

    Raises:
        AssertionError: If the analysis is not a dictionary, is empty, or
            contains non-positive portfolio values.
    """
    datas = [testcommon.getdata(0)]
    cerebros = testcommon.runtest(
        datas, RunStrategy, plot=main, analyzer=(bt.analyzers.TotalValue, {})
    )

    for cerebro in cerebros:
        strat = cerebro.runstrats[0][0]
        analyzer = strat.analyzers[0]
        analysis = analyzer.get_analysis()
        if main:
            # print('TotalValue Analysis:')  # Removed for performance
            pass
            print(analysis)
        else:
            assert isinstance(analysis, dict)
            # TotalValue should record portfolio value over time
            assert len(analysis) > 0  # Should have value recordings
            # All values should be positive
            for dt, value in analysis.items():
                assert value > 0, f"Portfolio value {value} should be positive"


if __name__ == "__main__":
    test_run(main=True)
