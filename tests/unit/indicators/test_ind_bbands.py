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

"""Test module for Bollinger Bands indicator.

This module contains test cases for the Bollinger Bands (BBands) indicator
in the backtrader framework. It verifies that the indicator correctly calculates
the upper band, middle band (simple moving average), and lower band based on
the input data.

The test uses predefined expected values to validate the indicator's output
across different data feeds and ensures the minimum period requirement is met.
"""

import backtrader as bt

import testcommon

import backtrader.indicators as btind

# Number of data feeds to test
chkdatas = 1

# Expected values for BBands indicator: [mid, top, bot]
# Each inner array represents expected values for a different data feed
chkvals = [
    ["4065.884000", "3621.185000", "3582.895500"],
    ["4190.782310", "3712.008864", "3709.453081"],
    ["3940.985690", "3530.361136", "3456.337919"],
]

# Minimum period required for BBands calculation (default period is 20)
chkmin = 20

# The indicator class being tested
chkind = btind.BBands


def test_run(main=False):
    """Run the Bollinger Bands indicator test.

    This function executes the test for the BBands indicator by loading test
    data, running the test strategy, and comparing the results against expected
    values.

    Args:
        main (bool): If True, enables plotting and runs in main execution mode.
            Defaults to False.

    Returns:
        None: The function runs the test but does not return a value. Results
            are asserted through the testcommon.runtest function.

    Raises:
        AssertionError: If the indicator values do not match the expected values.
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
