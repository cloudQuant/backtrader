#!/usr/bin/env python
"""Test module for DayStepsFilter functionality.

This module tests the DayStepsFilter (also known as BarReplayer_Open) which
replays bars during backtesting. The filter allows for replaying historical
data with specific day-based stepping behavior, which is useful for testing
strategy execution under various market conditions.

The test creates a Cerebro instance, loads 2006 daily data, applies the
DayStepsFilter, and verifies that the strategy processes the replayed data
correctly.
"""


import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import datetime

import backtrader as bt


class DayStepsStrategy(bt.Strategy):
    """A minimal strategy for testing DayStepsFilter functionality.

    This strategy performs a single validation during each bar: checking that
    the close price is valid (not None). This ensures that the DayStepsFilter
    is correctly replaying bars with valid data.

    Attributes:
        data: The data feed(s) attached to this strategy, providing access to
            price data (open, high, low, close, volume).
    """

    def next(self):
        """Execute logic for each bar in the backtest.

        This method is called by the backtrader engine for each bar of data.
        It validates that the close price is available and not None.

        Raises:
            AssertionError: If the close price for the current bar is None,
                indicating invalid data from the filter.
        """
        # Verify data is valid
        assert self.data.close[0] is not None


def test_run(main=False):
    """Test the DayStepsFilter (BarReplayer_Open) functionality.

    This test verifies that the DayStepsFilter correctly replays bars during
    backtesting. It sets up a Cerebro instance with 2006 daily price data,
    applies the DayStepsFilter, and runs a minimal strategy to validate that
    the filter produces valid data.

    The test performs the following validations:
    1. Creates a Cerebro backtesting engine
    2. Loads daily OHLCV data from a CSV file for the year 2006
    3. Applies the DayStepsFilter to the data feed
    4. Runs the backtest with a validation strategy
    5. Asserts that results were generated
    6. Asserts that the strategy processed bars from the filtered data

    Args:
        main (bool, optional): If True, indicates the test is being run in
            standalone mode (via __main__). Defaults to False. When True,
            additional output may be generated.

    Returns:
        None

    Raises:
        AssertionError: If any of the following conditions fail:
            - No results are returned from cerebro.run()
            - The strategy didn't process any bars (empty results)
            - Any close price is None during strategy execution

    Example:
        >>> test_run()  # Run as part of test suite
        >>> test_run(main=True)  # Run standalone
    """
    cerebro = bt.Cerebro()

    modpath = os.path.dirname(os.path.abspath(__file__))
    datapath = os.path.join(modpath, "../datas/2006-day-001.txt")

    data = bt.feeds.BacktraderCSVData(
        dataname=datapath,
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 12, 31),
    )

    # Add BarReplayer filter (DayStepsFilter alias)
    data.addfilter(bt.filters.DayStepsFilter)

    cerebro.adddata(data)
    cerebro.addstrategy(DayStepsStrategy)

    results = cerebro.run()

    # Verify filter worked
    assert len(results) > 0
    assert len(results[0]) > 0  # Strategy processed replayed data

    if main:
        # print('DayStepsFilter test passed')  # Removed for performance
        pass


if __name__ == "__main__":
    # Entry point for running the test as a standalone script.
    # When executed directly, this script runs the DayStepsFilter test with
    # the main parameter set to True, enabling any standalone-specific behavior.
    test_run(main=True)
