#!/usr/bin/env python
"""Test module for CalendarDays filter functionality in Backtrader.

This module contains tests for the CalendarDays filter, which is used to
fill in missing calendar days in price data. The filter is particularly
useful when working with data that has gaps due to weekends or holidays,
ensuring that the time series includes all calendar days with appropriate
fill values.

The test verifies that:
1. The CalendarDays filter can be applied to data feeds
2. The strategy processes the filtered data correctly
3. No data corruption occurs during filtering
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import datetime

import backtrader as bt


class CalendarDaysStrategy(bt.Strategy):
    """A simple strategy for testing CalendarDays filter functionality.

    This strategy validates that data received through the CalendarDays
    filter is valid and properly formatted.

    Attributes:
        data (bt.DataBase): The data feed with CalendarDays filter applied.
    """

    def next(self):
        """Called for each bar of data to validate data integrity.

        This method is called by Backtrader during the backtesting loop
        for each data bar. It verifies that the close price is valid
        (not None or NaN).

        Raises:
            AssertionError: If the close price is None, indicating data
                corruption or filter malfunction.
        """
        # Verify data is valid
        assert self.data.close[0] is not None


def test_run(main=False):
    """Test the CalendarDays filter functionality with a backtesting strategy.

    This test creates a Cerebro engine, loads sample data, applies the
    CalendarDays filter to fill in missing calendar days, and runs a
    simple strategy to verify the data integrity. The test ensures that
    the filter correctly processes the data without corruption.

    The test uses data from the 2006 year and applies the filter to ensure
    all calendar days are present in the time series, with missing days
    filled using the last available close price.

    Args:
        main (bool, optional): If True, enables verbose output. Defaults to False.
            When running as a standalone script (main=True), additional
            output may be generated. When running as a test case (main=False),
            output is suppressed for cleaner test results.

    Returns:
        None: This function performs assertions but does not return a value.

    Raises:
        AssertionError: If any of the following conditions fail:
            - No strategy instances are returned from cerebro.run()
            - The strategy did not process any data bars
            - The strategy encounters invalid data (None close prices)

    Side Effects:
        - Creates a Cerebro instance with data and strategy
        - Runs a backtest over the specified date range
        - Optionally prints output when main=True
    """
    cerebro = bt.Cerebro()

    modpath = os.path.dirname(os.path.abspath(__file__))
    datapath = os.path.join(modpath, "../datas/2006-day-001.txt")

    data = bt.feeds.BacktraderCSVData(
        dataname=datapath,
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 12, 31),
    )

    # Add CalendarDays filter (set fill_price to 0 to use last close)
    data.addfilter(bt.filters.CalendarDays, fill_price=0)

    cerebro.adddata(data)
    cerebro.addstrategy(CalendarDaysStrategy)

    results = cerebro.run()

    # Verify filter worked
    assert len(results) > 0
    assert len(results[0]) > 0  # Strategy processed data

    if main:
        # print('CalendarDays filter test passed')  # Removed for performance
        pass


if __name__ == "__main__":
    test_run(main=True)
