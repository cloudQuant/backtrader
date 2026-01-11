#!/usr/bin/env python
"""Test module for Benchmark observer functionality.

This module contains tests for the Benchmark observer in Backtrader, which
compares strategy performance against a benchmark (typically buy-and-hold).
The test verifies that the observer is properly integrated and can track
benchmark data during strategy execution.
"""

import backtrader as bt

from . import testcommon


class RunStrategy(bt.Strategy):
    """A simple moving average crossover strategy with benchmark tracking.

    This strategy implements a basic trend-following approach using a 15-period
    Simple Moving Average (SMA). It buys when price crosses above the SMA and
    closes positions when price crosses below. A Benchmark observer is attached
    to compare performance against buy-and-hold.

    Attributes:
        sma: Simple Moving Average indicator with period 15.
        cross: CrossOver indicator tracking price vs SMA crossings.
    """
    def __init__(self):
        """Initialize the strategy with indicators and benchmark observer.

        Sets up the 15-period SMA indicator, CrossOver indicator for detecting
        price vs SMA crossings, and attaches a Benchmark observer to track
        buy-and-hold performance.
        """
        self.sma = bt.indicators.SMA(self.data, period=15)
        self.cross = bt.indicators.CrossOver(self.data.close, self.sma)
        # Add benchmark observer
        bt.observers.Benchmark(self.data)

    def next(self):
        """Execute trading logic for each bar.

        Implements a simple trend-following strategy:
        - If no position exists, buy when price crosses above SMA
        - If position exists, close when price crosses below SMA

        The CrossOver indicator returns:
        - Positive value (>0) when upward crossover occurs
        - Negative value (<0) when downward crossover occurs
        - Zero otherwise
        """
        if not self.position.size:
            if self.cross > 0.0:
                self.buy()
        elif self.cross < 0.0:
            self.close()


def test_run(main=False):
    """Run the Benchmark observer test.

    This test function verifies that the Benchmark observer is properly
    integrated with a Backtrader strategy. It creates a cerebro instance,
    adds test data, runs the RunStrategy, and asserts that the strategy
    executed successfully.

    Args:
        main (bool, optional): If True, enables plotting mode. When run as
            a script (main=True), the test can display results. Defaults to False.

    Raises:
        AssertionError: If the strategy did not execute any bars (len(strat) == 0).
    """
    datas = [testcommon.getdata(0)]
    cerebros = testcommon.runtest(datas, RunStrategy, plot=main)

    for cerebro in cerebros:
        strat = cerebro.runstrats[0][0]
        if main:
            # print('Benchmark observer test completed')  # Removed for performance
            pass
        # Verify the strategy ran successfully
        assert len(strat) > 0


if __name__ == "__main__":
    test_run(main=True)
