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

"""Test module for the True Strength Index (TSI) indicator.

This module contains test cases for the TSI (True Strength Index) technical
indicator implementation in backtrader. The TSI is a momentum oscillator
that helps identify trend direction and overbought/versus oversold conditions.

The test validates that the TSI indicator produces expected values when
applied to test data, using a minimum period of 38 bars before the indicator
produces valid results.

Typical usage example:
    test_run(main=True)  # Runs the test with plotting enabled
"""

import backtrader as bt

import testcommon

# Number of data feeds to use in the test
chkdatas = 1

# Expected TSI values at specific data points for validation
# Format: [tsi_value, tsi_signal_value, tsi_value_2]
chkvals = [["16.012364", "22.866307", "4.990750"]]

# Minimum number of bars required before TSI produces valid output
chkmin = 38

# The TSI indicator class being tested
chkind = bt.ind.TSI


def test_run(main=False):
    """Run the TSI indicator test.

    This function loads test data, executes the TSI indicator test, and
    validates that the indicator produces expected values. The test can be
    run in main mode with plotting enabled for visual inspection.

    Args:
        main (bool): If True, enables plot generation for visual inspection
            of the indicator behavior. Defaults to False.

    Returns:
        None: The function runs the test but does not return a value.

    Raises:
        AssertionError: If the TSI indicator values do not match the
            expected values in chkvals.

    Example:
        >>> test_run(main=False)  # Run test without plotting
        >>> test_run(main=True)   # Run test with plotting enabled
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
