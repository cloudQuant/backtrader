#!/usr/bin/env python
"""Test module for Williams %R indicator.

This module contains tests for the Williams %R technical indicator, which is a
momentum indicator that measures overbought and oversold levels. The Williams %R
compares a stock's close to the high-low range over a specific period, typically
14 days.

The test validates that the indicator calculates correctly by comparing computed
values against known expected values at specific checkpoint positions in the data.
"""

import backtrader as bt

import backtrader.indicators as btind

from . import testcommon

# Number of data feeds to use in the test
chkdatas = 1

# Expected values at checkpoint positions for validation
# These values represent the Williams %R indicator output at specific points
# in the data, calculated from known historical data
chkvals = [
    ["-16.458733", "-68.298609", "-28.602854"],
]

# Expected minimum period for the indicator
# Williams %R typically needs at least 'period' data points before first valid value
chkmin = 14

# The indicator class being tested
chkind = btind.WilliamsR


def test_run(main=False):
    """Run the Williams %R indicator test.

    This function executes a backtest using the Williams %R indicator and
    validates the calculated values against expected results. The test is
    run with various configuration combinations (runonce, preload, exactbars)
    to ensure compatibility across all execution modes.

    The test loads historical data, applies the Williams %R indicator with
    default parameters, and compares the computed values at checkpoint
    positions against known expected values.

    Args:
        main (bool, optional): If True, enables plotting and verbose output
            for manual inspection. If False, runs in automated test mode
            with assertions. Defaults to False.

    Returns:
        None: The function raises AssertionError if validation fails.

    Raises:
        AssertionError: If the indicator values don't match expected values
            at checkpoint positions, or if other validation criteria fail.
    """
    # Load the required number of data feeds for testing
    datas = [testcommon.getdata(i) for i in range(chkdatas)]

    # Run the test with the common test framework
    testcommon.runtest(
        datas,
        testcommon.TestStrategy,
        main=main,
        plot=main,
        chkind=chkind,
        chkmin=chkmin,
        chkvals=chkvals,
    )


if __name__ == "__main__":
    # Run the test with plotting enabled when executed directly
    test_run(main=True)
