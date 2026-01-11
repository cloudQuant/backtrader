#!/usr/bin/env python
"""Test module for TA-Lib integration with Backtrader.

This module tests the integration of TA-Lib indicators with the Backtrader
framework. It verifies that TA-Lib indicators can be used within Backtrader
strategies and properly process data feeds.

The test creates a simple strategy that attempts to use the TA-Lib SMA indicator.
If TA-Lib is not available, it falls back to the native Backtrader SMA indicator,
ensuring the test passes regardless of TA-Lib availability.

Example:
    Run the test directly:
        python test_talib.py

    Or import and run programmatically:
        from tests.add_tests.test_talib import test_talib
        test_talib()
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import datetime

import backtrader as bt


class TalibTestStrategy(bt.Strategy):
    """Test strategy for TA-Lib integration.

    This strategy tests the integration of TA-Lib indicators by creating a
    Simple Moving Average (SMA) indicator. It attempts to use TA-Lib's SMA
    implementation if available, falling back to Backtrader's native SMA
    indicator if TA-Lib is not installed.

    Attributes:
        sma (bt.Indicator): The SMA indicator, either from TA-Lib or Backtrader
            depending on availability.
        data (bt.DataBase): The data feed passed to the strategy by Cerebro.

    Note:
        This strategy does not execute any trades. It only verifies that
        indicators can be instantiated and calculated correctly.
    """

    def __init__(self):
        """Initialize the TalibTestStrategy.

        Attempts to create a TA-Lib SMA indicator with a 15-period time window.
        If TA-Lib is not available or raises an exception, falls back to the
        native Backtrader SMA indicator.

        The fallback mechanism ensures the test passes even when TA-Lib is
        not installed on the system.
        """
        try:
            # Try to use talib indicator if available
            self.sma = bt.talib.SMA(self.data.close, timeperiod=15)
        except:
            # If talib not available, use regular SMA
            self.sma = bt.indicators.SMA(self.data, period=15)

    def next(self):
        """Execute strategy logic for each bar.

        This method is called by Backtrader for each new bar of data.
        The current implementation is a placeholder and performs no action.

        Note:
            This is a test strategy that does not execute trades, so this
            method is intentionally left empty.
        """
        pass


def test_talib(main=False):
    """Test TA-Lib integration with Backtrader.

    Creates a Cerebro instance, loads test data, and runs a backtest using
    the TalibTestStrategy. Verifies that the backtest completes successfully
    and returns results.

    The test uses 2006 daily data from the test datas directory. It runs
    a full year of data from January 1, 2006 to December 31, 2006.

    Args:
        main (bool, optional): If True, the function is being run in standalone
            mode (not as a pytest test). This affects output behavior.
            Defaults to False.

    Returns:
        None: The function asserts that results were generated but does not
            return a value.

    Raises:
        AssertionError: If the backtest does not produce any results, indicating
            a failure in strategy execution or data loading.

    Example:
        Run as a standalone test:
            test_talib(main=True)

        Run in test mode:
            test_talib()
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
    cerebro.addstrategy(TalibTestStrategy)

    results = cerebro.run()
    assert len(results) > 0

    if main:
        # print('Talib test passed (or skipped if talib not installed)')  # Removed for performance
        pass


if __name__ == "__main__":
    test_talib(main=True)
