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

"""Test module for KAMA Envelope indicator.

This module contains test cases for the Kaufman's Adaptive Moving Average (KAMA)
Envelope indicator in the backtrader framework. The KAMA Envelope is a volatility-based
indicator that plots upper and lower bands around a KAMA line, helping traders identify
potential overbought and oversold conditions.

The test validates the indicator's calculation accuracy by comparing computed values
against expected results stored in chkvals. The test framework loads historical price
data, applies the KAMA Envelope indicator, and verifies the output matches expected
values at specific data points.

Example:
    To run the test with plotting enabled::

        python test_ind_kamaenvelope.py

    To run the test without plotting (for automated testing)::

        pytest test_ind_kamaenvelope.py
"""

import backtrader as bt

import testcommon

import backtrader.indicators as btind

# Number of data feeds to load for testing
chkdatas = 1

# Expected values for KAMA Envelope indicator validation
# Each inner list contains the expected values for [top, mid, bottom] lines
chkvals = [
    ["4063.463000", "3644.444667", "3554.693333"],
    ["4165.049575", "3735.555783", "3643.560667"],
    ["3961.876425", "3553.333550", "3465.826000"],
]

# Minimum period required for the indicator to produce valid values
chkmin = 30

# The indicator class being tested
chkind = btind.SMAEnvelope


def test_run(main=False):
    """Run the KAMA Envelope indicator test.

    This function loads test data, executes the indicator calculation using the
    TestStrategy, and validates the results against expected values. The test
    can be run in standalone mode with plotting or as part of an automated
    test suite.

    Args:
        main (bool, optional): Flag indicating whether to run in standalone mode.
            When True, enables plotting of results. Defaults to False.

    Returns:
        None: The function runs the test but does not return a value. Results are
            validated internally by the runtest function.

    Raises:
        AssertionError: If the calculated indicator values do not match the
            expected values in chkvals.

    Example:
        Run as a standalone script with plotting::

            test_run(main=True)

        Run as part of automated testing::

            test_run(main=False)
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
