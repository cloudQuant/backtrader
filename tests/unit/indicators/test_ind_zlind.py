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
"""Test module for ZeroLagIndicator (ZLIND).

This module contains test cases for the ZeroLagIndicator, which is a technical
indicator designed to reduce lag in signal detection. The test validates that
the indicator produces expected values when applied to test data.

The test framework uses common testing utilities from testcommon to:
1. Load test data from CSV files
2. Execute the indicator with various Cerebro configurations
3. Verify computed values match expected results at specific checkpoints

Test Configuration:
    - Data Source: 2006-day-001.txt (daily OHLCV data)
    - Indicator: ZeroLagIndicator
    - Minimum Period: 30 bars
    - Checkpoint Values: Pre-computed expected values for validation
"""

import backtrader as bt

import testcommon

import backtrader.indicators as btind

# Number of data feeds to test (1 for single data source test)
chkdatas = 1

# Expected values at checkpoints for validation
# Format: List of lists, each containing string representations of expected values
chkvals = [["4110.282052", "3644.444667", "3564.906194"]]

# Minimum period required by the indicator before producing valid output
chkmin = 30

# The indicator class being tested
chkind = btind.ZeroLagIndicator


def test_run(main=False):
    """Execute the ZeroLagIndicator test with standard configuration.

    This function loads test data, runs the indicator test using the common
    test framework, and validates results against expected values. The test
    can be run in two modes:

    1. Automated mode (main=False): For automated testing without visualization
    2. Interactive mode (main=True): For manual inspection with plotting enabled

    The test framework will execute multiple configurations combining different
    values for runonce, preload, and exactbars parameters to ensure the
    indicator works correctly across all execution modes.

    Args:
        main (bool, optional): If True, enable plot output for visual inspection.
            Defaults to False, which runs the test without visualization for
            automated testing scenarios.

    Returns:
        list: A list of Cerebro instances, one for each configuration tested.
            Each Cerebro contains the executed backtest with the ZeroLagIndicator
            applied to the test data.

    Example:
        >>> # Run automated test
        >>> cerebros = test_run(main=False)
        >>>
        >>> # Run test with plotting for manual inspection
        >>> cerebros = test_run(main=True)
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
