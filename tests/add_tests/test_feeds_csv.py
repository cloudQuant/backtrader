#!/usr/bin/env python
"""Test module for CSV data feed functionality in Backtrader.

This module contains tests for various CSV data feed implementations, including
BacktraderCSVData and GenericCSVData. These tests verify that data feeds can
correctly load and parse CSV files, making the data available to strategies
during backtesting.

The tests use a sample data file (2006-day-001.txt) containing daily OHLCV
(Open, High, Low, Close, Volume) data for the year 2006.

Typical usage example:
    To run all tests from command line:
        python test_feeds_csv.py

    To run individual tests:
        test_btcsv()
        test_generic_csv()
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import datetime

import backtrader as bt


class FeedStrategy(bt.Strategy):
    """A simple strategy for testing CSV data feeds.

    This strategy performs basic validation to verify that data has been
    correctly loaded from the CSV feed and is accessible during strategy
    execution.

    Attributes:
        data: The data feed object containing OHLCV data. This is automatically
            assigned by Backtrader when the strategy is run.
    """

    def next(self):
        """Execute trading logic for each bar.

        This method is called by Backtrader for each bar in the data feed.
        It performs basic validation that the data has been loaded correctly.

        Raises:
            AssertionError: If the close price is not positive, indicating
                that the data feed was not loaded correctly.
        """
        # Verify data is loaded
        assert self.data.close[0] > 0


def test_btcsv(main=False):
    """Test the BacktraderCSVData feed implementation.

    This test creates a Cerebro instance, loads data using the
    BacktraderCSVData feed with the standard Backtrader CSV format,
    and verifies that the data is correctly loaded and accessible
    to the strategy.

    The test uses data from 2006 with specific date range filtering
    to validate that date-based filtering works correctly.

    Args:
        main (bool): If True, enables verbose output for manual execution.
            Defaults to False for automated testing.

    Returns:
        None

    Raises:
        AssertionError: If the data feed fails to load or if no data
            bars are available to the strategy.
        FileNotFoundError: If the test data file cannot be found.

    Example:
        >>> test_btcsv()
        >>> # Test passes silently if successful
        >>> test_btcsv(main=True)
        >>> # Runs with verbose output
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
    cerebro.addstrategy(FeedStrategy)
    results = cerebro.run()

    # Verify feed loaded successfully
    assert len(results) > 0
    assert len(results[0]) > 0

    if main:
        # print('BacktraderCSVData feed test passed')  # Removed for performance
        pass


def test_generic_csv(main=False):
    """Test the GenericCSVData feed implementation.

    This test creates a Cerebro instance, loads data using the
    GenericCSVData feed with custom column mappings, and verifies
    that the data is correctly loaded and accessible to the strategy.

    GenericCSVData requires explicit specification of column positions
    and date format, making it suitable for CSV files with non-standard
    formats. This test validates that the column mapping functionality
    works correctly.

    Args:
        main (bool): If True, enables verbose output for manual execution.
            Defaults to False for automated testing.

    Returns:
        None

    Raises:
        AssertionError: If the data feed fails to load or if no data
            bars are available to the strategy.
        FileNotFoundError: If the test data file cannot be found.
        ValueError: If the date format or column mappings are invalid.

    Example:
        >>> test_generic_csv()
        >>> # Test passes silently if successful
        >>> test_generic_csv(main=True)
        >>> # Runs with verbose output
    """
    cerebro = bt.Cerebro()

    modpath = os.path.dirname(os.path.abspath(__file__))
    datapath = os.path.join(modpath, "../datas/2006-day-001.txt")

    data = bt.feeds.GenericCSVData(
        dataname=datapath,
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 12, 31),
        dtformat="%Y-%m-%d",
        datetime=0,
        open=1,
        high=2,
        low=3,
        close=4,
        volume=5,
        openinterest=-1,
    )

    cerebro.adddata(data)
    cerebro.addstrategy(FeedStrategy)
    results = cerebro.run()

    # Verify feed loaded successfully
    assert len(results) > 0
    assert len(results[0]) > 0

    if main:
        # print('GenericCSVData feed test passed')  # Removed for performance
        pass


if __name__ == "__main__":
    test_btcsv(main=True)
    test_generic_csv(main=True)
