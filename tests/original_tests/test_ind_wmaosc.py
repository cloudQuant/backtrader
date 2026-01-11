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

"""Test module for the WMAOsc (Weighted Moving Average Oscillator) indicator.

This module tests the WMAOsc indicator, which calculates the difference between
two weighted moving averages with different periods. The test validates that
the indicator produces expected values at specific checkpoints in the data.

The test configuration uses:
- Data source: 2006-day-001.txt (single data feed)
- Indicator: WMAOsc (Weighted Moving Average Oscillator)
- Minimum period: 30 bars
- Expected values: [43.727634, 40.436366, -19.148000] at checkpoints

Example:
    To run the test with plotting:
        python test_ind_wmaosc.py

    To run as a pytest:
        pytest tests/original_tests/test_ind_wmaosc.py -v
"""

import backtrader as bt

import testcommon

import backtrader.indicators as btind

# Number of data feeds to use for the test
chkdatas = 1

# Expected indicator values at checkpoints (beginning, middle, end of data)
chkvals = [["43.727634", "40.436366", "-19.148000"]]

# Expected minimum period before indicator produces valid values
chkmin = 30

# Indicator class to test
chkind = btind.WMAOsc


def test_run(main=False):
    """Execute the WMAOsc indicator test.

    Loads test data, runs the indicator through all test configurations
    (different combinations of runonce, preload, and exactbars settings),
    and validates the output against expected values.

    Args:
        main (bool, optional): If True, enables plotting and verbose output.
            Used when running the test directly as a script. Defaults to False.

    Returns:
        None. The function executes the test through testcommon.runtest()
        which returns a list of Cerebro instances, but this function does
        not propagate the return value.

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
