#!/usr/bin/env python
"""Test module for the LogReturns observer in backtrader.

This module contains tests to verify that the LogReturns observer works correctly
within a backtrader strategy. The LogReturns observer tracks the logarithmic
returns of the portfolio value over time, which is useful for analyzing
compound growth and performance metrics.

The test uses a simple moving average crossover strategy to generate trades
and verify that the LogReturns observer can be instantiated and updated
properly during backtesting.
"""

import backtrader as bt

from . import testcommon


class RunStrategy(bt.Strategy):
    """A simple moving average crossover strategy for testing LogReturns observer.

    This strategy implements a basic trend-following approach:
    - Uses a 15-period Simple Moving Average (SMA)
    - Generates buy signals when price crosses above the SMA
    - Exits positions when price crosses below the SMA
    - Includes a LogReturns observer to track portfolio logarithmic returns

    Attributes:
        sma: Simple Moving Average indicator with 15-period lookback.
        cross: CrossOver indicator tracking price vs SMA crossovers.
    """

    def __init__(self):
        """Initialize the strategy with indicators and observers.

        Sets up:
        - 15-period SMA indicator on the close price
        - CrossOver indicator to detect when price crosses the SMA
        - LogReturns observer to track logarithmic returns of the portfolio
        """
        self.sma = bt.indicators.SMA(self.data, period=15)
        self.cross = bt.indicators.CrossOver(self.data.close, self.sma)
        # Add LogReturns observer
        bt.observers.LogReturns()

    def next(self):
        """Execute trading logic for each bar.

        Implements a simple crossover strategy:
        - Enter long when price crosses above SMA (cross > 0)
        - Close position when price crosses below SMA (cross < 0)

        The strategy only holds one position at a time and will not
        re-enter if already in a position.
        """
        if not self.position.size:
            if self.cross > 0.0:
                self.buy()
        elif self.cross < 0.0:
            self.close()


def test_run(main=False):
    """Run the LogReturns observer test.

    This test function verifies that the LogReturns observer works correctly
    by running a simple SMA crossover strategy and checking that the strategy
    executes successfully with the observer attached.

    Args:
        main (bool, optional): If True, enables plotting mode. Defaults to False.
            When False, runs in headless mode for automated testing.

    Raises:
        AssertionError: If the strategy did not run (len(strat) == 0).
            This ensures the backtest executed properly.

    Note:
        The test uses data from testcommon.getdata(0) and runs the strategy
        through the standard testcommon.runtest() infrastructure. Multiple
        cerebro instances may be returned (e.g., for different data modes),
        and each is verified independently.
    """
    datas = [testcommon.getdata(0)]
    cerebros = testcommon.runtest(datas, RunStrategy, plot=main)

    for cerebro in cerebros:
        strat = cerebro.runstrats[0][0]
        if main:
            # print('LogReturns observer test completed')  # Removed for performance
            pass
        # Verify the strategy ran successfully
        assert len(strat) > 0


if __name__ == "__main__":
    test_run(main=True)
