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

"""Test module for KAMA Oscillator indicator.

This module contains test cases for the Kaufman's Adaptive Moving Average
(KAMA) Oscillator indicator in the backtrader framework. The KAMA Oscillator
measures the difference between price and the KAMA, providing signals about
trend strength and potential reversals.

The test validates that the KAMA Oscillator calculates expected values at
specific checkpoints in historical price data, ensuring the indicator
implementation is correct and stable across different execution modes
(runonce, preload, exactbars).

Test Configuration:
    Data Sources: 1 data feed (2006-day-001.txt)
    Expected Values:
        - Checkpoint 1: 65.752078
        - Checkpoint 2: 78.911000
        - Checkpoint 3: 39.950810
    Minimum Period: 31 bars (required for KAMA calculation)
"""

import backtrader as bt

import testcommon

import backtrader.indicators as btind

# Number of data feeds to test with
chkdatas = 1

# Expected indicator values at test checkpoints
# These values are validated against the actual KAMA Oscillator output
chkvals = [["65.752078", "78.911000", "39.950810"]]

# Minimum period required for KAMA Oscillator calculation
# KAMA requires a minimum period to warm up before producing valid values
chkmin = 31

# Indicator class being tested
chkind = btind.KAMAOsc


def test_run(main=False):
    """Execute the KAMA Oscillator indicator test.

    This function runs a comprehensive test of the KAMA Oscillator indicator
    by loading test data, executing a backtest strategy with the indicator,
    and validating the calculated values against expected results.

    The test runs in multiple configurations (runonce/preload/exactbars modes)
    unless main=True, in which case it runs once with plotting enabled.

    Args:
        main (bool, optional): If True, run in standalone mode with plotting.
            Defaults to False. When True, the test runs once and displays
            results visually for manual inspection.

    Returns:
        None. The function executes the test and raises assertions if
        validation fails.

    Raises:
        AssertionError: If calculated indicator values do not match expected
            values at any checkpoint, or if minimum period is incorrect.

    Example:
        >>> test_run()  # Run full test matrix
        >>> test_run(main=True)  # Run with plotting for inspection
    """
    # Load test data feeds
    datas = [testcommon.getdata(i) for i in range(chkdatas)]

    # Execute the test with the configured parameters
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
    # Run the test in standalone mode when executed directly
    # This enables plotting and runs a single configuration
    test_run(main=True)
