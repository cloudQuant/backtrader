#!/usr/bin/env python
"""Test module for Parabolic SAR indicator.

This module contains tests for the Parabolic Stop and Reverse (SAR) indicator,
which is a trend-following indicator that sets trailing price levels for long
and short positions. The indicator is used to determine trend direction and
potential reversals.

The test validates that the ParabolicSAR indicator calculates values correctly
by comparing computed results against known expected values at specific
checkpoints in the data.
"""

import backtrader as bt
import backtrader.indicators as btind
from . import testcommon

# Number of data feeds to use for testing
chkdatas = 1

# Expected values at checkpoints for validation
# Format: [expected_values_at_checkpoint_0, expected_values_at_checkpoint_1, ...]
# Each checkpoint corresponds to a specific position in the data series
chkvals = [
    ["4079.700000", "3578.730000", "3420.471369"],
]

# Expected minimum period before indicator produces valid output
chkmin = 2

# Indicator class to test
chkind = btind.ParabolicSAR


def test_run(main=False):
    """Run the Parabolic SAR indicator test.

    This function executes the test by loading test data, running the test
    strategy with the ParabolicSAR indicator, and validating the computed
    values against expected results. The test can be run in automated mode
    (default) or manual mode with plotting enabled.

    Args:
        main (bool, optional): If True, run in manual mode with plotting.
            Enables visual inspection of results. Defaults to False.

    Returns:
        None: The function runs the test and assertions validate results.

    Raises:
        AssertionError: If computed indicator values do not match expected values
            at any checkpoint, or if the minimum period is incorrect.
    """
    datas = [testcommon.getdata(i) for i in range(chkdatas)]
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
    test_run(main=True)
