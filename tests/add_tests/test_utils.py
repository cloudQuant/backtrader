#!/usr/bin/env python
"""Test module for backtrader utility functions.

This module contains comprehensive tests for various utility functions and classes
provided by the backtrader framework, including:

- Date conversion utilities (date2num, num2date)
- AutoDict and AutoOrderedDict classes for automatic dictionary nesting
- Integration tests for utilities within a strategy context

These tests ensure that utility functions work correctly both in isolation and
when integrated into a backtrader strategy workflow.
"""


import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import datetime

import backtrader as bt
from backtrader.utils import AutoDict, AutoOrderedDict, date2num, num2date


def test_date_conversion(main=False):
    """Test date conversion utilities for datetime to numeric conversion.

    This test verifies the bidirectional conversion between datetime objects
    and their numeric representations used internally by backtrader. It ensures
    that converting a datetime to a number and back preserves the date components
    (year, month, day).

    Args:
        main (bool, optional): If True, prints debug information during test execution.
            Defaults to False for normal pytest runs.

    Returns:
        None

    Raises:
        AssertionError: If the converted date does not match the original date's
            year, month, or day components.

    Examples:
        >>> test_date_conversion()
        >>> test_date_conversion(main=True)  # With debug output
    """
    # Test date2num and num2date
    test_date = datetime.datetime(2006, 1, 1)
    num_date = bt.date2num(test_date)
    converted_back = bt.num2date(num_date)

    if main:
        print(f"Converted to num: {num_date}")
        print(f"Converted back: {converted_back}")

    assert converted_back.year == test_date.year
    assert converted_back.month == test_date.month
    assert converted_back.day == test_date.day


def test_autodict(main=False):
    """Test AutoDict and AutoOrderedDict automatic nesting functionality.

    This test verifies that AutoDict and AutoOrderedDict properly support
    automatic nesting of dictionaries through dot notation attribute access.
    These classes allow creating nested dictionary structures without
    explicitly creating intermediate dictionaries.

    Args:
        main (bool, optional): If True, prints success messages during test execution.
            Defaults to False for normal pytest runs.

    Returns:
        None

    Raises:
        AssertionError: If the nested values cannot be retrieved correctly.

    Examples:
        >>> test_autodict()
        >>> ad = AutoDict()
        >>> ad.level1.level2.level3 = "value"
        >>> assert ad.level1.level2.level3 == "value"
    """
    # Test AutoDict
    ad = AutoDict()
    ad.level1.level2.level3 = "value"

    assert ad.level1.level2.level3 == "value"

    # Test AutoOrderedDict
    aod = AutoOrderedDict()
    aod.key1.key2 = "test_value"

    assert aod.key1.key2 == "test_value"

    if main:
        print("AutoOrderedDict test passed")


def test_utils_integration(main=False):
    """Test utility functions integration within a backtrader strategy.

    This test verifies that utility functions, particularly date conversion,
    work correctly when used within a backtrader strategy's next() method.
    It creates a simple strategy that:

    1. Converts numeric dates to datetime objects during bar iteration
    2. Validates the conversion results
    3. Places a buy order on the 10th bar if no position exists

    Args:
        main (bool, optional): If True, prints debug information during test execution.
            Defaults to False for normal pytest runs.

    Returns:
        None

    Raises:
        AssertionError: If date conversion fails within the strategy context,
            or if the strategy execution encounters errors.

    Examples:
        >>> test_utils_integration()
        >>> test_utils_integration(main=True)  # With debug output
    """
    class UtilsStrategy(bt.Strategy):
        """Test strategy for utility function integration.

        This strategy tests date conversion utilities by converting numeric
        dates to datetime objects during each bar iteration and placing a
        buy order on the 10th bar.

        Attributes:
            order_count (int): Counter for tracking the number of orders placed.
        """

        def __init__(self):
            """Initialize the strategy with an order counter."""
            self.order_count = 0

        def next(self):
            """Execute strategy logic for each bar.

            This method is called by backtrader for each bar in the data feed.
            It tests date conversion utilities and places a buy order on the
            10th bar if no position exists.

            The method performs the following:
            1. Retrieves the current bar's datetime as a number
            2. Converts it to a datetime object
            3. Validates the conversion succeeded
            4. Places a buy order on bar 10 if not already in position
            """
            # Use date conversion in strategy
            dt_num = self.data.datetime[0]
            dt = bt.num2date(dt_num)

            # Verify conversion works
            assert dt is not None
            assert isinstance(dt, datetime.datetime)

            if not self.position and len(self) == 10:
                self.buy()

    cerebro = bt.Cerebro()

    modpath = os.path.dirname(os.path.abspath(__file__))
    datapath = os.path.join(modpath, "../datas/2006-day-001.txt")

    data = bt.feeds.BacktraderCSVData(
        dataname=datapath,
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 12, 31),
    )

    cerebro.adddata(data)
    cerebro.addstrategy(UtilsStrategy)
    cerebro.run()


if __name__ == "__main__":
    test_date_conversion(main=True)
    test_autodict(main=True)
    test_utils_integration(main=True)
