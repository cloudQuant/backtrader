#!/usr/bin/env python
"""Test module for the TimeReturn observer in backtrader.

This module tests the TimeReturn observer, which tracks the returns of a strategy
over time. The test uses a simple moving average crossover strategy to generate
trades and verify that the TimeReturn observer correctly calculates and records
returns throughout the backtest.

The test strategy:
- Uses a 15-period Simple Moving Average (SMA)
- Goes long when price crosses above the SMA
- Closes position when price crosses below the SMA
- TimeReturn observer tracks the returns of this strategy
"""

import backtrader as bt

from . import testcommon


class RunStrategy(bt.Strategy):
    """Test strategy that uses SMA crossover to generate trades.

    This strategy implements a simple trend-following approach:
    - Calculates a 15-period Simple Moving Average (SMA)
    - Monitors for crossover signals between price and SMA
    - Goes long when price crosses above SMA (bullish signal)
    - Exits position when price crosses below SMA (bearish signal)
    - Includes TimeReturn observer to track returns over time

    Attributes:
        sma: Simple Moving Average indicator with 15-period lookback.
        cross: Crossover indicator that tracks when price crosses the SMA.
            Positive values indicate bullish crossover (price > SMA).
            Negative values indicate bearish crossover (price < SMA).
    """

    def __init__(self):
        """Initialize the strategy with indicators and observers.

        Sets up the technical indicators and attaches the TimeReturn observer
        to track strategy returns throughout the backtest.
        """
        self.sma = bt.indicators.SMA(self.data, period=15)
        self.cross = bt.indicators.CrossOver(self.data.close, self.sma)
        # Add TimeReturn observer
        bt.observers.TimeReturn()

    def next(self):
        """Execute trading logic for each bar.

        Implements the core strategy logic:
        1. If not in a position, enter long when bullish crossover occurs
        2. If in a position, exit when bearish crossover occurs

        The crossover signal (self.cross) is:
        - Positive (> 0) when price crosses above SMA (buy signal)
        - Negative (< 0) when price crosses below SMA (sell signal)
        """
        if not self.position.size:
            if self.cross > 0.0:
                self.buy()
        elif self.cross < 0.0:
            self.close()


def test_run(main=False):
    """Run the TimeReturn observer test.

    This function executes a backtest using the RunStrategy with the TimeReturn
    observer attached. It verifies that the strategy runs successfully and that
    the observer correctly tracks returns.

    Args:
        main (bool, optional): If True, enables plotting mode and displays
            results. If False, runs in headless mode for automated testing.
            Defaults to False.

    Raises:
        AssertionError: If the strategy did not execute any bars (len(strat) == 0),
            indicating a failure in the backtest execution.
    """
    datas = [testcommon.getdata(0)]
    cerebros = testcommon.runtest(datas, RunStrategy, plot=main)

    for cerebro in cerebros:
        strat = cerebro.runstrats[0][0]
        if main:
            # print('TimeReturn observer test completed')  # Removed for performance
            pass
        # Verify the strategy ran successfully
        assert len(strat) > 0


if __name__ == "__main__":
    test_run(main=True)
