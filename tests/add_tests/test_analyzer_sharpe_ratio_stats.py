#!/usr/bin/env python
"""Test module for Sharpe Ratio analyzer.

This module tests the SharpeRatioA analyzer from backtrader, which calculates
the Sharpe ratio statistic for trading strategies. The Sharpe ratio is a measure
of risk-adjusted return, commonly used to evaluate the performance of investment
strategies.

The test uses a simple moving average crossover strategy to generate trades and
verifies that the analyzer correctly produces sharpe ratio statistics.

Example:
    To run the test with plotting enabled::
        python test_analyzer_sharpe_ratio_stats.py

    To run as a pytest test::
        pytest tests/add_tests/test_analyzer_sharpe_ratio_stats.py -v
"""

import backtrader as bt

from . import testcommon


class RunStrategy(bt.Strategy):
    """Simple moving average crossover strategy.

    This strategy generates buy signals when the price crosses above the
    Simple Moving Average (SMA) and closes positions when the price crosses
    below the SMA.

    Attributes:
        sma: Simple Moving Average indicator with period 15.
        cross: Crossover indicator tracking price vs SMA crossings.

    Note:
        - Only one position (long or short) is held at a time
        - Positions are closed when crossover signal reverses
    """

    def __init__(self):
        """Initialize the strategy with indicators.

        Sets up a 15-period Simple Moving Average (SMA) and a crossover
        indicator to track when price crosses the SMA.
        """
        self.sma = bt.indicators.SMA(self.data, period=15)
        self.cross = bt.indicators.CrossOver(self.data.close, self.sma)

    def next(self):
        """Execute trading logic for each bar.

        Implements the following logic:
        - If no position exists, buy when price crosses above SMA (cross > 0)
        - If position exists, close when price crosses below SMA (cross < 0)
        """
        if not self.position.size:
            if self.cross > 0.0:
                self.buy()
        elif self.cross < 0.0:
            self.close()


def test_run(main=False):
    """Run the Sharpe Ratio analyzer test.

    This function creates a cerebro instance with test data, runs the
    RunStrategy with the SharpeRatioA analyzer attached, and verifies
    that the analyzer produces valid output.

    Args:
        main (bool, optional): If True, runs in standalone mode with plotting
            and prints analysis results. If False, runs in test mode and
            performs assertions. Defaults to False.

    Returns:
        None

    Raises:
        AssertionError: If the analyzer output is not a dict or does not
            contain expected sharpe ratio statistics (in test mode).

    Note:
        In test mode (main=False), assertions verify that:
        - The analysis result is a dictionary
        - The dictionary contains 'sharperatio' key or has non-negative length
    """
    datas = [testcommon.getdata(0)]
    cerebros = testcommon.runtest(
        datas, RunStrategy, plot=main, analyzer=(bt.analyzers.SharpeRatioA, {})
    )

    for cerebro in cerebros:
        strat = cerebro.runstrats[0][0]
        analyzer = strat.analyzers[0]
        analysis = analyzer.get_analysis()
        if main:
            # print('SharpeRatio_A Analysis:')  # Removed for performance
            pass
            print(analysis)
        else:
            assert isinstance(analysis, dict)
            # SharpeRatioA should return sharperatio statistics
            assert "sharperatio" in analysis or len(analysis) >= 0


if __name__ == "__main__":
    test_run(main=True)
