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

"""Test module for Hull Moving Average (HMA) indicator.

This module contains tests for the Hull Moving Average indicator implementation
in backtrader. The HMA is a fast moving average that minimizes lag while
maintaining smoothness.

The test validates that the HMA indicator calculates expected values against
known test data with a minimum period requirement of 34 bars.

Example:
    Run the test directly from the command line:

        python test_ind_hma.py

    Or import and run programmatically:

        from tests.original_tests.test_ind_hma import test_run
        test_run(main=True)
"""

import backtrader as bt

import testcommon

import backtrader.indicators as btind

# Number of data feeds to test
chkdatas = 1

# Expected HMA values for validation
# These are the expected output values from the HMA calculation
chkvals = [
    ["4135.661250", "3736.429214", "3578.389024"],
]

# Minimum period required for HMA indicator
# HMA requires this many bars before producing valid output
chkmin = 34

# The indicator class being tested
chkind = btind.HMA


def test_run(main=False):
    """Execute the HMA indicator test.

    This function loads test data, runs the indicator calculation, and validates
    the output against expected values. The test uses a standard strategy to
    execute the indicator within the backtrader framework.

    Args:
        main (bool): If True, enables plotting and verbose output. When running
            as the main script, this should be set to True to visualize results.
            Defaults to False.

    Returns:
        None: The function runs the test and outputs results to stdout.

    Raises:
        AssertionError: If the calculated HMA values do not match the expected
            values in chkvals.

    Example:
        >>> test_run(main=False)
        >>> test_run(main=True)  # With plotting enabled
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
