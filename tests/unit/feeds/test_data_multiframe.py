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

"""Test module for multi-frame data feeds in backtrader.

This module tests the functionality of running backtrader strategies with multiple
data feeds operating on different timeframes (e.g., daily and weekly data). It
verifies that indicators correctly calculate across different timeframe granularities
and that the strategy can handle data alignment between timeframes.

The test uses two data feeds and validates that SMA indicators work correctly
when data has different periodicities. The minimum bar count is set to 151
to accommodate the weekly data timeframe requirements.
"""

import backtrader as bt

import testcommon

import backtrader.indicators as btind

chkdatas = 2
chkvals = []

chkmin = 151  # because of the weekly data
chkind = [btind.SMA]
chkargs = dict()


def test_run(main=False):
    """Run the multi-frame data test.

    This function loads multiple data feeds with different timeframes and
    executes a backtest using the TestStrategy from testcommon. It validates
    that indicators and strategies work correctly when data has different
    periodicities.

    Args:
        main (bool, optional): If True, enables plotting for visual inspection.
            Defaults to False, which runs the test without plotting.

    Returns:
        None: The function executes the test and prints/comparares results
            but does not return a value.

    Raises:
        AssertionError: If indicator values do not match expected results.
        Exception: If data loading or backtest execution fails.
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
    # Run the test with plotting enabled when executed as a script
    test_run(main=True)
