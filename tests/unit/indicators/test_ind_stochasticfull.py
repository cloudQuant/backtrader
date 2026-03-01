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

"""Test module for StochasticFull indicator.

This module tests the StochasticFull indicator implementation in backtrader,
validating that the indicator produces expected values for known data inputs.
The test loads historical price data and compares the computed StochasticFull
values against pre-validated expected results at specific checkpoints.

The StochasticFull indicator is a momentum oscillator that compares a specific
closing price of a security to a range of its prices over a certain period of
time. It consists of three lines:
1. %K - The fast stochastic line
2. %D - A moving average of %K
3. %Dslow - A slower moving average of %D

Test Configuration:
    - Data Source: 2006 daily OHLCV data (single data feed)
    - Indicator: StochasticFull with default parameters
    - Expected Minimum Period: 18 bars
    - Validation Checkpoints: Three points in time with expected values
"""

import backtrader as bt

import testcommon

import backtrader.indicators as btind

# Number of data feeds to use for testing
chkdatas = 1

# Expected values for StochasticFull indicator at three checkpoints
# Each inner list contains: [percK, percD, percDslow] values as strings
chkvals = [
    ["83.541267", "36.818395", "41.769503"],
    ["88.667626", "21.409626", "63.796187"],
    ["82.845850", "15.710059", "77.642219"],
]

# Expected minimum period before indicator produces valid values
chkmin = 18

# The indicator class being tested
chkind = btind.StochasticFull


def test_run(main=False):
    """Execute the StochasticFull indicator test.

    This function loads test data and runs the indicator validation test.
    It tests the indicator across multiple execution modes (runonce/preload
    combinations) to ensure compatibility and correctness.

    Args:
        main (bool, optional): If True, enables plotting for visual inspection.
            When run as main, the test will display charts. Defaults to False.

    Returns:
        None. The function runs the test and assertions are handled internally.

    Raises:
        AssertionError: If computed indicator values do not match expected values
            at any checkpoint, or if minimum period is incorrect.
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
