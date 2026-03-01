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
"""Test module for the DownMove indicator.

This module tests the DownMove indicator implementation in backtrader. The DownMove
indicator measures the magnitude of downward price movements over a specified period.

The test validates:
* Correct calculation of downward price movements
* Minimum period requirements (chkmin = 2)
* Expected values at specific checkpoints

Test Configuration:
    * chkdatas: Number of data feeds to test (1)
    * chkvals: Expected indicator values at checkpoints
        [0] - "10.720000": First checkpoint value
        [1] - "-10.010000": Second checkpoint value
        [2] - "-14.000000": Third checkpoint value
    * chkmin: Expected minimum period (2 bars)
    * chkind: Indicator class to test (DownMove)
"""

import backtrader as bt

import testcommon

import backtrader.indicators as btind

chkdatas = 1
chkvals = [
    ["10.720000", "-10.010000", "-14.000000"],
]

chkmin = 2
chkind = btind.DownMove


def test_run(main=False):
    """Run the DownMove indicator test.

    This function loads test data and executes the test strategy with various
    backtrader configurations (runonce, preload, exactbars) to validate the
    DownMove indicator implementation.

    Args:
        main (bool, optional): If True, enable plotting and verbose output for
            manual inspection. Defaults to False.

    Returns:
        None: The function runs the test and displays results if main=True,
            or performs silent validation otherwise.

    Raises:
        AssertionError: If the indicator values do not match expected values
            at the checkpoints, or if minimum period requirements are not met.
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
