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

"""Test module for the Fractal indicator.

This module contains tests for the Fractal indicator, which identifies local
extrema in price data by comparing high and low prices with neighboring bars.
The Fractal indicator is used to identify potential reversal points in market
data.

The test validates that:
1. The indicator requires a minimum period of 5 bars to start calculating
2. Initial values are NaN (not available) until the minimum period is reached
3. Once sufficient data is available, fractal values are calculated correctly

Test Data:
    Uses 2006 daily OHLCV data to validate fractal calculations.

Expected Results:
    - First 3 bars: All fractal values are NaN
    - Bar 4 onwards: Fractal values begin to be calculated
    - Example expected value at checkpoint: 3553.692850
"""

import backtrader as bt

import testcommon

# Number of data feeds to use in the test
chkdatas = 1

# Expected fractal values at test checkpoints
# First checkpoint: All NaN (minimum period not yet reached)
# Second checkpoint: Contains calculated fractal value
chkvals = [["nan", "nan", "nan"], ["nan", "nan", "3553.692850"]]

# Expected minimum period for the Fractal indicator
# Fractals require 2 bars on each side to identify a local extremum
chkmin = 5

# Import the Fractal indicator class to be tested
from backtrader.utils.fractal import Fractal as chkind


def test_run(main=False):
    """Run the Fractal indicator test.

    This function executes a backtest using the Fractal indicator and validates
    the calculated values against expected results. The test is run with
    multiple configuration combinations (runonce, preload, exactbars) to ensure
    compatibility across all execution modes.

    Args:
        main (bool, optional): If True, enable plot output for manual inspection.
            When run as the main script, this is set to True to visualize results.
            Defaults to False.

    Returns:
        list: List of Cerebro instances, one for each configuration tested.

    Raises:
        AssertionError: If the calculated fractal values do not match expected
            values at the checkpoints.
    """
    # Load test data for each required data feed
    datas = [testcommon.getdata(i) for i in range(chkdatas)]

    # Run the test with all configuration combinations
    # The test strategy will validate fractal calculations at checkpoints
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
    # When run directly, execute the test with plotting enabled
    test_run(main=True)
