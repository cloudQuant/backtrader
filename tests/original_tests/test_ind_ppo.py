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
"""Test module for the Percentage Price Oscillator (PPO) indicator.

This module contains tests to validate the PPO indicator implementation in
backtrader. The PPO is a momentum oscillator that measures the difference
between two moving averages as a percentage of the larger moving average.

The test verifies:
1. Indicator calculation accuracy at specific checkpoints
2. Minimum period requirements
3. Multiple data feed handling
4. Compatibility across different execution modes (runonce/preload combinations)

Test Data:
    - Data files: 2006-day-001.txt (daily OHLCV data)
    - Checkpoints: Beginning, middle, and end of data series
    - Expected values: Pre-calculated PPO values for validation
"""

import backtrader as bt

import testcommon

import backtrader.indicators as btind

chkdatas = 1
chkvals = [
    ["0.633439", "0.883552", "0.049430"],
    ["0.540516", "0.724136", "-0.079820"],
    ["0.092923", "0.159416", "0.129250"],
]

chkmin = 34
chkind = btind.PPO


def test_run(main=False):
    """Execute the PPO indicator test.

    This function loads test data and runs the PPO indicator through multiple
    test configurations using the TestStrategy. The test validates indicator
    calculations against expected values at specific checkpoints.

    Args:
        main (bool, optional): If True, enables plotting and verbose output.
            Used when running the test directly for manual inspection.
            Defaults to False.

    Returns:
        None. The function runs tests and asserts against expected values.

    Raises:
        AssertionError: If calculated PPO values do not match expected values
            at the defined checkpoints.

    Examples:
        Run test without plotting::

            test_run()

        Run test with plotting for visual inspection::

            test_run(main=True)
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
