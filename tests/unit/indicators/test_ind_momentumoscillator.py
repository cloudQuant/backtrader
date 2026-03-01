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

"""Test module for MomentumOscillator indicator.

This module tests the MomentumOscillator indicator implementation in backtrader.
It validates that the indicator calculates values correctly across different
execution modes (runonce/preload combinations) and checks the minimum period
requirements.

The test loads historical price data, applies the MomentumOscillator indicator,
and verifies that computed values match expected results at specific checkpoints.

Typical usage example:
    test_run()  # Run the test with default parameters
    test_run(main=True)  # Run with plotting enabled
"""

import backtrader as bt

import testcommon

import backtrader.indicators as btind

# Number of data feeds to use for testing
chkdatas = 1

# Expected values at checkpoint positions (beginning, middle, end)
# These values are used to validate indicator calculations
chkvals = [
    ["101.654375", "99.052251", "101.904990"],
]

# Expected minimum period for the MomentumOscillator indicator
chkmin = 13

# The indicator class being tested
chkind = btind.MomentumOscillator


def test_run(main=False):
    """Run the MomentumOscillator indicator test.

    This function loads test data, creates a test strategy with the
    MomentumOscillator indicator, and runs the backtest across multiple
    configuration combinations (runonce/preload modes) to ensure
    compatibility.

    Args:
        main (bool, optional): If True, enable plotting for visual inspection.
            Defaults to False, which runs the test without visualization.

    Returns:
        list: A list of Cerebro instances, one for each test configuration
            (runonce/preload/exactbars combinations).

    Raises:
        AssertionError: If indicator values do not match expected results
            at the checkpoint positions.
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
