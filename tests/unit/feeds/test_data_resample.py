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

"""Test module for data resampling functionality in backtrader.

This module tests the resampling of data from daily timeframe to weekly timeframe.
It validates that indicators (specifically SMA) produce correct values when applied
to resampled data.

The test loads daily price data, resamples it to weekly bars, and then verifies
that the SMA indicator calculates expected values at specific checkpoints.
"""

import backtrader as bt

import testcommon

import backtrader.indicators as btind

# Module-level constants for test validation
chkdatas = 1  # Number of data feeds to use
chkvals = [["3836.453333", "3703.962333", "3741.802000"]]  # Expected SMA values

chkmin = 30  # Expected minimum period (will be in weeks)
chkind = [btind.SMA]  # Indicator class to test
chkargs = dict()  # Additional arguments for indicator creation


def test_run(main=False):
    """Run the data resampling test with multiple execution modes.

    This function tests data resampling from daily to weekly timeframe with
    both runonce=True and runonce=False modes to ensure compatibility
    across different execution strategies.

    Args:
        main (bool, optional): If True, enables plotting for visual inspection.
            Defaults to False (automated test mode).

    Returns:
        None: The function executes tests and validates results through
            the testcommon.runtest framework.

    Raises:
        AssertionError: If indicator values don't match expected results
            at checkpoints.
    """
    for runonce in [True, False]:
        data = testcommon.getdata(0)
        data.resample(timeframe=bt.TimeFrame.Weeks, compression=1)

        datas = [data]
        testcommon.runtest(
            datas,
            testcommon.TestStrategy,
            main=main,
            runonce=runonce,
            plot=main,
            chkind=chkind,
            chkmin=chkmin,
            chkvals=chkvals,
            chkargs=chkargs,
        )


if __name__ == "__main__":
    test_run(main=True)
