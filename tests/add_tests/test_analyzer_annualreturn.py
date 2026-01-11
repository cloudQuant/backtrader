#!/usr/bin/env python
"""Test module for AnnualReturn analyzer.

This module contains tests for the backtrader AnnualReturn analyzer, which
calculates the annual returns of a trading strategy. The test creates a simple
moving average crossover strategy and verifies that the analyzer correctly
calculates and returns annual returns.
"""

import backtrader as bt

from . import testcommon


class RunStrategy(bt.Strategy):
    """A simple moving average crossover trading strategy.

    This strategy buys when the price crosses above the SMA and closes the
    position when the price crosses below the SMA.

    Attributes:
        sma: Simple Moving Average indicator.
        cross: CrossOver indicator tracking price vs SMA crossovers.

    Args:
        period (int): The period for the SMA calculation. Defaults to 15.
        printdata (bool): Whether to print data during execution. Defaults to True.
    """

    params = (
        ("period", 15),
        ("printdata", True),
    )

    def __init__(self):
        """Initialize the strategy with indicators.

        Creates the SMA indicator and CrossOver indicator to track
        price crossovers with the moving average.
        """
        self.sma = bt.indicators.SMA(self.data, period=self.p.period)
        self.cross = bt.indicators.CrossOver(self.data.close, self.sma)

    def next(self):
        """Execute trading logic for each bar.

        Implements a simple crossover strategy:
        - If no position exists, buy when price crosses above SMA
        - If position exists, close it when price crosses below SMA
        """
        if not self.position.size:
            if self.cross > 0.0:
                self.buy()
        elif self.cross < 0.0:
            self.close()


chkdatas = 1


def test_run(main=False):
    """Run the AnnualReturn analyzer test.

    This test function creates a backtesting engine with test data, runs a
    simple moving average crossover strategy with an AnnualReturn analyzer,
    and verifies that the analyzer produces correct results.

    The test validates that:
    - The analysis returns a dictionary
    - The dictionary contains year keys
    - The year 2006 is present with approximately 2.84% return

    Args:
        main (bool): If True, prints the analysis results instead of asserting.
                     Defaults to False, which runs assertion checks.

    Raises:
        AssertionError: If the analysis format is incorrect or the 2006 return
                       value deviates significantly from the expected 0.0284.
    """
    datas = [testcommon.getdata(i) for i in range(chkdatas)]
    cerebros = testcommon.runtest(
        datas, RunStrategy, printdata=main, plot=main, analyzer=(bt.analyzers.AnnualReturn, {})
    )

    for cerebro in cerebros:
        strat = cerebro.runstrats[0][0]  # no optimization, only 1
        analyzer = strat.analyzers[0]  # only 1
        analysis = analyzer.get_analysis()
        if main:
            # print('AnnualReturn Analysis:')  # Removed for performance
            pass
            print(analysis)
        else:
            # Verify that analysis is a dictionary and contains year keys
            assert isinstance(analysis, dict)
            assert len(analysis) > 0
            # Check that the year 2006 is present
            assert 2006 in analysis
            # Verify the actual return value for 2006 (from actual run)
            assert abs(analysis[2006] - 0.0284) < 0.01


if __name__ == "__main__":
    test_run(main=True)
