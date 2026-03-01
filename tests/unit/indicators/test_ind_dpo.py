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

"""Test module for the Detrended Price Oscillator (DPO) indicator.

This module contains test cases for the DPO indicator implementation in
backtrader. The DPO is designed to remove trends from prices, making it
easier to identify cycles and overbought/oversold conditions.

The test validates:
* Indicator calculation accuracy against expected values
* Minimum period requirements for the indicator
* Proper data feed handling
"""

import backtrader as bt

import testcommon

import backtrader.indicators as btind

# Number of data feeds to use in the test
chkdatas = 1

# Expected values for the DPO indicator at specific bars
# These are the reference values that the test will validate against
chkvals = [
    ["83.271000", "105.625000", "1.187000"],
]

# Minimum period required before the DPO indicator produces valid values
# The DPO needs enough data to calculate the moving average for detrending
chkmin = 29

# The indicator class being tested
chkind = btind.DPO


def test_run(main=False):
    """Execute the DPO indicator test.

    This function sets up the test environment by loading data feeds,
    running the test strategy, and validating the indicator output
    against expected values.

    Args:
        main (bool): If True, enables plotting and runs in standalone mode.
            When False (default), runs in test mode without visualization.
            Defaults to False.

    Returns:
        None

    Raises:
        AssertionError: If the calculated indicator values do not match
            the expected values in chkvals.

    Example:
        Run the test in normal mode:
        >>> test_run()

        Run the test with plotting:
        >>> test_run(main=True)
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
