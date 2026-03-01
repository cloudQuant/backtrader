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

"""Test module for the TRIX indicator.

This module contains test cases for the TRIX (Triple Exponential Moving Average)
indicator implementation in backtrader. The TRIX indicator is a momentum
indicator that displays the percent rate-of-change of a triple exponentially
smoothed moving average, designed to filter out insignificant price movements
that are insignificant to the larger trend.

The test validates that the TRIX indicator produces expected values when
applied to test data, ensuring the calculation logic is correct.
"""

import backtrader as bt

import testcommon

import backtrader.indicators as btind

# Number of data feeds to use in the test
chkdatas = 1
# Expected TRIX indicator values at specific data points
# These values are used to validate the indicator's calculation accuracy
chkvals = [["0.071304", "0.181480", "0.050954"]]

# Minimum period required before the TRIX indicator produces valid values
# TRIX requires sufficient data points to calculate the triple exponential smoothing
chkmin = 44
# The TRIX indicator class being tested
chkind = btind.Trix


def test_run(main=False):
    """Execute the TRIX indicator test.

    This function loads test data feeds and runs the TRIX indicator test
    using the common test infrastructure. The test validates that the
    indicator produces the expected values at specific data points.

    Args:
        main (bool): If True, enables plot generation for visual inspection.
            When False, runs the test without generating plots. Default is False.

    Returns:
        None

    Raises:
        AssertionError: If the TRIX indicator values do not match the
            expected values in chkvals.

    Example:
        >>> test_run(main=False)  # Run test without plotting
        >>> test_run(main=True)   # Run test and generate plot
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
