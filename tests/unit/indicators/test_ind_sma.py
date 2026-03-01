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

"""Test module for Simple Moving Average (SMA) indicator.

This module contains tests to validate the SMA indicator implementation in
backtrader. It tests the indicator calculation by comparing computed values
against known expected values at specific checkpoints in the data.

The test uses 2006 daily stock data and validates that a 30-period SMA
produces the expected values at specific time points.
"""
import backtrader as bt

import testcommon

import backtrader.indicators as btind

# Number of data feeds to use in the test
chkdatas = 1

# Expected SMA values at specific checkpoints
# These values are the expected 30-period SMA values at three checkpoints
chkvals = [
    ["4063.463000", "3644.444667", "3554.693333"],
]

# Minimum period for the SMA indicator (30-period moving average)
chkmin = 30

# The indicator class to test
chkind = btind.SMA


def test_run(main=False):
    """Run the SMA indicator test.

    Loads test data, creates a strategy with the SMA indicator, and runs
    the backtest to validate the indicator calculations against expected values.

    Args:
        main (bool, optional): If True, run in standalone mode with plotting.
            Defaults to False.

    Returns:
        None. The test raises an assertion error if values don't match.

    Raises:
        AssertionError: If the calculated SMA values do not match expected values.
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
