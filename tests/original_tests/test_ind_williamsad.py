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

"""Test module for Williams Accumulation/Distribution indicator.

This module contains test cases for the Williams Accumulation/Distribution (WilliamsAD)
indicator implementation in backtrader. The WilliamsAD is a cumulative indicator that
measures buying and selling pressure by analyzing the relationship between price
closing positions within the period's range.

The test validates that the WilliamsAD indicator calculates correct values by
comparing the computed indicator values against expected results for a given
dataset.
"""

import backtrader as bt

import testcommon

import backtrader.indicators as btind

# Number of data feeds to use in the test
chkdatas = 1

# Expected values for the WilliamsAD indicator at specific data points
# Format: ["last_value", "penultimate_value", "antepenultimate_value"]
chkvals = [["755.050000", "12.500000", "242.980000"]]

# Minimum period required for the indicator to produce valid output
chkmin = 2

# The indicator class being tested
chkind = btind.WilliamsAD


def test_run(main=False):
    """Execute the WilliamsAD indicator test.

    This function sets up the test data feed and runs the indicator test
    using the common test infrastructure. It loads the specified number
    of data feeds, applies the test strategy, and validates the indicator
    output against expected values.

    Args:
        main (bool, optional): Whether to run in main mode. When True,
            enables plotting. Defaults to False.

    Returns:
        None: The function runs the test but does not return a value.
            Test results are reported through the test framework.

    Raises:
        No specific exceptions are raised by this function. Any
        exceptions from the underlying test framework will propagate.
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
