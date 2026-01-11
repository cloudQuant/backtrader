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

"""Test module for the SMMA Oscillator indicator.

This module contains test cases for the SMMA (Smoothed Moving Average)
Oscillator indicator (SMMAOsc) in the backtrader framework. The test verifies
that the indicator produces expected values for given input data.

The test uses the standard test infrastructure from testcommon to load data,
run the strategy, and compare the indicator output against expected values.
"""

import backtrader as bt

import testcommon

import backtrader.indicators as btind

# Number of data feeds to use in the test
chkdatas = 1

# Expected values for the SMMA Oscillator indicator at specific points
# Format: list of lists containing string representations of expected values
chkvals = [["98.370275", "51.185333", "-59.347648"]]

# Minimum period required for the indicator to produce valid output
chkmin = 30

# The indicator class being tested
chkind = btind.SMMAOsc


def test_run(main=False):
    """Execute the SMMA Oscillator indicator test.

    This function loads test data, creates a test strategy, and runs the
    backtest to verify that the SMMA Oscillator indicator produces the
    expected output values.

    Args:
        main (bool, optional): Whether to enable plotting and run as the main
            test. Defaults to False. When True, the test will display plots
            and is typically used when running the module directly.

    Returns:
        None

    Raises:
        AssertionError: If the indicator output values do not match the
            expected values in chkvals.

    Example:
        >>> # Run test without plotting (typical for pytest)
        >>> test_run()
        >>> # Run test with plotting (when run as script)
        >>> test_run(main=True)
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
