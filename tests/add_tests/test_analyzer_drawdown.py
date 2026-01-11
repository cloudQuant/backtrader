#!/usr/bin/env python
"""Test module for DrawDown and TimeDrawDown analyzers.

This module contains tests for the backtrader drawdown analyzers, which measure
the decline from a historical peak in trading value. Two types of drawdown
analyzers are tested:

1. DrawDown: Measures the percentage and monetary drawdown from peak equity
2. TimeDrawDown: Measures the time duration of drawdown periods

Example:
    Run the tests with:
        python -m pytest tests/add_tests/test_analyzer_drawdown.py -v

    Run standalone with visualization:
        python tests/add_tests/test_analyzer_drawdown.py
"""

import backtrader as bt

from . import testcommon


class RunStrategy(bt.Strategy):
    """Simple moving average crossover strategy for testing drawdown analyzers.

    This strategy generates buy and sell signals based on the crossover of
    price and a simple moving average (SMA). When price crosses above the SMA,
    a long position is entered. When price crosses below the SMA, the position
    is closed.

    Attributes:
        sma: Simple moving average indicator
        cross: Crossover indicator showing when price crosses the SMA

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

        Creates a simple moving average (SMA) indicator and a crossover
        indicator to detect when price crosses above or below the SMA.
        """
        self.sma = bt.indicators.SMA(self.data, period=self.p.period)
        self.cross = bt.indicators.CrossOver(self.data.close, self.sma)

    def next(self):
        """Execute trading logic for each bar.

        Implements a simple trend-following strategy:
        - If not in a position, buy when price crosses above SMA
        - If in a position, close when price crosses below SMA
        """
        if not self.position.size:
            if self.cross > 0.0:
                self.buy()
        elif self.cross < 0.0:
            self.close()


chkdatas = 1
"""int: Number of data feeds to use in testing.

This constant specifies how many data feeds should be loaded for each test run.
Multiple data feeds allow for testing portfolio-level drawdown calculations.
"""


def test_run(main=False):
    """Test DrawDown and TimeDrawDown analyzers with sample data.

    This test function runs the RunStrategy strategy through backtrader with
    both DrawDown and TimeDrawDown analyzers attached. It verifies that:

    1. The analyzers produce valid dictionary output
    2. DrawDown analyzer contains expected fields (len, max, drawdown, len)
    3. TimeDrawDown analyzer contains expected fields (maxdrawdown)
    4. Drawdown values are positive when drawdowns occur
    5. Specific expected values match the backtest results

    Args:
        main (bool): If True, runs in standalone mode with printing and plotting.
                     If False, runs in test mode with assertions. Defaults to False.

    Raises:
        AssertionError: If analyzer output format is invalid or values are unexpected.
    """
    datas = [testcommon.getdata(i) for i in range(chkdatas)]
    # Test both DrawDown and TimeDrawDown
    for analyzer_class in [bt.analyzers.DrawDown, bt.analyzers.TimeDrawDown]:
        cerebros = testcommon.runtest(
            datas, RunStrategy, printdata=main, plot=main, analyzer=(analyzer_class, {})
        )

        for cerebro in cerebros:
            strat = cerebro.runstrats[0][0]  # no optimization, only 1
            analyzer = strat.analyzers[0]  # only 1
            analysis = analyzer.get_analysis()
            if main:
                # print(f'{analyzer_class.__name__} Analysis:')  # Removed for performance
                pass
                print(analysis)
            else:
                # Verify that analysis is a dictionary
                assert isinstance(analysis, dict)
                # Verify expected keys exist
                if analyzer_class == bt.analyzers.DrawDown:
                    assert "len" in analysis
                    assert "max" in analysis
                    # Verify specific values from actual run
                    assert hasattr(analysis.max, "drawdown")
                    assert hasattr(analysis.max, "len")
                    # Verify max drawdown and length (from actual run)
                    assert analysis.max.drawdown > 0  # Should have some drawdown
                    assert analysis.max.len > 0  # Should have length > 0
                    assert analysis.max.len == 157  # Specific value from run
                else:  # TimeDrawDown
                    assert "maxdrawdown" in analysis
                    assert analysis["maxdrawdown"] >= 0


if __name__ == "__main__":
    test_run(main=True)
