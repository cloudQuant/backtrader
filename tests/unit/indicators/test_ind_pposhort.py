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

"""Test module for the PPOShort (Percentage Price Oscillator Short) indicator.

This module contains tests for the PPOShort indicator, which is a momentum
oscillator that measures the difference between two moving averages as a
percentage of the longer moving average. The PPOShort variant typically uses
shorter period parameters for faster signal generation.

The test validates that the PPOShort indicator produces expected values
when applied to test data, ensuring correct calculation of the oscillator
lines including the PPO line, signal line, and histogram.
"""

import backtrader as bt

import testcommon

import backtrader.indicators as btind

# Number of data feeds to test with
chkdatas = 1

# Expected values for the PPOShort indicator outputs
# Each sublist contains expected values for different data points
chkvals = [
    ["0.629452", "0.875813", "0.049405"],
    ["0.537193", "0.718852", "-0.080645"],
    ["0.092259", "0.156962", "0.130050"],
]

# Minimum period required for the indicator to produce valid output
chkmin = 34

# The indicator class being tested
chkind = btind.PPOShort


def test_run(main=False):
    """Execute the PPOShort indicator test.

    This function loads test data, runs the indicator test using the common
    test framework, and optionally plots the results. The test validates
    that the PPOShort indicator produces the expected output values.

    Args:
        main (bool, optional): If True, enables plot output for visual
            inspection. When running as a script, this is set to True.
            Defaults to False.

    Returns:
        None

    Raises:
        AssertionError: If the indicator output values do not match the
            expected values in chkvals.
        Exception: If there are errors during data loading or test execution.
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
