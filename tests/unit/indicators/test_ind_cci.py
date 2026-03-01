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

"""Test module for Commodity Channel Index (CCI) indicator.

This module contains tests for the CCI (Commodity Channel Index) indicator
implementation in backtrader. The CCI is a momentum-based oscillator used
to help determine when an asset is reaching overbought or oversold conditions.

The test validates that the CCI indicator calculates expected values at
specific checkpoints in the data stream, ensuring correctness across
different execution modes (runonce/preload combinations).

Module Constants:
    chkdatas (int): Number of data feeds to use for testing (1).
    chkvals (list): Expected CCI values at test checkpoints. Each sublist
        contains string representations of expected values at different
        checkpoint positions in the data stream.
    chkmin (int): Expected minimum period for the CCI indicator (39 bars).
        This is the warmup period required before the CCI produces valid output.
    chkind (type): The CCI indicator class from backtrader.indicators.

Example:
    Run the test directly to execute with plotting enabled:
        python test_ind_cci.py

    Run as a module for automated testing:
        pytest test_ind_cci.py -v
"""

import backtrader as bt

import testcommon

import backtrader.indicators as btind

chkdatas = 1
chkvals = [
    ["69.574287", "91.196363", "82.175663"],
]

chkmin = 39
chkind = btind.CCI


def test_run(main=False):
    """Execute the CCI indicator test.

    This function runs a backtest using the CCI indicator and validates
    the calculated values against expected results at specific checkpoints.
    The test is run across multiple configuration combinations (runonce,
    preload, exactbars) to ensure compatibility.

    Args:
        main (bool, optional): If True, enables plotting mode for visual
            inspection. Defaults to False.

    Returns:
        list: A list of Cerebro instances, one for each configuration
            combination tested (runonce/preload/exactbars variations).

    Raises:
        AssertionError: If the calculated CCI values do not match the
            expected values at the checkpoint positions.
        Exception: Any exceptions raised during Cerebro execution or
            indicator calculation.

    Note:
        The test loads data from testcommon's data files, runs the CCI
        indicator, and validates values at three checkpoint positions:
        - Position 0 (most recent bar)
        - Position -len(ind) + minperiod (oldest valid bar)
        - Midpoint between oldest and most recent bars
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
