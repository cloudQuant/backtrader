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

"""Test module for Heikin Ashi indicator.

This module contains tests for the Heikin Ashi candlestick indicator,
which creates alternative candlestick charts for trend identification.
The test validates that the indicator correctly calculates:
- ha_open: Average of previous ha_open and ha_close
- ha_high: Maximum of high, ha_open, and ha_close
- ha_low: Minimum of low, ha_open, and ha_close
- ha_close: Average of open, high, low, and close

Expected values are checked at multiple checkpoints to ensure the indicator
produces correct results across different execution modes (runonce, preload,
exactbars).
"""

import backtrader as bt

import testcommon


# Number of data feeds to use in the test
chkdatas = 1

# Expected Heikin Ashi values at checkpoints
# Each list contains values for [ha_close, ha_low, ha_open] at different checkpoints
chkvals = [
    ["4119.466107", "3591.732500", "3578.625259"],
    ["4142.010000", "3638.420000", "3662.920000"],
    ["4119.466107", "3591.732500", "3578.625259"],
    ["4128.002500", "3614.670000", "3653.455000"],
]

# Expected minimum period for the indicator
chkmin = 2

# Indicator class to test
chkind = bt.ind.HeikinAshi


def test_run(main=False):
    """Run the Heikin Ashi indicator test.

    This function executes the test for the Heikin Ashi indicator by loading
    test data feeds and running the test strategy with various execution modes.
    Currently disabled (if False condition) but can be enabled for debugging.

    Args:
        main (bool): If True, run in standalone mode with plotting enabled.
            Defaults to False.

    Returns:
        None

    Raises:
        AssertionError: If indicator values do not match expected values at
            checkpoints.
    """
    if False:
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
