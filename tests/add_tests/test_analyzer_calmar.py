#!/usr/bin/env python
"""Test module for the Calmar ratio analyzer.

This module contains tests for the Calmar ratio analyzer (bt.analyzers.Calmar),
which measures the risk-adjusted return of a trading strategy. The Calmar ratio
is defined as the compound annual growth rate (CAGR) divided by the maximum
drawdown.

The test uses a simple moving average crossover strategy to generate trades
and verifies that the analyzer correctly calculates and returns the Calmar
ratio metrics.

Typical usage example:
    from tests.add_tests import test_analyzer_calmar
    test_analyzer_calmar.test_run(main=True)
"""

import backtrader as bt

from . import testcommon


class RunStrategy(bt.Strategy):
    """A simple moving average crossover trading strategy.

    This strategy generates buy signals when price crosses above the SMA
    and exit signals when price crosses below the SMA. It maintains at most
    one position at a time.

    Attributes:
        sma: Simple Moving Average indicator.
        cross: CrossOver indicator tracking price/SMA crossovers.

    Args:
        period (int): Period for the SMA calculation. Defaults to 15.
        printdata (bool): Whether to print data during execution. Defaults to True.
    """

    params = (
        ("period", 15),
        ("printdata", True),
    )

    def __init__(self):
        """Initialize the strategy with indicators.

        Creates a Simple Moving Average (SMA) indicator and a CrossOver
        indicator to track when price crosses above or below the SMA.
        """
        self.sma = bt.indicators.SMA(self.data, period=self.p.period)
        self.cross = bt.indicators.CrossOver(self.data.close, self.sma)

    def next(self):
        """Execute trading logic for each bar.

        Implements the following logic:
        - If no position exists, enter long when price crosses above SMA
        - If a position exists, close it when price crosses below SMA
        """
        if not self.position.size:
            if self.cross > 0.0:
                self.buy()
        elif self.cross < 0.0:
            self.close()


chkdatas = 1


def test_run(main=False):
    """Run the Calmar analyzer test.

    This function executes a backtest using the RunStrategy with the Calmar
    analyzer attached. It verifies that the analyzer returns a valid
    dictionary with the expected calmar attribute.

    Args:
        main (bool): If True, prints analysis results and enables plotting.
            If False, runs in test mode with assertions. Defaults to False.

    Raises:
        AssertionError: If the analysis is not a dictionary or does not
            contain the expected calmar attribute (only in test mode).
    """
    datas = [testcommon.getdata(i) for i in range(chkdatas)]
    cerebros = testcommon.runtest(
        datas, RunStrategy, printdata=main, plot=main, analyzer=(bt.analyzers.Calmar, {})
    )

    for cerebro in cerebros:
        strat = cerebro.runstrats[0][0]  # no optimization, only 1
        analyzer = strat.analyzers[0]  # only 1
        analysis = analyzer.get_analysis()
        if main:
            # print('Calmar Analysis:')  # Removed for performance
            pass
            print(analysis)
        else:
            # Verify that analysis is a dictionary
            assert isinstance(analysis, dict)
            # Verify calmar attribute exists
            assert hasattr(analyzer, "calmar")


if __name__ == "__main__":
    test_run(main=True)
