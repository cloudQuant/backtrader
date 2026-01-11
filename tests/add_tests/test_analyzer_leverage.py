#!/usr/bin/env python
"""Test module for the GrossLeverage analyzer.

This module tests the GrossLeverage analyzer which tracks the gross leverage
ratio of a trading strategy over time. Gross leverage is calculated as the
total value of open positions divided by the total portfolio value.

The test uses a simple SMA crossover strategy to generate trades and verifies
that the leverage values are within the expected range [0, 1], where:
- 0 indicates no positions (all cash)
- 1 indicates fully invested (all cash in positions)
"""

import backtrader as bt

from . import testcommon


class RunStrategy(bt.Strategy):
    """Simple moving average crossover strategy for testing leverage analyzer.

    This strategy generates buy signals when price crosses above the SMA
    and closes positions when price crosses below the SMA.

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
        indicator to detect when price crosses the SMA.
        """
        self.sma = bt.indicators.SMA(self.data, period=self.p.period)
        self.cross = bt.indicators.CrossOver(self.data.close, self.sma)

    def next(self):
        """Execute trading logic for each bar.

        Implements a simple trend-following strategy:
        - Buy when price crosses above SMA (no position exists)
        - Close position when price crosses below SMA
        """
        if not self.position.size:
            if self.cross > 0.0:
                self.buy()
        elif self.cross < 0.0:
            self.close()


chkdatas = 1


def test_run(main=False):
    """Run the GrossLeverage analyzer test.

    Executes a backtest with the GrossLeverage analyzer attached and verifies
    that the analyzer produces valid leverage values.

    Args:
        main (bool): If True, prints analysis results. If False, runs
            assertions to verify correctness. Defaults to False.

    Raises:
        AssertionError: If analysis is not a dict, is empty, or contains
            leverage values outside the valid range [0, 1].
    """
    datas = [testcommon.getdata(i) for i in range(chkdatas)]
    cerebros = testcommon.runtest(
        datas, RunStrategy, printdata=main, plot=main, analyzer=(bt.analyzers.GrossLeverage, {})
    )

    for cerebro in cerebros:
        strat = cerebro.runstrats[0][0]  # no optimization, only 1
        analyzer = strat.analyzers[0]  # only 1
        analysis = analyzer.get_analysis()
        if main:
            # print('GrossLeverage Analysis:')  # Removed for performance
            pass
            print(analysis)
            print(f"Number of leverage readings: {len(analysis)}")
        else:
            # Verify that analysis is a dictionary
            assert isinstance(analysis, dict)
            # Verify we have leverage values
            assert len(analysis) > 0
            # Leverage values should be between 0 (all cash) and 1 (fully invested)
            for dt, lev in analysis.items():
                assert 0 <= lev <= 1, f"Leverage {lev} out of range [0,1]"


if __name__ == "__main__":
    test_run(main=True)
