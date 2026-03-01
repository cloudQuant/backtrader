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

"""Test module for the Stochastic oscillator indicator.

This module contains tests for the Stochastic technical indicator, which is a
momentum indicator that shows the location of the close relative to the
high-low range over a set period of time. The Stochastic oscillator is
commonly used to identify overbought and oversold conditions.

The test validates that the Stochastic indicator produces expected values
at specific checkpoint bars when run with default parameters.

Module-level constants:
    chkdatas: Number of data feeds to use in the test.
    chkvals: Expected values for the Stochastic lines (percK, percD, percSlowK)
        at specific checkpoints. Each row contains values for one checkpoint.
    chkmin: Expected minimum period before the indicator produces valid values.
    chkind: The Stochastic indicator class being tested.
"""

import backtrader as bt

import testcommon

import backtrader.indicators as btind

chkdatas = 1
chkvals = [
    ["88.667626", "21.409626", "63.796187"],
    ["82.845850", "15.710059", "77.642219"],
]

chkmin = 18
chkind = btind.Stochastic


def test_run(main=False):
    """Run the Stochastic indicator test.

    This function executes the Stochastic indicator test by loading test data,
    running the backtest with a TestStrategy that creates the indicator,
    and validating that the computed values match the expected values at
    checkpoint bars.

    Args:
        main (bool, optional): If True, enable plotting mode for visual
            inspection. Defaults to False.

    Returns:
        None. The function runs the test and raises exceptions if validation
            fails.

    Raises:
        AssertionError: If the computed indicator values do not match the
            expected values at the checkpoint bars.
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
