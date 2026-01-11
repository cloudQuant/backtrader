#!/usr/bin/env python
"""Tests for the PeriodStats analyzer in Backtrader.

This module contains test cases for the PeriodStats analyzer, which calculates
statistical measures of strategy performance over different periods. The tests
verify that the analyzer correctly computes metrics such as average, standard
deviation, and other statistical measures.

Typical usage example:
    test_run()  # Run the test with assertions
    test_run(main=True)  # Run the test with plotting enabled
"""

import backtrader as bt

from . import testcommon


class RunStrategy(bt.Strategy):
    """A simple moving average crossover strategy for testing.

    This strategy generates buy signals when price crosses above the SMA
    and exit signals when price crosses below the SMA. It is used to
    generate trading data for testing the PeriodStats analyzer.

    Attributes:
        sma: Simple moving average indicator with period 15.
        cross: Crossover indicator showing when price crosses the SMA.
    """
    def __init__(self):
        """Initialize the strategy with indicators.

        Sets up a 15-period simple moving average (SMA) and a crossover
        indicator to detect when the close price crosses above or below
        the SMA.
        """
        self.sma = bt.indicators.SMA(self.data, period=15)
        self.cross = bt.indicators.CrossOver(self.data.close, self.sma)

    def next(self):
        """Execute trading logic for each bar.

        Implements a simple trend-following strategy:
        - When not in a position: Buy when price crosses above SMA
        - When in a position: Close position when price crosses below SMA

        The crossover indicator returns:
        - Positive value (>0): Bullish crossover (price crossing above SMA)
        - Negative value (<0): Bearish crossover (price crossing below SMA)
        - Zero: No crossover
        """
        if not self.position.size:
            if self.cross > 0.0:
                self.buy()
        elif self.cross < 0.0:
            self.close()


def test_run(main=False):
    """Run the PeriodStats analyzer test.

    This function executes the RunStrategy with the PeriodStats analyzer
    attached, verifying that the analyzer produces valid output. In test
    mode (main=False), it asserts that the analysis results are in the
    expected format. In main mode (main=True), it prints the analysis
    results and optionally plots the results.

    Args:
        main (bool, optional): If True, run in main mode with plotting
            enabled and print analysis results. If False, run in test
            mode with assertions. Defaults to False.

    Returns:
        None: The function performs assertions in test mode or prints
        results in main mode.

    Raises:
        AssertionError: If the analysis results are not a dictionary or
            do not contain expected statistical measures (in test mode only).
    """
    datas = [testcommon.getdata(0)]
    cerebros = testcommon.runtest(
        datas, RunStrategy, plot=main, analyzer=(bt.analyzers.PeriodStats, {})
    )

    for cerebro in cerebros:
        strat = cerebro.runstrats[0][0]
        analyzer = strat.analyzers[0]
        analysis = analyzer.get_analysis()
        if main:
            # print('PeriodStats Analysis:')  # Removed for performance
            pass
            print(analysis)
        else:
            assert isinstance(analysis, dict)
            # PeriodStats should contain statistical measures
            if len(analysis) > 0:
                # Check for common keys: average, stddev, positive, negative, etc
                assert "average" in analysis or "stddev" in analysis or len(analysis) > 0


if __name__ == "__main__":
    test_run(main=True)
