#!/usr/bin/env python
"""Test module for data series functionality in Backtrader.

This module contains tests for the data series (lines) functionality, which
is a core component of Backtrader's data handling system. Data series provide
time-series access to OHLCV (Open, High, Low, Close, Volume) data and other
data fields.

The test verifies:
1. Data series can be accessed from a strategy
2. Individual data fields (close, open, high, low, volume) can be referenced
3. Data values can be accessed using array-like indexing
4. Data values maintain expected relationships (e.g., high >= low)
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import datetime

import backtrader as bt


class DataSeriesStrategy(bt.Strategy):
    """Test strategy for validating data series access and manipulation.

    This strategy tests the fundamental data series functionality by:
    1. Storing references to data series lines in __init__
    2. Accessing current data values in next()
    3. Validating data integrity through assertions

    Attributes:
        data_close (LineSeries): Reference to the close price data series.
        data_open (LineSeries): Reference to the open price data series.
        data_high (LineSeries): Reference to the high price data series.
        data_low (LineSeries): Reference to the low price data series.
        data_volume (LineSeries): Reference to the volume data series.
    """

    def __init__(self):
        """Initialize the strategy and store data series references.

        This method stores references to the various data series lines
        (close, open, high, low, volume) for later access in the next()
        method. This tests that data series can be referenced and stored
        as instance variables.
        """
        # Test dataseries access
        self.data_close = self.data.close
        self.data_open = self.data.open
        self.data_high = self.data.high
        self.data_low = self.data.low
        self.data_volume = self.data.volume

    def next(self):
        """Process the current bar and validate data series values.

        This method is called for each bar of data and performs the following:
        1. Accesses current data values using [0] indexing
        2. Validates that prices are positive values
        3. Validates that high >= low price relationship holds
        4. Validates that volume is non-negative

        The [0] index provides access to the current bar's value, while
        [-1] would provide the previous bar's value.
        """
        # Access dataseries values
        if len(self) > 0:
            close = self.data.close[0]
            open_price = self.data.open[0]
            high = self.data.high[0]
            low = self.data.low[0]
            volume = self.data.volume[0]

            # Verify values are valid
            assert close > 0
            assert open_price > 0
            assert high >= low
            assert volume >= 0


def test_dataseries(main=False):
    """Test data series functionality with a simple backtest.

    This function creates a complete backtesting environment to test data
    series functionality. It loads historical price data, adds a test
    strategy, runs the backtest, and validates that data series work
    correctly through the strategy's assertions.

    The test performs the following steps:
    1. Creates a Cerebro engine instance
    2. Loads test data from a CSV file (2006 daily data)
    3. Adds the data to the engine
    4. Adds the DataSeriesStrategy which validates data access
    5. Runs the backtest, triggering strategy logic for each bar
    6. The strategy's assertions validate data integrity

    Args:
        main (bool, optional): If True, enables additional output when run
            as a standalone script. Defaults to False.

    Raises:
        AssertionError: If any data validation fails in the strategy,
            including: non-positive prices, high < low, or negative volume.

    Note:
        The data file path is relative to this test file's location and
        points to the standard Backtrader test data file containing
        daily OHLCV data for the year 2006.
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
    cerebro.addstrategy(DataSeriesStrategy)

    cerebro.run()

    if main:
        # print('DataSeries test passed')  # Removed for performance
        pass


if __name__ == "__main__":
    test_dataseries(main=True)
