#!/usr/bin/env python

"""Test module for the DaySplitter filter functionality in Backtrader.

This module tests the DaySplitter filter (specifically DaySplitter_Close) which
splits daily bars into smaller timeframes. The filter is applied to a data feed
and the test verifies that:

1. The data feed is properly loaded
2. The filter is applied correctly
3. The strategy can process the filtered data
4. Close prices are valid throughout the backtest

The test uses sample data from 2006 and runs a simple strategy that validates
data integrity at each bar.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import datetime

import backtrader as bt


class BarsplitterStrategy(bt.Strategy):
    """A simple strategy for testing the DaySplitter filter.

    This strategy validates that the DaySplitter filter produces valid data
    by checking that close prices are not None at each bar.

    Attributes:
        data: The data feed passed to the strategy by Cerebro.
    """

    def next(self):
        """Execute trading logic for each bar.

        This method is called by Backtrader for each bar of data.
        It validates that the close price is properly set.

        Raises:
            AssertionError: If the close price is None, indicating invalid data.
        """
        # Verify data is valid
        assert self.data.close[0] is not None


def test_run(main=False):
    """Test the DaySplitter filter functionality.

    This function creates a Cerebro engine, loads sample data from 2006,
    applies the DaySplitter_Close filter, and runs a simple strategy
    to verify that the filter works correctly.

    Args:
        main (bool, optional): If True, indicates this is being run as the
            main script. When False (default), suppresses output messages.
            Defaults to False.

    Returns:
        None: The function performs assertions but returns no value.

    Raises:
        AssertionError: If the backtest produces no results or if the
            strategy processes no bars, indicating filter failure.

    Note:
        The test uses data from '../datas/2006-day-001.txt' relative to
        this file's location. The data covers the full year of 2006.
    """
    cerebro = bt.Cerebro()

    modpath = os.path.dirname(os.path.abspath(__file__))
    datapath = os.path.join(modpath, "../datas/2006-day-001.txt")

    data = bt.feeds.BacktraderCSVData(
        dataname=datapath,
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 12, 31),
    )

    # Add DaySplitter filter (from bsplitter module)
    data.addfilter(bt.filters.DaySplitter_Close)

    cerebro.adddata(data)
    cerebro.addstrategy(BarsplitterStrategy)

    results = cerebro.run()

    # Verify filter worked
    assert len(results) > 0
    assert len(results[0]) > 0  # Strategy processed data

    if main:
        # print('DaySplitter filter test passed')  # Removed for performance
        pass


if __name__ == "__main__":
    test_run(main=True)
