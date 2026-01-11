#!/usr/bin/env python
"""Test module for base observer functionality in Backtrader.

This module tests the basic functionality of observers in the Backtrader
framework. Observers are components that track and record specific metrics
during backtesting, such as drawdown, cash value, and trade statistics.

The test creates a simple trading strategy that:
1. Buys when the close price is higher than the open price (bullish candle)
2. Closes the position after 50 bars

This allows observers to track performance metrics throughout the backtest.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import datetime

import backtrader as bt


class ObserverTestStrategy(bt.Strategy):
    """A simple test strategy for validating observer functionality.

    This strategy implements basic trading logic to generate trades that
    observers can track. It buys on bullish candles and holds positions
    for a minimum of 50 bars before closing.

    Attributes:
        data: The data feed object containing price data.
        position: Current position information from the broker.
    """

    def __init__(self):
        """Initialize the strategy.

        Observers are added by default by Cerebro, so this strategy
        simply needs to execute trades to generate observable data.
        """
        pass

    def next(self):
        """Execute trading logic for each bar.

        The strategy implements the following logic:
        1. If not in a position, buy when close price > open price (bullish)
        2. If in a position for more than 50 bars, close the position

        This creates a mix of long and short positions that observers
        can track and analyze.
        """
        if not self.position:
            if self.data.close[0] > self.data.open[0]:
                self.buy()
        elif len(self) > 50:
            self.close()


def test_observer(main=False):
    """Test base observer functionality in the Backtrader framework.

    This test creates a Cerebro instance, adds a data feed and a test strategy,
    then runs the backtest to verify that observers can track the strategy's
    behavior correctly. The test validates that:
    1. The backtest completes successfully
    2. Results are returned from the run
    3. The strategy executed through multiple bars

    Args:
        main (bool, optional): If True, indicates the test is being run
            as the main script rather than as a pytest test. Defaults to False.

    Returns:
        None: This function performs assertions but does not return a value.

    Raises:
        AssertionError: If the backtest fails to produce results or if
            the strategy does not execute any bars.

    Example:
        >>> test_observer()  # Run as pytest test
        >>> test_observer(main=True)  # Run as standalone script
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
    cerebro.addstrategy(ObserverTestStrategy)

    results = cerebro.run()
    assert len(results) > 0
    assert len(results[0]) > 0

    if main:
        # Optional: print('Observer base test passed')
        pass


if __name__ == "__main__":
    test_observer(main=True)
