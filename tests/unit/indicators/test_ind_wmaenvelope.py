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

"""Test module for WMAEnvelope indicator.

This module contains tests for the Weighted Moving Average Envelope (WMAEnvelope)
indicator in the backtrader framework. The WMAEnvelope consists of an upper
and lower band that are placed around a weighted moving average, typically
at a percentage distance from the central WMA line.

The test validates that the WMAEnvelope indicator calculates expected values
based on historical price data and verifies the indicator's behavior across
different data feeds.
"""

import backtrader as bt

import testcommon

import backtrader.indicators as btind

# Number of data feeds to test
chkdatas = 1

# Expected values for the WMAEnvelope indicator output
# Each inner list contains [upper_band, lower_band, wma] values
chkvals = [
    ["4076.212366", "3655.193634", "3576.228000"],
    ["4178.117675", "3746.573475", "3665.633700"],
    ["3974.307056", "3563.813794", "3486.822300"],
]

# Minimum period required for the indicator calculation
chkmin = 30

# The indicator class being tested
chkind = btind.WMAEnvelope


def test_run(main=False):
    """Run the WMAEnvelope indicator test.

    This function executes a test of the WMAEnvelope indicator by loading test
    data, running a backtesting strategy, and comparing the calculated indicator
    values against expected results.

    Args:
        main (bool, optional): If True, enables plotting and main execution mode.
            Defaults to False, which runs in test mode without visualization.

    Returns:
        None

    Raises:
        AssertionError: If the calculated indicator values do not match the
            expected values in chkvals.
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
