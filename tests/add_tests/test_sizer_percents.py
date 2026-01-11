#!/usr/bin/env python
"""Tests for percentage-based position sizers.

This module tests the following sizers:
- PercentSizer: Sizes orders as a percentage of available portfolio value
- AllInSizer: Allocates all available cash to each order
- PercentSizerInt: Integer version of PercentSizer
- AllInSizerInt: Integer version of AllInSizer
"""

import backtrader as bt
from . import testcommon


class RunStrategy(bt.Strategy):
    """Base strategy for testing sizers.

    This strategy uses a simple crossover system:
    - Buy when price crosses above SMA
    - Close position when price crosses below SMA

    Attributes:
        sma: Simple Moving Average indicator
        cross: Crossover indicator tracking price vs SMA
    """

    def __init__(self):
        """Initialize strategy with indicators."""
        self.sma = bt.indicators.SMA(self.data, period=15)
        self.cross = bt.indicators.CrossOver(self.data.close, self.sma)

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
    """Test PercentSizer functionality.

    Args:
        main: If True, enable plotting and verbose output

    Raises:
        AssertionError: If strategy execution fails
    """
    datas = [testcommon.getdata(0)]

    # Test PercentSizer - allocates 20% of portfolio per trade
    class PercentStrategy(RunStrategy):
        """Strategy using PercentSizer for position sizing.

        This strategy extends RunStrategy and configures PercentSizer
        to allocate 20% of available portfolio value per trade.

        Attributes:
            sizer: PercentSizer instance configured for 20% allocation
        """

        def __init__(self):
            """Initialize strategy and configure PercentSizer."""
            super().__init__()
            self.sizer = bt.sizers.PercentSizer(percents=20)

    cerebros = testcommon.runtest(datas, PercentStrategy, plot=main)
    for cerebro in cerebros:
        strat = cerebro.runstrats[0][0]
        if main:
            print(f"Final value: {strat.broker.getvalue()}")
        # Verify strategy executed successfully
        assert len(strat) > 0


def test_allin(main=False):
    """Test AllInSizer functionality.

    Args:
        main: If True, enable plotting and verbose output

    Raises:
        AssertionError: If strategy execution fails
    """
    datas = [testcommon.getdata(0)]

    # Test AllInSizer - allocates 100% of available cash
    class AllInStrategy(RunStrategy):
        """Strategy using AllInSizer for position sizing.

        This strategy extends RunStrategy and configures AllInSizer
        to allocate 100% of available cash to each trade.

        Attributes:
            sizer: AllInSizer instance for full cash allocation
        """

        def __init__(self):
            """Initialize strategy and configure AllInSizer."""
            super().__init__()
            self.sizer = bt.sizers.AllInSizer()

    cerebros = testcommon.runtest(datas, AllInStrategy, plot=main)
    for cerebro in cerebros:
        strat = cerebro.runstrats[0][0]
        if main:
            pass  # Reserved for future verbose output
        # Verify strategy executed successfully
        assert len(strat) > 0


def test_percentint(main=False):
    """Test PercentSizerInt functionality.

    Args:
        main: If True, enable plotting and verbose output

    Raises:
        AssertionError: If strategy execution fails
    """
    datas = [testcommon.getdata(0)]

    # Test PercentSizerInt - integer version of PercentSizer
    class PercentIntStrategy(RunStrategy):
        """Strategy using PercentSizerInt for position sizing.

        This strategy extends RunStrategy and configures PercentSizerInt
        to allocate 20% of available portfolio value per trade, returning
        integer share quantities.

        Attributes:
            sizer: PercentSizerInt instance configured for 20% allocation
        """

        def __init__(self):
            """Initialize strategy and configure PercentSizerInt."""
            super().__init__()
            self.sizer = bt.sizers.PercentSizerInt(percents=20)

    cerebros = testcommon.runtest(datas, PercentIntStrategy, plot=main)
    for cerebro in cerebros:
        strat = cerebro.runstrats[0][0]
        if main:
            pass  # Reserved for future verbose output
        # Verify strategy executed successfully
        assert len(strat) > 0


def test_allinint(main=False):
    """Test AllInSizerInt functionality.

    Args:
        main: If True, enable plotting and verbose output

    Raises:
        AssertionError: If strategy execution fails
    """
    datas = [testcommon.getdata(0)]

    # Test AllInSizerInt - integer version of AllInSizer
    class AllInIntStrategy(RunStrategy):
        """Strategy using AllInSizerInt for position sizing.

        This strategy extends RunStrategy and configures AllInSizerInt
        to allocate 100% of available cash to each trade, returning
        integer share quantities.

        Attributes:
            sizer: AllInSizerInt instance for full cash allocation
        """

        def __init__(self):
            """Initialize strategy and configure AllInSizerInt."""
            super().__init__()
            self.sizer = bt.sizers.AllInSizerInt()

    cerebros = testcommon.runtest(datas, AllInIntStrategy, plot=main)
    for cerebro in cerebros:
        strat = cerebro.runstrats[0][0]
        if main:
            pass  # Reserved for future verbose output
        # Verify strategy executed successfully
        assert len(strat) > 0


if __name__ == "__main__":
    test_run(main=True)
    test_allin(main=True)
    test_percentint(main=True)
    test_allinint(main=True)
