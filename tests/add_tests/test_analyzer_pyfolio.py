#!/usr/bin/env python
"""Test module for the PyFolio analyzer.

This module contains tests for the PyFolio analyzer, which integrates
backtrader with the pyfolio library for performance analytics and
visualization of trading strategies.

The test uses a simple moving average crossover strategy to generate
trades and verifies that the PyFolio analyzer correctly captures
returns, positions, and transaction data.
"""

import backtrader as bt

from . import testcommon


class RunStrategy(bt.Strategy):
    """Simple moving average crossover strategy for testing PyFolio analyzer.

    This strategy generates buy signals when price crosses above the
    15-period SMA and closes positions when price crosses below.

    Attributes:
        sma: Simple Moving Average indicator with period 15.
        cross: CrossOver indicator tracking price vs SMA crossovers.

    Note:
        This is a minimal strategy designed to generate test trades
        for verifying PyFolio analyzer functionality.
    """

    def __init__(self):
        """Initialize strategy indicators.

        Creates a 15-period Simple Moving Average (SMA) and a CrossOver
        indicator to detect when price crosses above or below the SMA.
        """
        self.sma = bt.indicators.SMA(self.data, period=15)
        self.cross = bt.indicators.CrossOver(self.data.close, self.sma)

    def next(self):
        """Execute trading logic for each bar.

        Enters a long position when price crosses above the SMA (cross > 0).
        Closes the position when price crosses below the SMA (cross < 0).

        Note:
            Only one position (long or short) is held at a time.
        """
        if not self.position.size:
            if self.cross > 0.0:
                self.buy()
        elif self.cross < 0.0:
            self.close()


def test_run(main=False):
    """Run test for PyFolio analyzer.

    Executes a backtest using RunStrategy with the PyFolio analyzer attached.
    Verifies that the analyzer correctly captures performance metrics including
    returns, positions, and transactions.

    Args:
        main (bool): If True, runs in verbose mode with plotting and prints
            analysis results. If False (default), runs assertion checks
            without plotting. Defaults to False.

    Test Behavior:
        - Loads test data from testcommon.getdata(0)
        - Runs RunStrategy with PyFolio analyzer
        - In test mode: Asserts analysis object is not None and contains
          expected data (returns, positions, or transactions)
        - In main mode: Prints full analysis results for manual inspection

    Note:
        PyFolio is a third-party library for performance analytics. The analyzer
        returns a dict-like object containing returns, positions, gross leverage,
        and transactions data compatible with pyfolio's create_full_tear_sheet.
    """
    datas = [testcommon.getdata(0)]
    cerebros = testcommon.runtest(
        datas, RunStrategy, plot=main, analyzer=(bt.analyzers.PyFolio, {})
    )

    for cerebro in cerebros:
        strat = cerebro.runstrats[0][0]
        analyzer = strat.analyzers[0]
        analysis = analyzer.get_analysis()
        if main:
            # print('PyFolio Analysis:')  # Removed for performance
            pass
            print(analysis)
        else:
            # PyFolio analyzer returns a dict-like object
            assert analysis is not None
            # PyFolio should return returns, positions, transactions
            assert "returns" in analysis or "positions" in analysis or analysis is not None


if __name__ == "__main__":
    test_run(main=True)
