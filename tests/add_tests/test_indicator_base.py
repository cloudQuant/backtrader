#!/usr/bin/env python
"""Test module for base indicator functionality in Backtrader.

This module tests the basic creation, registration, and execution of technical
indicators within the Backtrader framework. It verifies that indicators are
properly initialized, update correctly during backtesting, and produce valid
output values.

The test uses a simple strategy that creates SMA (Simple Moving Average) and
EMA (Exponential Moving Average) indicators and validates that they produce
non-zero values after their minimum period is reached.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import datetime

import backtrader as bt


class IndicatorTestStrategy(bt.Strategy):
    """A test strategy for validating base indicator functionality.

    This strategy creates two technical indicators (SMA and EMA) and verifies
    that they produce valid output values during backtesting. The assertions
    ensure that indicators are properly registered and updating correctly.

    Attributes:
        sma (bt.indicators.SMA): Simple Moving Average indicator with period 15.
        ema (bt.indicators.EMA): Exponential Moving Average indicator with period 15.

    Raises:
        AssertionError: If indicator values are zero or negative after the
            minimum period is reached.
    """

    def __init__(self):
        """Initialize the strategy and create test indicators.

        Creates SMA and EMA indicators with a 15-period lookback to test
        basic indicator creation and registration with the strategy.
        """
        # Test indicator creation
        self.sma = bt.indicators.SMA(self.data, period=15)
        self.ema = bt.indicators.EMA(self.data, period=15)

    def next(self):
        """Execute trading logic for each bar in the backtest.

        Verifies that indicators produce valid non-zero values after the
        minimum period (15 bars) has been reached. This ensures indicators
        are properly calculating and updating during the backtest.

        Raises:
            AssertionError: If SMA or EMA values are zero or negative when
                len(self) >= 15.
        """
        # Verify indicators work
        if len(self) >= 15:
            assert self.sma[0] > 0
            assert self.ema[0] > 0


def test_indicator(main=False):
    """Test base indicator functionality with a simple backtest.

    Creates a Cerebro engine, loads sample data, adds the IndicatorTestStrategy,
    and runs a backtest for the full year of 2006. The strategy's assertions
    validate that indicators work correctly.

    Args:
        main (bool, optional): If True, indicates the function is being run
            as the main entry point. Defaults to False. This parameter is
            primarily used to control optional output when run as a script.

    Returns:
        None

    Raises:
        AssertionError: If indicator values are invalid during the backtest,
            as asserted by the IndicatorTestStrategy.
        FileNotFoundError: If the test data file cannot be found at the
            expected path.

    Note:
        The test data file is expected to be located at
        'tests/datas/2006-day-001.txt' relative to the project root.
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
    cerebro.addstrategy(IndicatorTestStrategy)

    cerebro.run()

    if main:
        # print('Indicator base test passed')  # Removed for performance
        pass


if __name__ == "__main__":
    test_indicator(main=True)
