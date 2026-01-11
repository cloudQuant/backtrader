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
"""Test module for RSI_Safe indicator.

This module tests the RSI_Safe (Relative Strength Index Safe) indicator implementation
in backtrader. The RSI_Safe indicator is a variation of the standard RSI that handles
edge cases more safely, particularly during initialization and when there is insufficient
data.

The test validates that the RSI_Safe indicator produces expected values at specific
checkpoints in the data series, ensuring correct calculation across different market
conditions and data scenarios.

Test Configuration:
    - Data Source: Single data feed from 2006 daily data
    - Indicator: RSI_Safe with default parameters
    - Minimum Period: 15 bars
    - Expected Values: Pre-calculated RSI values at specific checkpoints

Example:
    To run this test directly::

        python test_ind_rsi_safe.py

    To run via pytest::

        pytest tests/original_tests/test_ind_rsi_safe.py -v
"""

import backtrader as bt

import testcommon

import backtrader.indicators as btind

# Number of data feeds to use in the test
chkdatas = 1

# Expected RSI_Safe values at checkpoints
# Format: List of lists, where each inner list contains values for different lines
# These values are validated against the actual indicator output
chkvals = [
    ["57.644284", "41.630968", "53.352553"],
]

# Expected minimum period for the RSI_Safe indicator
# The RSI_Safe requires at least this many bars before producing valid output
chkmin = 15

# The indicator class being tested
chkind = btind.RSI_Safe


def test_run(main=False):
    """Run the RSI_Safe indicator test.

    This function loads the test data, creates a strategy with the RSI_Safe indicator,
    and runs the backtest with various configuration combinations. When run in main
    mode, it will also display plot results for visual inspection.

    The test uses the common test infrastructure (testcommon) to validate that the
    indicator produces expected values at specific checkpoints in the data series.

    Args:
        main (bool, optional): If True, run in main mode which enables plotting
            and verbose output. Defaults to False, which runs in automated test mode.

    Returns:
        None. The function executes the test and relies on assertions within
        the test infrastructure to validate results.

    Example:
        Run in automated test mode::

            test_run()

        Run in main mode with plotting::

            test_run(main=True)

    Raises:
        AssertionError: If indicator values do not match expected values at
            any checkpoint, or if minimum period is incorrect.
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
