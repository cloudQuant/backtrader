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
"""Test module for Exponential Moving Average (EMA) indicator.

This module contains tests for the EMA indicator implementation in backtrader.
It validates that the EMA calculations produce expected results at specific
checkpoints when tested against historical data.

The test uses 2006 daily price data and verifies EMA values at multiple
time points to ensure the indicator's smoothing calculations are correct.
"""

import backtrader as bt

import testcommon

import backtrader.indicators as btind

chkdatas = 1
chkvals = [
    ["4070.115719", "3644.444667", "3581.728712"],
]

chkmin = 30
chkind = btind.EMA


def test_run(main=False):
    """Run the EMA indicator test.

    This function loads test data, executes a backtest with the EMA indicator,
    and validates the calculated values against expected results.

    The test is run with multiple configuration combinations (runonce, preload,
    exactbars) to ensure the EMA indicator works correctly across all execution
    modes.

    Args:
        main (bool, optional): If True, enables plotting and detailed output.
            Defaults to False.

    Returns:
        list: A list of Cerebro instances, one for each configuration tested.

    Raises:
        AssertionError: If the calculated EMA values do not match expected values.
        IOError: If test data files cannot be loaded.
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
