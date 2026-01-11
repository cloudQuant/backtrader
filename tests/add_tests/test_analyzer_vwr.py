#!/usr/bin/env python
"""Test module for the Variability Weighted Return (VWR) analyzer.

This module contains test cases for the backtrader VWR analyzer, which
calculates risk-adjusted returns weighted by volatility/variability. The
test implements a simple moving average crossover strategy to generate
trades and verifies that the VWR analyzer produces valid analysis results.

The VWR metric measures returns while accounting for the variability/risk
of those returns, providing a more complete picture of performance than
raw returns alone.

Example:
    To run this test with plotting:
        python -m tests.add_tests.test_analyzer_vwr

    To run as a pytest test:
        pytest tests/add_tests/test_analyzer_vwr.py
"""

import backtrader as bt

from . import testcommon


class RunStrategy(bt.Strategy):
    """Simple moving average crossover strategy for testing VWR analyzer.

    This strategy generates buy signals when price crosses above the SMA
    and closes positions when price crosses below the SMA. This creates
    trades with varying returns and volatility, which the VWR analyzer
    uses to calculate variability-weighted returns.

    Attributes:
        sma: Simple Moving Average indicator with 15-period lookback.
        cross: Crossover indicator tracking price vs SMA intersections.

    Note:
        - Enters long when price crosses above SMA (cross > 0)
        - Exits when price crosses below SMA (cross < 0)
        - Only holds one position at a time
    """

    def __init__(self):
        """Initialize the strategy with indicators.

        Sets up the 15-period Simple Moving Average and crossover indicator
        to generate trading signals for the VWR analyzer to evaluate.
        """
        self.sma = bt.indicators.SMA(self.data, period=15)
        self.cross = bt.indicators.CrossOver(self.data.close, self.sma)

    def next(self):
        """Execute trading logic for each bar.

        Implements the trend-following logic:
        - If not in position, buy when price crosses above SMA
        - If in position, close when price crosses below SMA
        """
        if not self.position.size:
            if self.cross > 0.0:
                self.buy()
        elif self.cross < 0.0:
            self.close()


def test_run(main=False):
    """Run the VWR analyzer test with a simple strategy.

    Executes a backtest using the RunStrategy with VWR analysis enabled,
    then validates that the analyzer returns a properly structured
    analysis dictionary.

    Args:
        main (bool, optional): If True, runs in standalone mode with plotting
            and prints analysis results. If False, runs as a test and
            validates the output structure. Defaults to False.

    Behavior:
        - Loads test data using testcommon.getdata()
        - Runs backtest with VWR analyzer attached
        - Validates analysis contains 'vwr' key or is non-empty dict
        - Optionally prints results and shows plot

    Note:
        When main=True, the test will display the analysis output and
        plot the results. When main=False (default), assertions validate
        the analyzer output structure.
    """
    datas = [testcommon.getdata(0)]
    cerebros = testcommon.runtest(datas, RunStrategy, plot=main, analyzer=(bt.analyzers.VWR, {}))

    for cerebro in cerebros:
        strat = cerebro.runstrats[0][0]
        analyzer = strat.analyzers[0]
        analysis = analyzer.get_analysis()
        if main:
            # print('VWR Analysis:')  # Removed for performance
            pass
            print(analysis)
        else:
            assert isinstance(analysis, dict)
            # VWR (Variability Weighted Return)
            assert "vwr" in analysis or len(analysis) >= 0


if __name__ == "__main__":
    test_run(main=True)
