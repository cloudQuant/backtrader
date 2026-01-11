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

"""Test module for the Awesome Oscillator (AO) indicator.

This module contains test cases for the Backtrader Awesome Oscillator indicator,
which is a momentum indicator that measures the difference between a 34-period
and a 5-period simple moving average of the median price (high + low) / 2.

The test validates that the AO indicator produces expected values when applied
to historical price data, ensuring the implementation matches the reference
calculation.

Module Variables:
    chkdatas (int): Number of data feeds to load for testing (default: 1).
    chkvals (list): List of expected indicator values at specific bars for
        validation. Contains three string representations of float values:
        ["50.804206", "72.983735", "33.655941"].
    chkmin (int): Minimum period required before the indicator produces valid
        values (default: 34).
    chkind (type): The indicator class being tested (bt.ind.AO - Awesome
        Oscillator).
"""

import backtrader as bt

import testcommon


chkdatas = 1
chkvals = [["50.804206", "72.983735", "33.655941"]]

chkmin = 34
chkind = bt.ind.AO


def test_run(main=False):
    """Execute the Awesome Oscillator indicator test.

    This function loads test data, runs the indicator through the standard
    test strategy, and validates that the calculated values match the expected
    results. The test can optionally plot the results for visual inspection
    when run directly as a script.

    Args:
        main (bool, optional): Whether the test is being run as the main
            script. When True, enables plotting of the results. Defaults to
            False.

    Returns:
        None: The function executes the test and raises assertions if
            validation fails, otherwise returns silently.

    Raises:
        AssertionError: If the calculated indicator values do not match the
            expected values in chkvals, or if the minimum period does not
            match chkmin.

    Example:
        >>> test_run(main=False)  # Run test without plotting
        >>> test_run(main=True)   # Run test with plotting (typically in __main__)
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
