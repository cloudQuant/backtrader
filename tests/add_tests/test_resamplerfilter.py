#!/usr/bin/env python
"""Test module for data resampling functionality in Backtrader.

This module contains tests for the data resampling feature, which allows
converting data from one timeframe to another (e.g., daily to weekly).
Resampling is useful for:
    - Testing strategies on different timeframes
    - Reducing data volume by using larger timeframes
    - Multi-timeframe analysis

The test uses sample daily data from 2006 and resamples it to weekly bars.
"""

import backtrader as bt


import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import datetime



class ResampleTestStrategy(bt.Strategy):
    """A minimal strategy used for testing data resampling.

    This strategy is a placeholder that does not implement any trading logic.
    Its purpose is to verify that resampled data can be successfully loaded
    and processed by the Backtrader engine.

    Attributes:
        None (this is a minimal strategy with no custom attributes)
    """

    def next(self):
        """Called for each bar of data.

        This method is called by the Backtrader engine for each resampled
        bar. The current implementation is empty as this is a minimal
        test strategy.
        """
        pass


def test_resample(main=False):
    """Test data resampling from daily to weekly timeframe.

    This test verifies that Backtrader can properly resample data from a
    smaller timeframe (daily) to a larger timeframe (weekly). The test:
        1. Loads daily OHLCV data from a CSV file for the year 2006
        2. Resamples the data to weekly bars
        3. Runs a minimal strategy with the resampled data
        4. Verifies that the backtest completes successfully

    Args:
        main (bool, optional): If True, allows additional output when run
            as a standalone script. Defaults to False.

    Returns:
        None: This function performs assertions but does not return a value.

    Raises:
        AssertionError: If the backtest results are empty, indicating
            a failure in the resampling or execution process.

    Example:
        >>> test_resample()  # Run as a test
        >>> test_resample(main=True)  # Run as a standalone script
    """
    cerebro = bt.Cerebro()

    modpath = os.path.dirname(os.path.abspath(__file__))
    datapath = os.path.join(modpath, "../datas/2006-day-001.txt")

    data = bt.feeds.BacktraderCSVData(
        dataname=datapath,
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 12, 31),
    )

    # Resample to weekly
    cerebro.resampledata(data, timeframe=bt.TimeFrame.Weeks)
    cerebro.addstrategy(ResampleTestStrategy)

    results = cerebro.run()
    assert len(results) > 0

    if main:
        # print('Resample test passed')  # Removed for performance
        pass


if __name__ == "__main__":
    test_resample(main=True)
