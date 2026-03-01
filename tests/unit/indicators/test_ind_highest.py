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

"""Test module for the Highest indicator.

This module contains test cases for the backtrader Highest indicator, which
calculates the highest value over a specified period. The test validates that
the indicator produces expected results when applied to sample data.

The test uses a 14-period Highest indicator and verifies the output against
pre-calculated expected values.
"""

import backtrader as bt

import testcommon

import backtrader.indicators as btind

chkdatas = 1
chkvals = [
    ["4140.660000", "3671.780000", "3670.750000"],
]

chkmin = 14
chkind = btind.Highest
chkargs = dict(period=14)


def test_run(main=False):
    """Run the Highest indicator test.

    This function loads test data, applies the Highest indicator with the
    specified parameters, and verifies the results against expected values.

    Args:
        main (bool, optional): If True, enables plotting and main execution mode.
            Defaults to False.

    Returns:
        None

    Raises:
        AssertionError: If the indicator output does not match expected values.
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
