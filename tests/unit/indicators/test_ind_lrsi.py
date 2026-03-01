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

"""Test module for the Linear Regression Relative Strength Index (LRSI) indicator.

This module contains test cases for the LRSI (Linear Regression RSI) indicator
in the backtrader framework. The LRSI indicator combines linear regression
concepts with the traditional RSI calculation to provide a smoothed momentum
oscillator.

The test validates:
* Indicator initialization with default parameters
* Calculation accuracy at specific data checkpoints
* Minimum period requirements for valid calculations
* Compatibility across different execution modes (runonce, preload, exactbars)

Test Data:
    The test uses 2006 daily OHLCV data from the backtrader test dataset.
    Expected values are validated at three checkpoint indices:
    * First data point
    * Last data point
    * Middle data point

Expected Values:
    At checkpoints (formatted to 6 decimal places):
    * lrsi: [0.748915, 0.714286, 1.000000]

Example:
    To run this test directly::

        python test_ind_lrsi.py

    To run via pytest::

        pytest tests/original_tests/test_ind_lrsi.py -v
"""

import backtrader as bt

import testcommon

import backtrader.indicators as btind

# Number of data feeds to use in the test
chkdatas = 1

# Expected LRSI values at three checkpoint indices [first, last, middle]
# These values are used to validate indicator calculation accuracy
chkvals = [
    ["0.748915", "0.714286", "1.000000"],
]

# Minimum period required before LRSI produces valid values
chkmin = 6

# The indicator class being tested
chkind = btind.LRSI


def test_run(main=False):
    """Execute the LRSI indicator test.

    This function loads test data, runs the indicator through multiple
    execution configurations, and validates the calculated values against
    expected results.

    The test runs through different combinations of:
    * runonce mode (True/False)
    * preload mode (True/False)
    * exactbars settings (-2, -1, False)

    Args:
        main (bool, optional): If True, enables plotting and detailed output
            for manual inspection. When run as a script (__main__), this is
            set to True. Defaults to False.

    Returns:
        list: A list of Cerebro instances, one for each test configuration
            executed. Each Cerebro instance contains the test strategy with
            the LRSI indicator.

    Raises:
        AssertionError: If any of the calculated LRSI values at the
            checkpoint indices do not match the expected values in chkvals.

    Example:
        >>> cerebros = test_run(main=False)
        >>> print(f"Tested {len(cerebros)} configurations")
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
