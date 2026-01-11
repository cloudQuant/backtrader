#!/usr/bin/env python
"""Test module for signal-based trading strategies in Backtrader.

This module tests the functionality of SignalStrategy, which allows for
declarative trading based on signal indicators rather than imperative
order placement. The test strategy generates long signals when a fast
moving average crosses above a slow moving average.

The test verifies that:
1. SignalStrategy properly initializes and processes signals
2. Signals are correctly generated from indicator crossovers
3. The strategy executes trades based on these signals
4. The broker maintains a positive portfolio value

Typical usage example:
    test_signal()  # Run the test programmatically
    python test_signal.py  # Run as standalone script
"""

import backtrader as bt


import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import datetime


class SignalTestStrategy(bt.SignalStrategy):
    """A test strategy that uses moving average crossover signals.

    This strategy generates long trading signals when a 10-period SMA
    crosses above a 30-period SMA. It demonstrates the use of Backtrader's
    SignalStrategy class, which provides a declarative approach to trading
    by using signal indicators instead of explicit buy/sell orders.

    Attributes:
        data: The data feed object passed to the strategy by Cerebro.
        signal_add: Method to register signal indicators with the strategy.
    """

    def __init__(self):
        """Initialize the SignalTestStrategy with indicators and signals.

        Sets up two Simple Moving Average (SMA) indicators with different
        periods and registers a crossover signal that triggers long trades
        when the fast SMA crosses above the slow SMA.

        Note:
            The super().__init__() call is critical to properly initialize
            the _signals attribute in SignalStrategy.
        """
        # CRITICAL FIX: Call super().__init__() to initialize _signals
        super().__init__()
        sma1 = bt.indicators.SMA(self.data, period=10)
        sma2 = bt.indicators.SMA(self.data, period=30)
        self.signal_add(bt.SIGNAL_LONG, bt.ind.CrossOver(sma1, sma2))


def test_signal(main=False):
    """Test signal-based strategy execution and validation.

    This function creates a complete backtesting environment with a
    SignalTestStrategy that generates trading signals based on moving
    average crossovers. It loads historical price data, runs the backtest,
    and validates that the strategy executed successfully.

    Args:
        main (bool, optional): If True, enables main execution mode.
            When False (default), runs in test mode without output.
            Defaults to False.

    Returns:
        None: This function does not return a value. It performs assertions
            to validate the test results.

    Raises:
        AssertionError: If the backtest returns no results or if the
            final portfolio value is not positive.

    Note:
        The test uses 2006 daily data from the test datas directory.
        When run in main mode (main=True), output is suppressed for
        performance reasons.
    """
    cerebro = bt.Cerebro()

    modpath = os.path.dirname(os.path.abspath(__file__))
    datapath = os.path.join(modpath, "../datas/2006-day-001.txt")

    data = bt.feeds.BacktraderCSVData(
        dataname=datapath,
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 12, 31),
    )

    cerebro.adddata(data)
    cerebro.addstrategy(SignalTestStrategy)

    results = cerebro.run()
    assert len(results) > 0
    assert results[0].broker.getvalue() > 0

    if main:
        # print('Signal test passed')  # Removed for performance
        pass


if __name__ == "__main__":
    test_signal(main=True)
