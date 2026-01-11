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

"""Test module for the Momentum indicator.

This module contains tests for the Momentum indicator implementation in backtrader.
The Momentum indicator measures the rate of change (speed) of price movements
by comparing the current price to the price N periods ago.

The test validates that the Momentum indicator:
  * Calculates correct values at specific checkpoints
  * Uses the correct minimum period (period parameter)
  * Works with the standard test data feed (2006-day-001.txt)

Test Configuration:
  * Data Source: Single data feed (2006-day-001.txt)
  * Indicator: bt.indicators.Momentum
  * Period: Default period (typically 13)
  * Checkpoints: Final values for validation

Expected Values:
  * The test validates indicator values at three checkpoints:
    - First bar after minimum period
    - Middle of data series
    - Final bar of data series
"""

import backtrader as bt

import testcommon

import backtrader.indicators as btind

# Number of data feeds to use in the test
chkdatas = 1

# Expected values at checkpoint positions
# Format: list of lists, where each inner list contains string-formatted float values
# for different lines of the indicator at checkpoint positions
chkvals = [
    ["67.050000", "-34.160000", "67.630000"],
]

# Expected minimum period for the Momentum indicator
# The Momentum indicator needs 'period' bars before producing valid output
chkmin = 13

# The indicator class being tested
chkind = btind.Momentum


def test_run(main=False):
    """Run the Momentum indicator test.

    Executes a backtest using the TestStrategy with the Momentum indicator
    and validates the calculated values against expected results.

    The test uses multiple cerebro configurations (runonce/preload/exactbars
    combinations) to ensure the indicator works correctly across all execution
    modes.

    Args:
        main (bool, optional): If True, run in main mode with plotting enabled.
            When False, runs silently for automated testing. Defaults to False.

    Returns:
        None. The function executes tests and raises assertions if validation fails.

    Raises:
        AssertionError: If calculated indicator values do not match expected
            values at checkpoint positions.

    Example:
        >>> test_run()  # Run automated tests
        >>> test_run(main=True)  # Run with plotting for manual inspection
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
