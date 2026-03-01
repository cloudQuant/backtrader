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

"""Test module for the PercentRank indicator.

This module contains test cases for the PercentRank (pctrank) indicator in
backtrader. The PercentRank indicator calculates the percentile rank of a
value within a given period, showing where the current value falls within
the historical distribution.

The test validates that the PercentRank indicator:
* Calculates correct percentile rank values
* Handles the minimum period requirement correctly
* Produces expected output at specific checkpoints
* Works correctly with the test data set

Test Configuration:
    Data Sources: Uses 1 data feed (2006-day-001.txt)
    Indicator: backtrader.indicators.PercentRank
    Minimum Period: 50 bars
    Expected Values: Validated at specific checkpoints

Module Constants:
    chkdatas: Number of data feeds to use (1)
    chkvals: Expected indicator values at test checkpoints
    chkmin: Expected minimum period for the indicator (50)
    chkind: The indicator class being tested (PercentRank)
"""

import backtrader as bt

import testcommon

import backtrader.indicators as btind

chkdatas = 1
chkvals = [
    ["0.900000", "0.880000", "0.980000"],
]

chkmin = 50
chkind = btind.PercentRank


def test_run(main=False):
    """Run the PercentRank indicator test.

    Executes a backtest using the TestStrategy with the PercentRank indicator
    to validate that the indicator produces expected values. The test is run
    with multiple configuration combinations (runonce, preload, exactbars)
    to ensure compatibility across all execution modes.

    The test loads data feeds, applies the PercentRank indicator with a
    period of 50, and validates the calculated values against expected
    results at specific checkpoints.

    Args:
        main (bool, optional): If True, enables plotting and verbose output.
            Defaults to False, which runs the test in silent mode suitable
            for automated testing.

    Returns:
        None. The function executes the test and implicitly validates results
        through assertions in the TestStrategy.stop() method.

    Raises:
        AssertionError: If indicator values do not match expected results
            at the defined checkpoints. This is raised during the strategy's
            stop() method execution.
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
