#!/usr/bin/env python
"""Test module for backtrader data feed functionality.

This module contains tests for verifying that data feeds load correctly
and provide data to strategies during backtesting. It tests the
BacktraderCSVData feed with date range filtering.

Example:
    Run the test directly:
        python test_feed.py

    Or run via pytest:
        pytest test_feed.py -v
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import datetime

import backtrader as bt


class FeedTestStrategy(bt.Strategy):
    """A simple strategy to verify data feed functionality.

    This strategy performs minimal validation to ensure that data from
    the feed is loaded correctly and accessible during backtesting.

    Attributes:
        data: The primary data feed attached to this strategy.
    """

    def next(self):
        """Called on each bar of the backtest.

        Verifies that the data feed has loaded valid price data by
        checking that close prices are positive on the first bar.

        Raises:
            AssertionError: If close price is not positive on first bar.
        """
        # Just verify data is loaded
        if len(self) == 1:
            assert self.data.close[0] > 0


def test_feed(main=False):
    """Test data feed loading with BacktraderCSVData.

    This function creates a Cerebro engine, loads CSV data with date filtering,
    attaches a test strategy, and verifies that the feed loads data correctly
    and the strategy runs through all bars.

    Args:
        main (bool): If True, the test is run as the main program.
            Controls optional output behavior. Defaults to False.

    Returns:
        None

    Raises:
        AssertionError: If the backtest results are empty or if the
            strategy did not process any data.

    Example:
        >>> test_feed()
        >>> test_feed(main=True)
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
    cerebro.addstrategy(FeedTestStrategy)

    results = cerebro.run()

    # Verify feed loaded data correctly
    assert len(results) > 0
    assert len(results[0]) > 0  # Strategy ran through data

    if main:
        # print('Feed test passed')  # Removed for performance
        pass


if __name__ == "__main__":
    test_feed(main=True)
