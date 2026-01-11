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

"""Test module for the Relative Strength Index (RSI) indicator.

This module contains test cases for validating the RSI indicator implementation
in backtrader. The RSI is a momentum oscillator that measures the speed and
change of price movements, providing values between 0 and 100.

The test loads historical price data, calculates RSI values, and validates them
against expected results at specific checkpoints in the data series.

Test Configuration:
    - Data source: 2006-day-001.txt (daily OHLCV data)
    - Indicator: RSI (default period of 14 bars)
    - Minimum period: 15 bars (indicator warmup period)
    - Expected values: Validated at multiple checkpoints

Example:
    To run the test directly:
        python test_ind_rsi.py

    To run the test via pytest:
        pytest tests/original_tests/test_ind_rsi.py -v
"""

import backtrader as bt

import testcommon

import backtrader.indicators as btind

# Number of data feeds to use in the test
chkdatas = 1

# Expected RSI values at checkpoints
# Format: List of lists, where each inner list contains expected values
# for each line of the indicator at different checkpoint indices
chkvals = [
    ["57.644284", "41.630968", "53.352553"],
]

# Minimum period required for the indicator to produce valid values
# RSI with period 14 needs 15 bars (14 for calculation + 1 for output)
chkmin = 15

# The indicator class to test
chkind = btind.RSI


def test_run(main=False):
    """Execute the RSI indicator test with the configured parameters.

    This function loads test data, creates a test strategy with the RSI
    indicator, and runs the backtest to validate indicator calculations against
    expected values.

    The test runs the strategy through multiple execution modes (runonce/preload
    combinations) unless main=True, which runs a single pass with optional plotting.

    Args:
        main (bool, optional): If True, runs a single test pass with plotting
            enabled for visual inspection. If False, runs the full test matrix
            with multiple execution modes. Defaults to False.

    Returns:
        list: A list of Cerebro instances from each test run. The length of the
            list depends on the test configuration (single run for main=True,
            multiple runs for main=False).

    Example:
        >>> # Run full test matrix (typical usage)
        >>> cerebros = test_run(main=False)

        >>> # Run single test with plot for manual verification
        >>> cerebros = test_run(main=True)
    """
    # Load the specified number of data feeds from test data files
    datas = [testcommon.getdata(i) for i in range(chkdatas)]

    # Run the test with the configured parameters
    # testcommon.runtest will iterate through different execution modes
    # (runonce/preload/exactbars combinations) unless main=True
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
    # Run the test with main=True when executed directly as a script
    # This enables plotting and runs a single test pass
    test_run(main=True)
