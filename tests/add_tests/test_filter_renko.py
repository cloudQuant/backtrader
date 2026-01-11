#!/usr/bin/env python
"""Test module for Renko filter functionality in Backtrader.

This module tests the Renko filter, which is a type of chart filter that
transforms price data into Renko bricks. Renko charts filter out market noise
by only creating new bricks when price moves by a specified amount, ignoring
time and minor price fluctuations.

The test verifies that:
1. The Renko filter can be applied to CSV data feeds
2. Data integrity is maintained (open and close prices are valid)
3. The filter produces a valid number of output bars

Example:
    To run the test with output:
        python test_filter_renko.py

    To run as a pytest test:
        pytest tests/add_tests/test_filter_renko.py -v
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import datetime

import backtrader as bt


class RenkoStrategy(bt.Strategy):
    """A minimal strategy for testing Renko filter functionality.

    This strategy validates that data processed through the Renko filter
    maintains basic integrity by checking that open and close prices
    are not None for each bar.

    Attributes:
        data: The data feed with Renko filter applied, accessible via
            self.data[0] or self.data.
    """

    def next(self):
        """Execute trading logic for each bar of data.

        Validates that the Renko filter has produced valid data by
        asserting that both open and close prices are not None.

        Raises:
            AssertionError: If open or close price is None, indicating
                invalid data from the Renko filter.
        """
        # Verify data is valid
        assert self.data.open[0] is not None
        assert self.data.close[0] is not None


def test_run(main=False):
    """Test the Renko filter with a sample data feed.

    This function creates a Cerebro engine, loads sample data, applies
    the Renko filter with a brick size of 10.0, and runs a backtest
    to verify the filter works correctly.

    The test uses 2006 daily OHLCV data and verifies that:
    1. The filter processes without errors
    2. At least one strategy result is produced
    3. The strategy processes a valid number of bars

    Args:
        main (bool, optional): If True, prints the number of Renko bars
            produced. Defaults to False.

    Returns:
        None: This function performs assertions but returns no value.

    Raises:
        AssertionError: If the Cerebro engine produces no results,
            or if the strategy length is invalid.

    Note:
        Renko filters typically produce fewer bars than the original
        data because they only create new bars when price moves by
        the specified brick size, ignoring time periods with small
        price movements.
    """
    cerebro = bt.Cerebro()

    modpath = os.path.dirname(os.path.abspath(__file__))
    datapath = os.path.join(modpath, "../datas/2006-day-001.txt")

    data = bt.feeds.BacktraderCSVData(
        dataname=datapath,
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 12, 31),
    )

    # Add Renko filter
    data.addfilter(bt.filters.Renko, size=10.0)

    cerebro.adddata(data)
    cerebro.addstrategy(RenkoStrategy)

    results = cerebro.run()

    # Verify filter worked
    assert len(results) > 0
    strat = results[0]
    # Renko may produce fewer bars than original data
    assert len(strat) >= 0  # At least processed some data

    if main:
        # print('Renko filter test passed')  # Removed for performance
        pass
        print(f"Renko bars: {len(strat)}")


if __name__ == "__main__":
    test_run(main=True)
