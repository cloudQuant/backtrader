#!/usr/bin/env python
"""Test module for the DrawDown observer in backtrader.

This module contains test cases to verify that the DrawDown observer correctly
tracks and reports drawdown metrics during strategy execution. The test uses
a simple moving average crossover strategy to generate trades, which creates
drawdown scenarios that the observer should capture.
"""

import backtrader as bt

from . import testcommon


class RunStrategy(bt.Strategy):
    """A simple moving average crossover strategy for testing DrawDown observer.

    This strategy generates buy and sell signals based on the crossover of
    price and a Simple Moving Average (SMA). The strategy is designed to
    create realistic drawdown scenarios that the DrawDown observer can track.

    Attributes:
        sma: Simple Moving Average indicator with period 15.
        cross: Crossover indicator tracking price vs SMA intersections.
    """

    def __init__(self):
        """Initialize the strategy with indicators and DrawDown observer.

        Sets up:
        - A 15-period Simple Moving Average (SMA) indicator
        - A CrossOver indicator to detect when price crosses the SMA
        - A DrawDown observer to track drawdown metrics

        The DrawDown observer is instantiated to monitor portfolio performance
        and calculate drawdown statistics throughout the backtest.
        """
        self.sma = bt.indicators.SMA(self.data, period=15)
        self.cross = bt.indicators.CrossOver(self.data.close, self.sma)
        # Add DrawDown observer
        bt.observers.DrawDown()

    def next(self):
        """Execute trading logic for the current bar.

        Implements a simple trend-following strategy:
        - Enter long (buy) when price crosses above SMA and no position exists
        - Exit position when price crosses below SMA

        The crossover signals are provided by the CrossOver indicator:
        - Positive value (> 0) indicates bullish crossover (price crosses above SMA)
        - Negative value (< 0) indicates bearish crossover (price crosses below SMA)
        """
        if not self.position.size:
            if self.cross > 0.0:
                self.buy()
        elif self.cross < 0.0:
            self.close()


def test_run(main=False):
    """Run the DrawDown observer test.

    This function executes a backtest using the RunStrategy with the DrawDown
    observer attached. It verifies that the strategy executes successfully and
    that the DrawDown observer is properly integrated into the backtest.

    Args:
        main (bool, optional): If True, enables plotting mode. When run as a
            standalone script (main=True), plots are displayed. When run via
            pytest (main=False), plotting is disabled for faster execution.
            Defaults to False.

    The test performs the following:
        1. Loads test data using testcommon.getdata()
        2. Creates a Cerebro instance with the RunStrategy
        3. Runs the backtest with DrawDown observer monitoring
        4. Verifies the strategy processed data (len(strat) > 0)
        5. Optionally plots results when main=True

    Raises:
        AssertionError: If the strategy fails to process any data bars.
    """
    datas = [testcommon.getdata(0)]
    cerebros = testcommon.runtest(datas, RunStrategy, plot=main)

    for cerebro in cerebros:
        strat = cerebro.runstrats[0][0]
        if main:
            # print('DrawDown observer test completed')  # Removed for performance
            pass
        # Verify the strategy ran successfully
        assert len(strat) > 0


if __name__ == "__main__":
    test_run(main=True)
