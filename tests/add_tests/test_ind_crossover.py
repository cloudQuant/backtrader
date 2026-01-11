#!/usr/bin/env python
"""Test module for the CrossOver indicator in Backtrader.

This module contains tests to verify the functionality of the CrossOver indicator,
which detects when one data series crosses over or under another data series.
The CrossOver indicator returns 1 when the first series crosses above the second,
-1 when it crosses below, and 0 when there is no crossover.

Example:
    To run the test directly::

        python test_ind_crossover.py

    To run via pytest::

        pytest tests/add_tests/test_ind_crossover.py -v
"""

import backtrader as bt

import backtrader.indicators as btind

from . import testcommon


def test_run(main=False):
    """Execute the CrossOver indicator test.

    This function creates a test strategy that uses two Simple Moving Averages
    (SMA) with different periods and applies the CrossOver indicator to detect
    when the faster SMA crosses the slower SMA. The test verifies that the
    CrossOver indicator produces valid values (-1, 0, or 1) after the minimum
    period is reached.

    The test uses sample data and runs a backtest to ensure the indicator
    functions correctly within the Backtrader framework.

    Args:
        main (bool, optional): If True, enables print statements for manual
            testing. Defaults to False for automated testing.

    Raises:
        AssertionError: If the CrossOver indicator produces a value outside
            the valid range of [-1, 0, 1].
        AssertionError: If the backtest results are empty or invalid.

    Returns:
        None: This function performs assertions but does not return a value.
    """

    # Test CrossOver functionality
    class TestCrossStrategy(bt.Strategy):
        """Test strategy for validating CrossOver indicator behavior.

        This strategy sets up two Simple Moving Averages with different periods
        (15 and 30) and creates a CrossOver indicator to detect crossovers
        between them. During execution, it validates that the CrossOver indicator
        only produces valid values.

        Attributes:
            crossover (bt.indicators.CrossOver): The crossover indicator that
                tracks when the 15-period SMA crosses the 30-period SMA.
        """

        def __init__(self):
            """Initialize the TestCrossStrategy.

            Creates two Simple Moving Average indicators with different periods
            and a CrossOver indicator to detect when the faster SMA crosses
            the slower SMA.
            """
            sma1 = btind.SMA(self.data, period=15)
            sma2 = btind.SMA(self.data, period=30)
            self.crossover = btind.CrossOver(sma1, sma2)

        def next(self):
            """Execute trading logic for each bar.

            Validates that the CrossOver indicator produces valid values after
            the minimum period (30 bars) has been reached. The CrossOver
            indicator should return 1 (crossed above), -1 (crossed below), or 0
            (no crossover).

            Raises:
                AssertionError: If the crossover value is not in [-1, 0, 1].
            """
            # Verify crossover produces values
            if len(self) >= 30:
                # CrossOver returns 1, -1, or 0
                assert self.crossover[0] in [-1, 0, 1]

    datas = [testcommon.getdata(0)]
    cerebro = bt.Cerebro()
    for data in datas:
        cerebro.adddata(data)
    cerebro.addstrategy(TestCrossStrategy)
    results = cerebro.run()

    # Verify test ran
    assert len(results) > 0
    assert len(results[0]) > 0

    if main:
        # Print statement removed for performance optimization
        pass


if __name__ == "__main__":
    test_run(main=True)
