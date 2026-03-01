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

"""Test module for the Oscillator indicator.

This module contains tests for the backtrader Oscillator indicator, which
calculates the difference between two data series (typically price and a
moving average) to show momentum and overbought/oversold conditions.

The test validates that the Oscillator indicator produces expected values
when applied to historical price data, using a Simple Moving Average (SMA)
as the comparison baseline.

Test Configuration:
    - Data feeds: 1 (2006-day-001.txt)
    - Indicator: Oscillator
    - Minimum period: 30
    - Expected values: ["56.477000", "51.185333", "2.386667"]

Example:
    To run this test directly:
        python test_ind_oscillator.py

    To run as part of the test suite:
        pytest tests/original_tests/test_ind_oscillator.py -v
"""

import backtrader as bt

import testcommon

import backtrader.indicators as btind

chkdatas = 1
chkvals = [["56.477000", "51.185333", "2.386667"]]

chkmin = 30
chkind = btind.Oscillator


class TS2(testcommon.TestStrategy):
    """Test strategy for Oscillator indicator validation.

    This strategy sets up a Simple Moving Average (SMA) indicator to be used
    by the Oscillator indicator during testing. The SMA provides the baseline
    for calculating the oscillator values.

    Attributes:
        p (Params): Parameter object inherited from TestStrategy.
            inddata (list): Will be populated with the SMA indicator instance.
    """

    def __init__(self):
        """Initialize the test strategy and set up the SMA indicator.

        Creates an SMA indicator on the data feed and assigns it to the
        strategy's indicator data list for validation during testing.
        """
        ind = btind.MovAv.SMA(self.data)
        self.p.inddata = [ind]
        super().__init__()


def test_run(main=False):
    """Run the Oscillator indicator test.

    Executes the test by loading historical data, applying the test strategy
    with the Oscillator indicator, and validating the results against expected
    values.

    Args:
        main (bool, optional): If True, enables plotting mode for visual
            inspection. Defaults to False.

    Returns:
        None: The function executes the test and prints/raises results
            based on the validation outcome.

    Raises:
        AssertionError: If the calculated oscillator values do not match
            the expected values in chkvals.

    Example:
        >>> test_run(main=False)  # Run without plotting
        >>> test_run(main=True)   # Run with plotting enabled
    """
    datas = [testcommon.getdata(i) for i in range(chkdatas)]
    testcommon.runtest(
        datas, TS2, main=main, plot=main, chkind=chkind, chkmin=chkmin, chkvals=chkvals
    )


if __name__ == "__main__":
    test_run(main=True)
