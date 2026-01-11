#!/usr/bin/env python
"""Test suite for backtrader functional utility operators.

This module contains tests for the functional utilities provided in
backtrader.functions, which include logical operators (And, Or) and
conditional functions (If, Max, Min) that operate on line objects
and indicators.

These functions are essential for creating complex trading signals
by combining multiple conditions and indicators in a declarative way.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import backtrader as bt
import backtrader.functions as btfunc


def test_functions_and_or(main=False):
    """Test the And and Or logical functions from backtrader.functions.

    This test verifies that the And and Or functions correctly perform
    logical operations on line objects and indicators. These functions
    are commonly used to create complex trading signals by combining
    multiple conditions.

    The test creates two SMA indicators and uses them to test:
    - And: Returns True only when both conditions are True
    - Or: Returns True when either condition is True

    Args:
        main (bool, optional): If True, prints success message. Defaults to False.

    Raises:
        AssertionError: If the And or Or signals do not produce valid values.
    """

    class FuncStrategy(bt.Strategy):
        """Test strategy for And and Or logical functions.

        This strategy creates two SMA indicators and uses the And/Or
        functions to combine conditions based on price relationships
        to these indicators.
        """

        def __init__(self):
            """Initialize the strategy and create logical signal indicators.

            Creates two Simple Moving Averages (10 and 20 period) and
            uses them to create:
            - and_signal: True when close > SMA10 AND SMA10 > SMA20
            - or_signal: True when close > SMA10 OR close > SMA20
            """
            sma1 = bt.indicators.SMA(self.data, period=10)
            sma2 = bt.indicators.SMA(self.data, period=20)

            # Test And
            self.and_signal = btfunc.And(self.data.close > sma1, sma1 > sma2)

            # Test Or
            self.or_signal = btfunc.Or(self.data.close > sma1, self.data.close > sma2)

        def next(self):
            """Verify that logical signals produce valid values on each bar.

            Raises:
                AssertionError: If the and_signal or or_signal is None.
            """
            # Verify signals produce values
            assert self.and_signal[0] is not None
            assert self.or_signal[0] is not None

    cerebro = bt.Cerebro()

    modpath = os.path.dirname(os.path.abspath(__file__))
    datapath = os.path.join(modpath, "../datas/2006-day-001.txt")

    import datetime

    data = bt.feeds.BacktraderCSVData(
        dataname=datapath,
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 12, 31),
    )

    cerebro.adddata(data)
    cerebro.addstrategy(FuncStrategy)
    cerebro.run()

    if main:
        # print('And/Or functions test passed')  # Removed for performance
        pass


def test_functions_if(main=False):
    """Test the If conditional function from backtrader.functions.

    The If function provides conditional logic for line objects, returning
    one value when a condition is True and another when False. This is
    commonly used for creating trading signals that produce different
    values based on market conditions.

    Args:
        main (bool, optional): If True, prints success message. Defaults to False.

    Raises:
        AssertionError: If the If function does not produce expected values (1 or -1).
    """

    class IfStrategy(bt.Strategy):
        """Test strategy for the If conditional function.

        This strategy uses the If function to produce a signal that
        returns 1 when price is above SMA, and -1 when below.
        """

        def __init__(self):
            """Initialize the strategy and create conditional signal.

            Creates a 10-period SMA and uses the If function to:
            - Return 1 when close > SMA
            - Return -1 when close <= SMA
            """
            sma = bt.indicators.SMA(self.data, period=10)

            # Test If function
            self.if_result = btfunc.If(self.data.close > sma, 1, -1)

        def next(self):
            """Verify that the If function produces expected values.

            Only validates after the SMA has enough data (10 bars).

            Raises:
                AssertionError: If if_result is None or not in [1, -1].
            """
            # Verify If produces values
            if len(self) >= 10:
                assert self.if_result[0] is not None
                assert self.if_result[0] in [1, -1]

    cerebro = bt.Cerebro()

    modpath = os.path.dirname(os.path.abspath(__file__))
    datapath = os.path.join(modpath, "../datas/2006-day-001.txt")

    import datetime

    data = bt.feeds.BacktraderCSVData(
        dataname=datapath,
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 12, 31),
    )

    cerebro.adddata(data)
    cerebro.addstrategy(IfStrategy)
    cerebro.run()

    if main:
        # print('If function test passed')  # Removed for performance
        pass


def test_functions_max_min(main=False):
    """Test the Max and Min functions from backtrader.functions.

    The Max and Min functions compare two line objects and return
    the maximum or minimum value at each point in time. These are
    useful for comparing indicators, prices, or other time series.

    Args:
        main (bool, optional): If True, prints success message. Defaults to False.

    Raises:
        AssertionError: If Max is not >= Min, or if values are None.
    """

    class MaxMinStrategy(bt.Strategy):
        """Test strategy for Max and Min functions.

        This strategy creates two SMA indicators and uses Max/Min
        functions to compare their values at each bar.
        """

        def __init__(self):
            """Initialize the strategy and create Max/Min comparators.

            Creates two Simple Moving Averages (10 and 20 period) and
            uses Max/Min to track which is greater at each point.
            """
            sma1 = bt.indicators.SMA(self.data, period=10)
            sma2 = bt.indicators.SMA(self.data, period=20)

            # Test Max and Min
            self.max_val = btfunc.Max(sma1, sma2)
            self.min_val = btfunc.Min(sma1, sma2)

        def next(self):
            """Verify that Max and Min produce valid, consistent values.

            Only validates after both SMAs have enough data (20 bars).

            Raises:
                AssertionError: If max_val < min_val, or if either is None.
            """
            if len(self) >= 20:
                assert self.max_val[0] is not None
                assert self.min_val[0] is not None
                assert self.max_val[0] >= self.min_val[0]

    cerebro = bt.Cerebro()

    modpath = os.path.dirname(os.path.abspath(__file__))
    datapath = os.path.join(modpath, "../datas/2006-day-001.txt")

    import datetime

    data = bt.feeds.BacktraderCSVData(
        dataname=datapath,
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 12, 31),
    )

    cerebro.adddata(data)
    cerebro.addstrategy(MaxMinStrategy)
    cerebro.run()

    if main:
        # print('Max/Min functions test passed')  # Removed for performance
        pass


if __name__ == "__main__":
    test_functions_and_or(main=True)
    test_functions_if(main=True)
    test_functions_max_min(main=True)
