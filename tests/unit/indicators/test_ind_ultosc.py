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

"""Test module for UltimateOscillator indicator.

This module contains test cases for the UltimateOscillator technical indicator
in the backtrader framework. The Ultimate Oscillator is a momentum indicator
that uses three different time periods to reduce volatility and false trade
signals compared to single-period oscillators.

The test validates that the indicator calculates expected values at specific
checkpoints and respects the minimum period requirement.
"""

import backtrader as bt

import testcommon


# Number of data feeds to use in the test
chkdatas = 1

# Expected values at specific checkpoints for validation
# These values represent the UltimateOscillator output at three different
# points in the data series: [beginning, middle, end]
chkvals = [["51.991177", "62.334055", "46.707445"]]

# Expected minimum period before indicator produces valid values
# 28 from longest SumN/Sum calculation + 1 extra from truelow/truerange
chkmin = 29

# The indicator class being tested
chkind = bt.indicators.UltimateOscillator


def test_run(main=False):
    """Run the UltimateOscillator indicator test.

    This function loads test data, executes a backtest using the TestStrategy
    with the UltimateOscillator indicator, and validates the results against
    expected values. The test can be run in automated mode (for pytest) or
    manual mode (for visualization and debugging).

    Args:
        main (bool, optional): If True, run in manual mode with plotting.
            Defaults to False for automated testing. When True, the test
            will display detailed output and plot the results.

    Returns:
        None. The function executes the test and raises assertions if
        validation fails.

    Raises:
        AssertionError: If the calculated indicator values do not match
            the expected values at the checkpoint locations.

    Example:
        >>> # Run automated test
        >>> test_run()

        >>> # Run manual test with plotting
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
