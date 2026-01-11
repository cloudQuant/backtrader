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

"""Test module for KAMA (Kaufman's Adaptive Moving Average) indicator.

This module tests the KAMA indicator implementation in backtrader. KAMA is an
adaptive moving average developed by Perry Kaufman that adjusts its smoothing
factor based on market volatility and direction.

The test validates that:
1. The indicator produces expected values at specific checkpoints
2. The minimum period is correctly calculated (31 bars for default parameters)
3. The indicator works correctly across different execution modes

The test uses a single data feed with 2006 daily data and validates the
indicator output against known correct values.

Module Constants:
    chkdatas (int): Number of data feeds to use in the test (1).
    chkvals (list): Expected indicator values at checkpoint bars for validation.
    chkmin (int): Expected minimum period before indicator produces valid values (31).
    chkind (type): The KAMA indicator class to test.
"""

import backtrader as bt

import testcommon

import backtrader.indicators as btind

chkdatas = 1
chkvals = [
    ["4054.187922", "3648.549000", "3592.979190"],
]

chkmin = 31
chkind = btind.KAMA


def test_run(main=False):
    """Run the KAMA indicator test.

    This function loads the test data, creates a backtest with the TestStrategy
    (which applies the KAMA indicator), and validates the results against
    expected values. The test can be run in two modes:

    1. Test mode (main=False): Runs assertions to validate correctness
    2. Main mode (main=True): Displays plots for manual inspection

    Args:
        main (bool, optional): If True, run with plotting enabled for visual
            inspection. If False, run automated tests without plotting.
            Defaults to False.

    Returns:
        None

    Raises:
        AssertionError: If indicator values do not match expected values at
            checkpoint bars (only when main=False).
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
