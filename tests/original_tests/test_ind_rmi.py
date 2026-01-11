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

"""Test module for the Relative Momentum Index (RMI) indicator.

This module contains test cases for the RMI indicator implementation in
backtrader. The RMI is a variation of the RSI (Relative Strength Index) that
uses momentum over a specified period instead of just price changes.

The test validates that the RMI indicator produces expected values for
given data inputs, checking against known correct outputs.
"""

import backtrader as bt

import testcommon

# Number of data feeds to use in the test
chkdatas = 1

# Expected RMI indicator values for validation
chkvals = [["67.786097", "59.856230", "38.287526"]]

# Minimum period required for the indicator to be valid
chkmin = 25

# The indicator class being tested
chkind = bt.ind.RMI


def test_run(main=False):
    """Run the RMI indicator test.

    This function executes a test of the RMI (Relative Momentum Index)
    indicator by loading test data, running the indicator calculation,
    and comparing the results against expected values.

    Args:
        main (bool): If True, runs in standalone mode with plotting enabled.
            When False, runs in test mode without plotting. Defaults to False.

    Returns:
        None

    Raises:
        AssertionError: If the calculated indicator values do not match
            the expected values in chkvals.

    Example:
        Run the test in standalone mode with plotting:
        >>> test_run(main=True)

        Run the test in automated test mode:
        >>> test_run()
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
