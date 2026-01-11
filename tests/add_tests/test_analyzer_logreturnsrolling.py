#!/usr/bin/env python
"""Test module for LogReturnsRolling analyzer.

This module tests the LogReturnsRolling analyzer which calculates rolling
log returns for a strategy's performance. The test verifies that the analyzer:

1. Returns a dictionary of log returns keyed by date
2. Contains return values for the backtest period
3. Produces log returns within reasonable bounds

Example:
    Run the test with output::
        $ python test_analyzer_logreturnsrolling.py
"""

import backtrader as bt

from . import testcommon


class RunStrategy(bt.Strategy):
    """A simple moving average crossover trading strategy.

    This strategy uses a Simple Moving Average (SMA) and generates trading
    signals based on price crossovers with the SMA. It goes long when price
    crosses above the SMA and closes the position when price crosses below.

    Attributes:
        sma: Simple Moving Average indicator with configurable period.
        cross: CrossOver indicator detecting price/SMA crossovers.

    Args:
        None (parameters are defined at class level).

    Parameters:
        period (int): Period for the SMA indicator. Default is 15.
        printdata (bool): Whether to print data during execution. Default is True.
    """

    params = (
        ("period", 15),
        ("printdata", True),
    )

    def __init__(self):
        """Initialize the strategy with indicators.

        Creates the SMA indicator and the CrossOver indicator that detects
        when price crosses the SMA line.
        """
        self.sma = bt.indicators.SMA(self.data, period=self.p.period)
        self.cross = bt.indicators.CrossOver(self.data.close, self.sma)

    def next(self):
        """Execute trading logic for each bar.

        Implements a simple trend-following strategy:
        - Go long when price crosses above SMA (cross > 0)
        - Close position when price crosses below SMA (cross < 0)
        - Only enter if no existing position

        The strategy maintains at most one position at a time.
        """
        if not self.position.size:
            if self.cross > 0.0:
                self.buy()
        elif self.cross < 0.0:
            self.close()


chkdatas = 1


def test_run(main=False):
    """Test the LogReturnsRolling analyzer.

    This function runs a backtest with the RunStrategy and the LogReturnsRolling
    analyzer, then verifies that the analyzer produces valid results.

    When run in main mode (main=True), prints the analysis results.
    When run in test mode (main=False), performs assertions to validate results.

    Args:
        main (bool): If True, print analysis results. If False, run assertions.
            Default is False.

    Raises:
        AssertionError: If analysis is not a dictionary, is empty, or contains
            extreme log return values (outside [-5, 5] range).

    Returns:
        None
    """
    datas = [testcommon.getdata(i) for i in range(chkdatas)]
    cerebros = testcommon.runtest(
        datas, RunStrategy, printdata=main, plot=main, analyzer=(bt.analyzers.LogReturnsRolling, {})
    )

    for cerebro in cerebros:
        strat = cerebro.runstrats[0][0]  # no optimization, only 1
        analyzer = strat.analyzers[0]  # only 1
        analysis = analyzer.get_analysis()
        if main:
            # print('LogReturnsRolling Analysis:')  # Removed for performance
            pass
            print(analysis)
            print(f"Number of return readings: {len(analysis)}")
        else:
            # Verify that analysis is a dictionary
            assert isinstance(analysis, dict)
            # Verify we have return values
            assert len(analysis) > 0
            # Log returns should be reasonable (not too extreme)
            for dt, ret in analysis.items():
                # Log returns typically in range [-1, 1] for normal market
                assert -5 < ret < 5, f"Log return {ret} seems extreme"


if __name__ == "__main__":
    test_run(main=True)
