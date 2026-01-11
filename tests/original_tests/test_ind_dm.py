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

"""Test module for the Directional Movement (DM) indicator.

This module contains test cases for the Directional Movement indicator (btind.DM),
which measures the positive and negative directional movement in price data.
The DM indicator is a key component of the Directional Movement System developed
by J. Welles Wilder Jr.

The test validates that the DM indicator produces expected values when applied
to test data, using the common test infrastructure.

Typical usage example:
    test_run()  # Run the test programmatically
    python test_ind_dm.py  # Run from command line with plotting
"""

import backtrader as bt

import testcommon

import backtrader.indicators as btind

chkdatas = 1
chkvals = [
    ["15.302485", "31.674648", "15.961767"],
    ["18.839142", "26.946536", "18.161738"],
    ["28.809535", "30.460124", "31.386311"],
    ["24.638772", "18.914537", "21.564611"],
]

chkmin = 42
chkind = btind.DM


def test_run(main=False):
    """Run the DM indicator test.

    This function loads test data, executes a backtest with the DM indicator,
    and validates the results against expected values. It uses the common
    test infrastructure to perform the validation.

    Args:
        main (bool, optional): If True, enables plotting mode for visual
            inspection of results. When running as a script (main=True),
            the chart will be displayed. Defaults to False.

    Returns:
        None: The function executes the test but does not return a value.
            Results are validated internally by testcommon.runtest().

    Raises:
        AssertionError: If the DM indicator values do not match the expected
            values in chkvals.

    Example:
        >>> test_run()  # Run without plotting
        >>> test_run(main=True)  # Run with plotting enabled
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
