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

"""Test module for the Lowest indicator.

This module tests the backtrader Lowest indicator, which calculates the
lowest value over a specified period. The test validates that the indicator
correctly identifies minimum values in a rolling window and produces expected
results at various checkpoints.

The test uses historical stock data from 2006 and validates the indicator
calculations against known expected values. It runs the indicator with a
14-period window and checks the output at multiple data points.

Example:
    Run the test from the command line to execute with plotting:
        python test_ind_lowest.py

    Or import and run programmatically:
        from tests.original_tests.test_ind_lowest import test_run
        test_run(main=False)
"""

import backtrader as bt

import testcommon

import backtrader.indicators as btind

# Number of data feeds to use in the test
chkdatas = 1

# Expected values at checkpoints for the Lowest indicator
# These are string-formatted float values representing the lowest price
# over a 14-period window at specific points in the data
chkvals = [
    ["4019.890000", "3570.170000", "3506.070000"],
]

# Minimum period required for the indicator to produce valid output
chkmin = 14

# The indicator class being tested
chkind = btind.Lowest

# Arguments to pass to the indicator constructor
chkargs = dict(period=14)


def test_run(main=False):
    """Run the Lowest indicator test.

    This function loads test data and executes the indicator test with the
    specified parameters. It runs the test through multiple configurations
    of runonce, preload, and exactbars settings to ensure compatibility
    across all execution modes.

    Args:
        main (bool, optional): If True, enable plotting and detailed output.
            Used when running the test directly from the command line.
            Defaults to False.

    Returns:
        list: A list of Cerebro instances, one for each configuration tested.

    Example:
        >>> test_run(main=False)
        [<backtrader.cerebro.Cerebro object at 0x...>]
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
        chkargs=chkargs,
    )


if __name__ == "__main__":
    test_run(main=True)
