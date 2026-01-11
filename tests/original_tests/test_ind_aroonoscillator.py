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
"""Test module for Aroon Oscillator indicator.

This module contains test cases for the Aroon Oscillator technical indicator.
The Aroon Oscillator is a trend-following indicator that measures the strength
of a trend and identifies potential trend changes. It is calculated as the
difference between the Aroon Up and Aroon Down indicators.

The test validates:
  * Indicator calculation accuracy at specific checkpoints
  * Minimum period requirements (15 bars)
  * Compatibility with different execution modes (runonce/preload combinations)

Expected Values:
  * Checkpoint 0: aroonosc = 35.714286
  * Checkpoint 1: aroonosc = -50.000000
  * Checkpoint 2: aroonosc = 57.142857
"""

import backtrader as bt

import testcommon

import backtrader.indicators as btind

# Test configuration constants
chkdatas = 1  # Number of data feeds to use for testing
chkvals = [["35.714286", "-50.000000", "57.142857"]]  # Expected values at checkpoints

chkmin = 15  # Expected minimum period before indicator produces valid values
chkind = btind.AroonOscillator  # Indicator class being tested


def test_run(main=False):
    """Execute the Aroon Oscillator indicator test.

    This function loads test data, creates a backtesting engine with the
    TestStrategy, and runs the test with the Aroon Oscillator indicator.
    The test validates that the indicator produces expected values at
    specific checkpoint locations.

    Args:
        main (bool, optional): If True, enable plotting mode for visual
            inspection. Defaults to False, which runs the test without
            generating plots.

    Returns:
        None: The function runs the test and implicitly passes if no
            assertions fail.

    Raises:
        AssertionError: If indicator values do not match expected values
            at checkpoint locations.
    """
    # Load test data feeds
    datas = [testcommon.getdata(i) for i in range(chkdatas)]

    # Run the test with the configured parameters
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
    # Run the test in main mode with plotting enabled when executed directly
    test_run(main=True)
