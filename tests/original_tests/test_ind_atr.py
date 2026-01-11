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

"""Test module for Average True Range (ATR) indicator.

This module contains tests for the ATR (Average True Range) technical indicator,
which measures market volatility by decomposing the entire range of an asset
price for that period. The test validates indicator calculation accuracy across
different data configurations and execution modes.

The ATR is calculated using a moving average of the true ranges, which are the
greatest of the following:
    * Current high minus current low
    * Absolute value of current high minus previous close
    * Absolute value of current low minus previous close

Test Configuration:
    * Data source: Single daily OHLCV data feed (2006-day-001.txt)
    * Expected minimum period: 15 bars
    * Checkpoint values: Pre-calculated ATR values for validation
"""

import backtrader as bt

import testcommon

import backtrader.indicators as btind

# Number of data feeds to use in the test
chkdatas = 1

# Expected ATR values at checkpoints
# These values are calculated from the indicator and used for validation
chkvals = [
    ["35.866308", "34.264286", "54.329064"],
]

# Expected minimum period before indicator produces valid output
chkmin = 15

# The indicator class being tested
chkind = btind.ATR


def test_run(main=False):
    """Execute the ATR indicator test.

    This function loads test data, creates a test strategy with the ATR indicator,
    and runs the backtest to validate that the indicator produces expected results.
    The test is run with multiple configuration combinations (runonce, preload,
    exactbars) to ensure compatibility across all execution modes.

    Args:
        main (bool, optional): If True, enables plotting and verbose output.
            Defaults to False, which runs the test silently for automated testing.

    Returns:
        None. The function executes the test and raises an assertion error if
        the indicator values do not match expected results.

    Raises:
        AssertionError: If the calculated ATR values at checkpoints do not match
            the expected values in chkvals.

    Example:
        >>> test_run()  # Run test silently
        >>> test_run(main=True)  # Run test with plotting and verbose output
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
