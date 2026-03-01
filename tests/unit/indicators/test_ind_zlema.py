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

"""Test suite for Zero Lag Exponential Moving Average (ZLEMA) indicator.

This module contains tests for the ZLEMA (Zero Lag Exponential Moving Average)
indicator implementation in backtrader. ZLEMA is designed to reduce the lag
inherent in traditional exponential moving averages by using a de-lagged
data series.

The test validates:
1. Indicator calculation accuracy at specific checkpoints
2. Minimum period requirements
3. Compatibility across different execution modes (runonce, preload, exactbars)

Test Configuration:
    - Data Source: 2006 daily OHLCV data (data file 0)
    - Indicator: ZLEMA (Zero Lag Exponential Moving Average)
    - Minimum Period: 44 bars
    - Checkpoint Values: Expected values at start, middle, and end points

Example:
    To run the test manually with plotting:
        python test_ind_zlema.py

    To run via pytest:
        pytest tests/original_tests/test_ind_zlema.py -v
"""

import backtrader as bt

import testcommon

import backtrader.indicators as btind

chkdatas = 1
chkvals = [["4125.487746", "3778.694000", "3620.284712"]]

chkmin = 44
chkind = btind.ZLEMA


def test_run(main=False):
    """Run the ZLEMA indicator test.

    Executes a backtest using the TestStrategy with ZLEMA indicator to validate
    calculation accuracy against expected checkpoint values.

    The test runs with multiple configuration combinations:
        - runonce: True/False (batch vs. bar-by-bar execution)
        - preload: True/False (data preloading)
        - exactbars: -2, -1, False (memory management modes)

    Args:
        main (bool, optional): If True, enable plotting and detailed output.
            Defaults to False for automated testing. When True, the test will
            display visualization of results.

    Returns:
        list: List of Cerebro instances, one for each configuration tested.
            Each instance contains the backtest results for validation.

    Raises:
        AssertionError: If calculated indicator values do not match expected
            values at any checkpoint, or if minimum period requirements are not met.

    Example:
        >>> # Run test without plotting (for automated testing)
        >>> cerebros = test_run(main=False)
        >>>
        >>> # Run test with plotting (for manual inspection)
        >>> cerebros = test_run(main=True)
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
