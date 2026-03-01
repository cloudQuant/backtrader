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

"""Test module for SMAEnvelope indicator validation.

This module contains tests for the Simple Moving Average Envelope (SMAEnvelope)
indicator, which creates bands around a Simple Moving Average at a specified
percentage distance. The test validates that the indicator correctly calculates
the upper envelope, SMA middle line, and lower envelope values.

The test loads historical price data, applies the SMAEnvelope indicator with
default parameters, and verifies that the calculated values match expected
results at specific checkpoint indices.

Module Constants:
    chkdatas (int): Number of data feeds to test (1).
    chkvals (list): Expected indicator values at checkpoints for validation.
        Each inner list contains string representations of the upper band,
        middle SMA, and lower band values.
    chkmin (int): Expected minimum period for the indicator (30).
    chkind (type): The SMAEnvelope indicator class to test.

Typical Usage:
    Run the test directly with main=True for plotting:
        python test_ind_smaenvelope.py

    Run the test programmatically:
        test_run(main=False)
"""

import backtrader as bt

import testcommon

import backtrader.indicators as btind

chkdatas = 1
chkvals = [
    ["4063.463000", "3644.444667", "3554.693333"],
    ["4165.049575", "3735.555783", "3643.560667"],
    ["3961.876425", "3553.333550", "3465.826000"],
]

chkmin = 30
chkind = btind.SMAEnvelope


def test_run(main=False):
    """Run the SMAEnvelope indicator test.

    Loads test data, executes the backtest with the TestStrategy, and validates
    that the SMAEnvelope indicator produces expected values. The test is run
    across multiple configuration combinations (runonce, preload, exactbars)
    to ensure compatibility.

    Args:
        main (bool, optional): If True, enables plot output for visual inspection.
            When run as the main script, this is set to True. Defaults to False.

    Returns:
        list: List of Cerebro instances, one for each test configuration.

    Raises:
        AssertionError: If the calculated indicator values do not match the
            expected values at any checkpoint.

    Note:
        The function uses testcommon.runtest() which executes the strategy
        across multiple configuration combinations:
        - runonce: True/False (vectorized vs iterative calculation)
        - preload: True/False (preloading data vs streaming)
        - exactbars: -2, -1, False (different memory management modes)
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
