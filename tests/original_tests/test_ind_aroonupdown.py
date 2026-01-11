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

"""Test module for the Aroon Up/Down indicator.

This module contains test cases for validating the AroonUpDown indicator
implementation in the backtrader framework. The Aroon indicator is a technical
analysis tool used to identify trends and measure the strength of a trend.

The test loads historical data, applies the AroonUpDown indicator, and validates
the calculated values against expected results at specific checkpoints. The test
ensures the indicator correctly identifies the time periods since the highest
high (Aroon Up) and lowest low (Aroon Down) within a given time period.

Example:
    To run the test directly:
        python test_ind_aroonupdown.py

    To run as a pytest test:
        pytest tests/original_tests/test_ind_aroonupdown.py -v
"""

import backtrader as bt
import backtrader.indicators as btind

import testcommon

# Number of data feeds to test
chkdatas = 1

# Expected indicator values at checkpoints for validation
# Format: [data_feed_1_values, data_feed_2_values, ...]
# Each data feed contains values for multiple indicator lines at checkpoint positions
chkvals = [
    ["42.857143", "35.714286", "85.714286"],  # First data feed expected values
    ["7.142857", "85.714286", "28.571429"],   # Second data feed expected values
]

# Expected minimum period for the indicator
# The Aroon indicator requires this many bars before producing valid output
chkmin = 15

# The indicator class being tested
chkind = btind.AroonUpDown


def test_run(main=False):
    """Execute the AroonUpDown indicator test.

    This function loads test data, runs the indicator through a test strategy,
    and validates the calculated values against expected results. The test is
    run with multiple configuration combinations (runonce, preload, exactbars)
    to ensure compatibility across all execution modes.

    Args:
        main (bool, optional): If True, run in main mode with plotting enabled.
            When False, runs in silent test mode. Defaults to False.

    Returns:
        None. The function runs the test and raises assertions if values
        don't match expectations.

    Raises:
        AssertionError: If the calculated indicator values don't match the
            expected values in chkvals, or if the minimum period doesn't match
            chkmin.

    Example:
        >>> test_run(main=True)  # Run with plotting for visual inspection
        >>> test_run(main=False)  # Run as automated test
    """
    # Load the specified number of data feeds from test data files
    datas = [testcommon.getdata(i) for i in range(chkdatas)]

    # Run the test with the loaded data, test strategy, and validation parameters
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
    # Run the test with main=True to enable plotting when executed directly
    test_run(main=True)
