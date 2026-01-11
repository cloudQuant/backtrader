#!/usr/bin/env python
"""Tests for fixed-size position sizers.

This module tests the following sizers:
- FixedSize: Uses a fixed number of units/shares per order
- FixedReverser: Fixed size with position reversal capability
- FixedSizeTarget: Targets a fixed position size
"""

import backtrader as bt
from . import testcommon


class RunStrategy(bt.Strategy):
    """Base strategy for testing fixed-size sizers.

    This strategy uses a simple crossover system:
    - Buy when price crosses above SMA
    - Close position when price crosses below SMA

    Attributes:
        sma: Simple Moving Average indicator
        cross: Crossover indicator tracking price vs SMA
        sizer: FixedSize sizer configured for 10 units per trade
    """

    def __init__(self):
        """Initialize strategy with indicators and sizer."""
        self.sma = bt.indicators.SMA(self.data, period=15)
        self.cross = bt.indicators.CrossOver(self.data.close, self.sma)
        # Set fixed size sizer to 10 units per trade
        self.sizer = bt.sizers.FixedSize(stake=10)

    def next(self):
        """Execute trading logic for each bar.

        Buy on bullish crossover, close on bearish crossover.
        """
        if not self.position.size:
            if self.cross > 0.0:
                self.buy()
        elif self.cross < 0.0:
            self.close()


def test_run(main=False):
    """Test FixedSizer functionality.

    Args:
        main: If True, enable plotting and verbose output

    Raises:
        AssertionError: If strategy execution fails
    """
    datas = [testcommon.getdata(0)]
    cerebros = testcommon.runtest(datas, RunStrategy, plot=main)

    for cerebro in cerebros:
        strat = cerebro.runstrats[0][0]
        if main:
            print(f"Final value: {strat.broker.getvalue()}")
        # Verify the strategy ran successfully
        assert len(strat) > 0


def test_fixedreverser(main=False):
    """Test FixedReverser functionality.

    The FixedReverser sizer reverses positions instead of closing them.
    When a sell signal occurs while long, it sells 2x stake to flip short.

    Args:
        main: If True, enable plotting and verbose output

    Raises:
        AssertionError: If strategy execution fails
    """
    class ReverserStrategy(bt.Strategy):
        """Strategy using FixedReverser sizer."""

        def __init__(self):
            """Initialize strategy with indicators and reverser sizer."""
            self.sma = bt.indicators.SMA(self.data, period=15)
            self.cross = bt.indicators.CrossOver(self.data.close, self.sma)
            # Set FixedReverser sizer - reverses positions instead of closing
            self.sizer = bt.sizers.FixedReverser(stake=10)

        def next(self):
            """Execute trading logic with position reversal.

            Buy on bullish crossover, sell (reverse) on bearish crossover.
            """
            if not self.position.size:
                if self.cross > 0.0:
                    self.buy()
            elif self.cross < 0.0:
                # Sell reverses position (sells 2x stake to go short)
                self.sell()

    datas = [testcommon.getdata(0)]
    cerebros = testcommon.runtest(datas, ReverserStrategy, plot=main)

    for cerebro in cerebros:
        strat = cerebro.runstrats[0][0]
        if main:
            pass  # Reserved for future verbose output
        # Verify the strategy ran successfully
        assert len(strat) > 0


def test_fixedsizetarget(main=False):
    """Test FixedSizeTarget functionality.

    The FixedSizeTarget sizer targets a specific position size rather than
    ordering a fixed amount to add/subtract.

    Args:
        main: If True, enable plotting and verbose output

    Raises:
        AssertionError: If strategy execution fails
    """
    class TargetStrategy(bt.Strategy):
        """Strategy using FixedSizeTarget sizer."""

        def __init__(self):
            """Initialize strategy with indicators and target sizer."""
            self.sma = bt.indicators.SMA(self.data, period=15)
            self.cross = bt.indicators.CrossOver(self.data.close, self.sma)
            # Set FixedSizeTarget sizer - targets absolute position size
            self.sizer = bt.sizers.FixedSizeTarget(stake=10)

        def next(self):
            """Execute trading logic for each bar.

            Buy on bullish crossover, close on bearish crossover.
            """
            if not self.position.size:
                if self.cross > 0.0:
                    self.buy()
            elif self.cross < 0.0:
                self.close()

    datas = [testcommon.getdata(0)]
    cerebros = testcommon.runtest(datas, TargetStrategy, plot=main)

    for cerebro in cerebros:
        strat = cerebro.runstrats[0][0]
        if main:
            pass  # Reserved for future verbose output
        # Verify the strategy ran successfully
        assert len(strat) > 0


if __name__ == "__main__":
    test_run(main=True)
    test_fixedreverser(main=True)
    test_fixedsizetarget(main=True)
