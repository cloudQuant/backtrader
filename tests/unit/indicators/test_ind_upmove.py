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

"""Test module for the UpMove indicator.

This module contains test cases for the UpMove technical indicator, which
measures upward price movements in financial data. The test validates that
the indicator correctly calculates and reports upward price changes.

The test uses a single data feed and verifies the indicator values against
expected results for different time periods.
"""

import backtrader as bt

import testcommon

import backtrader.indicators as btind

# Number of data feeds to use in the test
chkdatas = 1

# Expected output values for the UpMove indicator at different periods
chkvals = [
    ["-10.720000", "10.010000", "14.000000"],
]

# Minimum period required for the indicator to produce valid output
chkmin = 2

# The indicator class being tested
chkind = btind.UpMove


def test_run(main=False):
    """Execute the UpMove indicator test.

    This function loads test data, runs the backtest using the TestStrategy,
    and validates that the UpMove indicator produces the expected values.

    Args:
        main (bool, optional): If True, enables plotting and runs as the main
            test execution. If False, runs in automated test mode without
            plotting. Defaults to False.

    Returns:
        None

    Raises:
        AssertionError: If the indicator values do not match the expected
            results defined in chkvals.

    Example:
        >>> test_run(main=False)  # Run automated test
        >>> test_run(main=True)   # Run with plot output
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
