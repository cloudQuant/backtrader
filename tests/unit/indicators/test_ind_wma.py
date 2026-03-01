#!/usr/bin/env python
###############################################################################
#
# Copyright (C) 2015-2023 Daniel Rodriguez
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
###############################################################################
"""Test module for Weighted Moving Average (WMA) indicator.

This module contains tests for the WMA (Weighted Moving Average) indicator
in the backtrader framework. It validates that the WMA indicator calculates
values correctly across different execution modes (runonce/preload combinations)
and verifies the minimum period requirements.

The test loads historical price data, applies the WMA indicator with a
30-period window, and validates the calculated values against known
expected results at specific checkpoints.
"""

import backtrader as bt

import testcommon

import backtrader.indicators as btind

# Number of data feeds to test with
chkdatas = 1

# Expected WMA values at checkpoints (start, middle, end of data)
# These values are validated against the actual indicator output
chkvals = [
    ["4076.212366", "3655.193634", "3576.228000"],
]

# Expected minimum period for the WMA indicator
chkmin = 30

# The indicator class being tested
chkind = btind.WMA


def test_run(main=False):
    """Run the WMA indicator test.

    This function loads test data, creates a backtest strategy with the WMA
    indicator, and validates the indicator's calculated values against expected
    results. The test can be run in two modes:

    * Automated test mode (main=False): Runs assertions to validate correctness
    * Manual inspection mode (main=True): Plots results for visual inspection

    Args:
        main (bool, optional): If True, enables plot output for manual inspection.
            Defaults to False, which runs the test without plotting for automated
            testing.

    Returns:
        None. The function either raises an AssertionError if validation fails,
        or completes silently if all tests pass.

    Raises:
        AssertionError: If the calculated WMA values do not match the expected
            values in chkvals, or if the minimum period does not match chkmin.

    Example:
        >>> test_run()  # Run automated test
        >>> test_run(main=True)  # Run with plot for visual inspection
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
