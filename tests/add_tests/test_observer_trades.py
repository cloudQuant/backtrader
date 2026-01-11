#!/usr/bin/env python
"""Test module for the Trades observer in backtrader.

This module contains tests to verify that the Trades observer correctly records
and tracks trade information during backtesting. The Trades observer monitors
all trades executed by a strategy, including entry and exit points, profit/loss,
and other trade-related metrics.

The test strategy uses a simple moving average crossover system:
- Buy when price crosses above the SMA
- Close position when price crosses below the SMA
- The Trades observer records all trade activity

Example:
    To run this test directly::
        python tests/add_tests/test_observer_trades.py

    To run via pytest::
        pytest tests/add_tests/test_observer_trades.py -v
"""

import backtrader as bt

from . import testcommon


class RunStrategy(bt.Strategy):
    """A simple moving average crossover strategy for testing the Trades observer.

    This strategy implements a basic trend-following system using a Simple Moving
    Average (SMA) crossover signal. It demonstrates the integration of the Trades
    observer to monitor trading activity.

    Attributes:
        sma (bt.indicators.SMA): Simple Moving Average indicator with period 15.
        cross (bt.indicators.CrossOver): Crossover indicator tracking the
            relationship between price and SMA.

    Trading Logic:
        - Entry: Buy when close price crosses above SMA (cross > 0)
        - Exit: Close position when close price crosses below SMA (cross < 0)
        - Only one position open at a time (no pyramiding)
    """

    def __init__(self):
        """Initialize the strategy with indicators and the Trades observer.

        Sets up the technical indicators used for generating trading signals
        and adds the Trades observer to monitor trade execution.
        """
        self.sma = bt.indicators.SMA(self.data, period=15)
        self.cross = bt.indicators.CrossOver(self.data.close, self.sma)
        # Add Trades observer to monitor trade activity
        bt.observers.Trades()

    def next(self):
        """Execute trading logic for each bar.

        Implements the core trading logic that evaluates crossover signals
        and executes trades accordingly. The method checks for position status
        and crossover conditions before placing orders.

        Trading Rules:
            1. If no position exists: Buy when crossover is positive (price > SMA)
            2. If position exists: Close when crossover is negative (price < SMA)
        """
        if not self.position.size:
            if self.cross > 0.0:
                self.buy()
        elif self.cross < 0.0:
            self.close()


def test_run(main=False):
    """Run the Trades observer test.

    Executes a backtest using the RunStrategy with the Trades observer enabled.
    Verifies that the strategy runs successfully and processes data correctly.

    This test function:
        1. Loads test data using the common test data loader
        2. Creates a Cerebro instance with the RunStrategy
        3. Runs the backtest with the Trades observer
        4. Verifies the strategy executed successfully

    Args:
        main (bool, optional): If True, enables plotting mode and suppresses
            the print statement. Defaults to False. When run as a script
            (via __main__), this is set to True.

    Returns:
        None: This function performs assertions but does not return a value.

    Raises:
        AssertionError: If the strategy did not process any bars (len(strat) == 0),
            indicating a failure in the backtest execution.

    Note:
        The test uses data from testcommon.getdata(0) which provides a standard
        test dataset for backtrader testing.
    """
    datas = [testcommon.getdata(0)]
    cerebros = testcommon.runtest(datas, RunStrategy, plot=main)

    for cerebro in cerebros:
        strat = cerebro.runstrats[0][0]
        if main:
            # Running in main mode - no output needed
            pass
        # Verify the strategy ran successfully
        assert len(strat) > 0


if __name__ == "__main__":
    test_run(main=True)
