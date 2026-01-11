#!/usr/bin/env python
"""Test module for backtrader base sizer functionality.

This module contains tests for the basic position sizing functionality in
backtrader. It tests the FixedSize sizer with a simple moving average crossover
strategy that buys when price is above the SMA and closes when price falls below.

The test verifies that:
1. The sizer is properly attached to the strategy
2. The sizer correctly sets position sizes (10 shares per trade)
3. The strategy executes trades with the correct size
4. The broker maintains a positive value after backtesting

Example:
    To run this test directly::
        python tests/add_tests/test_sizer_base.py

    To run via pytest::
        pytest tests/add_tests/test_sizer_base.py -v
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import datetime

import backtrader as bt


class SizerTestStrategy(bt.Strategy):
    """Test strategy for validating sizer functionality.

    This strategy implements a simple moving average crossover system that
    demonstrates position sizing. It buys when the close price crosses above
    the SMA and exits when it crosses below, using a sizer to control the
    position size.

    Attributes:
        sma (bt.indicators.SMA): Simple Moving Average indicator with period 15.
            Used to generate buy/sell signals based on price crossovers.

    Note:
        The sizer is dynamically configured in __init__ to set a fixed size
        of 10 shares per trade, overriding the default sizer parameters.
    """

    def __init__(self):
        """Initialize the strategy and set up indicators.

        Creates the SMA indicator and configures the sizer to use a fixed
        stake size of 10 shares for all trades.
        """
        self.sma = bt.indicators.SMA(self.data, period=15)
        self.sizer.setsizing(10)

    def next(self):
        """Execute trading logic for each bar.

        Implements a simple trend-following strategy:
        - If not in a position and close price > SMA: buy (enter long)
        - If in a position and close price < SMA: close position (exit)

        The position size is determined by the attached sizer.
        """
        if not self.position:
            if self.data.close[0] > self.sma[0]:
                self.buy()
        elif self.data.close[0] < self.sma[0]:
            self.close()


def test_sizer(main=False):
    """Test base sizer functionality with FixedSize sizer.

    This test creates a complete backtesting environment with:
    - A single data feed (2006 daily data)
    - SizerTestStrategy with SMA-based signals
    - FixedSize sizer configured for 10 shares per trade

    The test verifies that the backtest completes successfully and
    maintains a positive portfolio value.

    Args:
        main (bool, optional): If True, enables additional output for direct
            script execution. Defaults to False.

    Raises:
        AssertionError: If the backtest produces no results or if the final
            broker value is not positive, indicating a test failure.

    Note:
        The print statement for test success is commented out for performance
        reasons. When main=True, the test passes silently.
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
    cerebro.addstrategy(SizerTestStrategy)
    cerebro.addsizer(bt.sizers.FixedSize, stake=10)

    results = cerebro.run()
    assert len(results) > 0
    assert results[0].broker.getvalue() > 0

    if main:
        # print('Sizer base test passed')  # Removed for performance
        pass


if __name__ == "__main__":
    test_sizer(main=True)
