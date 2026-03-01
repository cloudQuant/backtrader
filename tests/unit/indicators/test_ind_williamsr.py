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

"""Test module for Williams %R indicator.

This module contains test cases for the Williams %R technical indicator
implementation in backtrader. The Williams %R is a momentum indicator that
measures overbought and oversold levels, developed by Larry Williams.

The test verifies that the indicator calculates values correctly by comparing
the output against known expected values for specific data points.
"""

import backtrader as bt

import testcommon

import backtrader.indicators as btind

# Number of data feeds to use in the test
chkdatas = 1

# Expected Williams %R values for verification
# These are the known correct values for specific data points
chkvals = [
    ["-16.458733", "-68.298609", "-28.602854"],
]

# Minimum period required for Williams %R calculation
# Williams %R typically uses a 14-period lookback
chkmin = 14

# The indicator class being tested
chkind = btind.WilliamsR


def test_run(main=False):
    """Execute the Williams %R indicator test.

    This function loads test data, runs the indicator calculation, and verifies
    the results against expected values. It uses the common test infrastructure
    to perform the validation.

    Args:
        main (bool, optional): If True, enables plotting and interactive mode.
            Defaults to False. When False, runs in automated test mode without
            visual output.

    Returns:
        None

    Raises:
        AssertionError: If the calculated indicator values do not match the
            expected values in chkvals.
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
