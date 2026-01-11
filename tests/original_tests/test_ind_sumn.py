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

"""Test module for the SumN indicator.

This module contains test cases for the SumN (Sum over N periods) indicator
in the backtrader framework. The SumN indicator calculates the sum of data
values over a specified period.

The test validates that:
1. The indicator correctly calculates the sum of values over a 14-period window
2. The minimum period requirement is properly enforced (14 periods)
3. The calculated values match expected results at specific data points

Example:
    To run the test with plot output:
        python test_ind_sumn.py

    To run the test programmatically:
        test_ind_sumn.test_run(main=False)
"""

import backtrader as bt

import testcommon

import backtrader.indicators as btind

# Number of data feeds to use in the test
chkdatas = 1

# Expected values for the SumN indicator at specific data points
# These values represent the sum of the previous 14 periods' data
chkvals = [
    ["57406.490000", "50891.010000", "50424.690000"],
]

# Minimum period required before the indicator produces valid values
chkmin = 14

# The indicator class being tested
chkind = btind.SumN

# Arguments to pass to the indicator constructor
chkargs = dict(period=14)


def test_run(main=False):
    """Run the SumN indicator test.

    This function executes a test of the SumN indicator by loading test data,
    running a backtest with the indicator applied, and validating the results
    against expected values.

    Args:
        main (bool, optional): If True, enables plot output for visual
            inspection of the test results. Defaults to False.

    Returns:
        None: The function runs the test and outputs results to stdout.

    Raises:
        AssertionError: If the indicator values do not match the expected
            values in chkvals.
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
        chkargs=chkargs,
    )


if __name__ == "__main__":
    test_run(main=True)
