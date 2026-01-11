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

"""Test module for TEMA (Triple Exponential Moving Average) indicator.

This module contains test cases for the TEMA indicator implementation in
backtrader. TEMA is a trend-following indicator that combines single,
double, and triple exponential moving averages to reduce lag and improve
signal responsiveness.

The test verifies that the TEMA indicator calculates values correctly
against known expected results using test data fixtures.

Example:
    To run this test directly::

        python tests/original_tests/test_ind_tema.py

    To run via pytest::

        pytest tests/original_tests/test_ind_tema.py -v
"""

import backtrader as bt

import testcommon

import backtrader.indicators as btind

# Number of data feeds to use in the test
chkdatas = 1

# Expected TEMA indicator values for validation
# These are the calculated values at specific bars to verify correctness
chkvals = [["4113.721705", "3862.386854", "3832.691054"]]

# Minimum period required for TEMA calculation before valid values are produced
chkmin = 88

# The TEMA indicator class being tested
chkind = btind.TEMA


def test_run(main=False):
    """Run the TEMA indicator test.

    This function executes the TEMA indicator test by loading test data,
    running the strategy with the indicator, and validating the calculated
    values against expected results.

    Args:
        main (bool): If True, enables plotting and runs as a standalone
            execution. If False, runs in test mode without plotting.
            Defaults to False.

    Returns:
        None

    Raises:
        AssertionError: If the calculated TEMA values do not match the
            expected values in chkvals.

    Example:
        Run test without plotting (for automated testing)::

            test_run(main=False)

        Run test with plotting (for manual verification)::

            test_run(main=True)
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
