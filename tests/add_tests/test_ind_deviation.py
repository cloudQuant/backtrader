#!/usr/bin/env python
"""Test module for StandardDeviation indicator.

This module contains tests for the StandardDeviation (Deviation) indicator in backtrader.
It validates that the indicator calculates correct values across different data points
and configurations using the TestStrategy framework.

The test loads data feeds, applies the StandardDeviation indicator with a 30-period
window, and verifies that calculated values match expected results at specific
checkpoint indices.
"""

import backtrader as bt

import backtrader.indicators as btind

from . import testcommon

# Number of data feeds to use in the test
chkdatas = 1

# Expected values for StandardDeviation at checkpoint indices
# Format: [value_at_checkpoint_0, value_at_checkpoint_1, value_at_checkpoint_2]
# These are the expected StandardDeviation values with period=30
chkvals = [
    ["58.042315", "50.824827", "73.944160"],
]

# Expected minimum period for the indicator
chkmin = 30

# The indicator class being tested
chkind = btind.StandardDeviation


def test_run(main=False):
    """Run the StandardDeviation indicator test.

    This function loads test data, creates a backtest with the TestStrategy,
    and validates that the StandardDeviation indicator produces expected
    results. The test can be run in automated mode (main=False) for
    assertion checking, or in manual mode (main=True) for visual inspection
    with plotting.

    Args:
        main (bool, optional): If True, run in manual mode with plotting.
            Defaults to False, which runs automated assertion checks.

    Returns:
        None

    Raises:
        AssertionError: If any calculated indicator values do not match
            the expected values in chkvals.

    Example:
        >>> test_run()  # Automated test with assertions
        >>> test_run(main=True)  # Manual test with plot display
    """
    # Load the specified number of data feeds
    datas = [testcommon.getdata(i) for i in range(chkdatas)]

    # Run the test with the configured parameters
    testcommon.runtest(
        datas,
        testcommon.TestStrategy,
        main=main,
        plot=main,
        chkind=chkind,
        chkmin=chkmin,
        chkargs={"period": 30},
        chkvals=chkvals,
    )


if __name__ == "__main__":
    # Run the test in manual mode when executed directly
    test_run(main=True)
