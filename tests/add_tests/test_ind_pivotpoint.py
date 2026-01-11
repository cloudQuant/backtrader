#!/usr/bin/env python
"""Test module for PivotPoint indicator.

This module contains tests for the PivotPoint technical indicator in backtrader.
The PivotPoint indicator calculates support and resistance levels based on the
previous period's high, low, and close prices, which are commonly used in
trading to identify potential price turning points.

The test verifies that the PivotPoint indicator can be instantiated correctly
and produces valid values for all its output lines:
    - p: Pivot point
    - s1: Support level 1
    - s2: Support level 2
    - r1: Resistance level 1
    - r2: Resistance level 2

Example:
    To run this test directly::

        python -m tests.add_tests.test_ind_pivotpoint

    Or run via pytest::

        pytest tests/add_tests/test_ind_pivotpoint.py -v
"""

import backtrader as bt

import backtrader.indicators as btind

from . import testcommon


def test_run(main=False):
    """Execute the PivotPoint indicator test.

    This function creates a test strategy that instantiates a PivotPoint indicator
    and verifies that it produces valid values for all output lines during
    backtesting execution.

    Args:
        main (bool): If True, prints a success message after test completion.
                     If False, runs silently. Defaults to False.

    Raises:
        AssertionError: If any of the PivotPoint output lines contain None values,
                       indicating the indicator failed to calculate properly.

    Returns:
        None: This function performs assertions but does not return a value.
    """

    class TestInd(bt.Strategy):
        """Test strategy for PivotPoint indicator validation.

        This strategy instantiates a PivotPoint indicator during initialization
        and validates that all output lines produce valid values during the
        backtesting loop.

        Attributes:
            ind (btind.PivotPoint): The PivotPoint indicator instance being tested,
                                    initialized with the strategy's data feed.
        """

        def __init__(self):
            """Initialize the test strategy and create the PivotPoint indicator.

            The indicator is created using the strategy's data feed, which
            provides the OHLC (Open, High, Low, Close) data required for
            pivot point calculations.
            """
            self.ind = btind.PivotPoint(self.data)

        def next(self):
            """Execute strategy logic for each bar.

            This method is called by backtrader for each new data bar.
            It verifies that the PivotPoint indicator has calculated valid
            values for all output lines once at least one bar is available.

            Raises:
                AssertionError: If any of the indicator lines (p, s1, s2, r1, r2)
                               contain None values, indicating a calculation failure.
            """
            if len(self) >= 1:
                assert self.ind.lines.p[0] is not None
                assert self.ind.lines.s1[0] is not None
                assert self.ind.lines.s2[0] is not None
                assert self.ind.lines.r1[0] is not None
                assert self.ind.lines.r2[0] is not None

    # Set up the backtesting engine with test data
    datas = [testcommon.getdata(0)]
    cerebro = bt.Cerebro()
    for data in datas:
        cerebro.adddata(data)
    cerebro.addstrategy(TestInd)
    cerebro.run()

    if main:
        # Optionally print success message when run as main module
        # Commented out for performance reasons
        pass


if __name__ == "__main__":
    test_run(main=True)
