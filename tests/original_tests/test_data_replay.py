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

"""Test module for data replay functionality in backtrader.

This module tests the replay feature of backtrader, which allows data to be
replayed at a different timeframe than the original data. Specifically, this
test validates replaying daily data as weekly bars, ensuring that indicators
calculate correctly on the replayed data.

The test uses Simple Moving Average (SMA) indicators to verify that the replay
mechanism properly aggregates and presents data at the target timeframe.

Example:
    Run the test from the command line:
        python test_data_replay.py

    Or import and run programmatically:
        from tests.original_tests.test_data_replay import test_run
        test_run(main=True)
"""

import backtrader as bt

import testcommon

import backtrader.indicators as btind

# Test configuration constants
chkdatas = 1
chknext = 113
chkvals = [["3836.453333", "3703.962333", "3741.802000"]]

chkmin = 30  # period will be in weeks
chkind = [btind.SMA]
chkargs = dict()


def test_run(main=False, exbar=False):
    """Execute a backtest with replayed data.

    This function sets up and runs a backtest using data replayed from daily
    to weekly timeframe. It tests the replay functionality by running a
    strategy with SMA indicators and verifying the calculated values match
    expected results.

    The replay feature allows data to be aggregated and replayed at a different
    timeframe than the original. In this case, daily data is replayed as weekly
    bars, with the compression parameter set to 1.

    Args:
        main (bool, optional): Whether to display plot results. Defaults to False.
            When True, the backtest will generate a plot of the results.
        exbar (bool or int, optional): Extra bar configuration for testing.
            Can be False, -1, or -2. Defaults to False. This parameter controls
            how extra bars are handled in the test framework.

    Returns:
        None: This function executes the test but does not return a value.
            Results are verified internally by the test framework.

    Raises:
        AssertionError: If the calculated indicator values do not match the
            expected values in chkvals, or if the number of next() calls
            does not match chknext.

    Example:
        Run test without plotting:
            >>> test_run()

        Run test with plotting:
            >>> test_run(main=True)

        Run with different extra bar configurations:
            >>> for exbar in [False, -1, -2]:
            ...     test_run(main=True, exbar=exbar)
    """
    data = testcommon.getdata(0)
    data.replay(timeframe=bt.TimeFrame.Weeks, compression=1)
    datas = [data]
    testcommon.runtest(
        datas,
        testcommon.TestStrategy,
        main=main,
        plot=main,
        chkind=chkind,
        chkmin=chkmin,
        chkvals=chkvals,
        chknext=chknext,
        chkargs=chkargs,
        runonce=False,
        preload=False,
        exbar=exbar,
    )


if __name__ == "__main__":
    for exbar in [False, -1, -2]:
        test_run(main=True, exbar=exbar)
