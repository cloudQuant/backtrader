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

"""Test module for validating indicator minimum period calculations.

This module tests that various backtrader indicators correctly calculate and
respect their minimum period requirements. The minimum period is the number of
bars an indicator needs before it can produce valid output values.

The test validates indicators including:
    - SMA (Simple Moving Average)
    - Stochastic oscillator
    - MACD (Moving Average Convergence Divergence)
    - Highest (maximum value over N periods)

The MACD indicator is used as the reference for the expected minimum period
(chkmin = 34), which accounts for the default parameters:
    - fast period: 12
    - slow period: 26
    - signal period: 9
    - minimum period = max(12, 26) + 9 - 1 = 34

Example:
    To run this test directly::

        python test_ind_minperiod.py

    To run as part of the test suite::

        pytest tests/original_tests/test_ind_minperiod.py -v
"""

import backtrader as bt

import testcommon

import backtrader.indicators as btind

# Number of data feeds to use for testing
chkdatas = 1
# List for storing expected indicator values (empty for this test)
chkvals = []

# Expected minimum period - derived from MACD with default parameters
# MACD requires: max(fast, slow) + signal - 1 = max(12, 26) + 9 - 1 = 34
chkmin = 34  # from MACD
# List of indicator classes to test for minimum period calculation
chkind = [btind.SMA, btind.Stochastic, btind.MACD, btind.Highest]
# Additional keyword arguments to pass to indicator constructors
chkargs = dict()


def test_run(main=False):
    """Run the indicator minimum period test.

    This function loads test data feeds and executes a backtest using the
    TestStrategy with multiple indicators to verify that minimum period
    calculations are correct.

    Args:
        main (bool, optional): If True, enables plotting and detailed output.
            Defaults to False, which runs the test silently for automated
            testing. When True, displays visualization of indicator behavior.

    Returns:
        None. The function runs the test through testcommon.runtest() which
        returns a list of Cerebro instances, but this function does not
        propagate the return value.

    Example:
        Run test without visualization (for CI/CD)::

            test_run()

        Run test with visualization (for manual inspection)::

            test_run(main=True)
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
