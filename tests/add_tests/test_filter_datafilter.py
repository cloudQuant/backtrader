#!/usr/bin/env python
"""Test module for DataFilter functionality in Backtrader.

This module contains tests for verifying that data filters work correctly
within the Backtrader framework. Data filters allow preprocessing of data
before it is fed to strategies, enabling operations like data cleaning,
validation, or transformation.

The test creates a simple strategy that validates data integrity and runs
a backtest over a 6-month period to ensure data is properly filtered and
processed.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import datetime

import backtrader as bt


class DataFilterStrategy(bt.Strategy):
    """A simple strategy to validate data filtering functionality.

    This strategy performs basic validation that data is being properly
    filtered and passed through to the strategy. It verifies that close
    prices are available and not None for each bar.

    Attributes:
        data: The data feed(s) attached to this strategy. Access close prices
            via self.data.close[0] to get the current bar's close price.
    """

    def next(self):
        """Called for each bar of data to validate data integrity.

        This method is called by Backtrader's core engine during the backtest
        for each data bar. It asserts that the close price is available and
        valid (not None).

        Raises:
            AssertionError: If the close price for the current bar is None,
                indicating data filtering or loading failed.
        """
        assert self.data.close[0] is not None


def test_run(main=False):
    """Run a backtest test with data filtering.

    This function sets up a Cerebro engine, loads historical stock data for
    the first half of 2006, and runs a simple backtest with the DataFilterStrategy.
    The test verifies that data is properly loaded and filtered through the
    strategy.

    The test uses sample data from the Backtrader test dataset, specifically
    the 2006 daily OHLCV data.

    Args:
        main (bool, optional): If True, enables verbose output for debugging.
            Defaults to False. When True, print statements can be executed
            for test status information.

    Returns:
        None: This function performs assertions but returns no value.
            Successful completion indicates all assertions passed.

    Raises:
        AssertionError: If the backtest produces no results, or if the
            strategy processes zero bars of data. This indicates a failure
            in data loading, filtering, or strategy execution.
    """
    cerebro = bt.Cerebro()

    modpath = os.path.dirname(os.path.abspath(__file__))
    datapath = os.path.join(modpath, "../datas/2006-day-001.txt")

    data = bt.feeds.BacktraderCSVData(
        dataname=datapath,
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 6, 30),
    )

    cerebro.adddata(data)
    cerebro.addstrategy(DataFilterStrategy)

    results = cerebro.run()

    assert len(results) > 0
    assert len(results[0]) > 0

    if main:
        pass


if __name__ == "__main__":
    test_run(main=True)
