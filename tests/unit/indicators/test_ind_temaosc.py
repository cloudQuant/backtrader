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

"""Test module for the TEMAOsc (Triple Exponential Moving Average Oscillator) indicator.

This module contains tests for the TEMAOsc indicator, which is a momentum
oscillator derived from the Triple Exponential Moving Average (TEMA). The TEMA
oscillator calculates the difference between price and the TEMA, providing
signals about overbought and oversold conditions.

The test validates that the TEMAOsc indicator:
1. Calculates values correctly at specific checkpoints
2. Requires the correct minimum period before producing valid output
3. Works correctly across different backtrader execution modes

Test Data:
    Uses 2006 daily price data (first data file) for calculations.

Expected Values:
    At specified checkpoints, the indicator should produce:
    - First checkpoint: 6.218295
    - Second checkpoint: 15.143146
    - Third checkpoint: -23.991054

Module Constants:
    chkdatas (int): Number of data feeds to use (1).
    chkvals (list): Expected indicator values at test checkpoints.
    chkmin (int): Expected minimum period (88 bars).
    chkind (type): Indicator class to test (btind.TEMAOsc).
"""

import backtrader as bt

import testcommon

import backtrader.indicators as btind

chkdatas = 1
chkvals = [["6.218295", "15.143146", "-23.991054"]]

chkmin = 88
chkind = btind.TEMAOsc


def test_run(main=False):
    """Execute the TEMAOsc indicator test.

    This function loads test data, runs the test strategy with the TEMAOsc
    indicator, and validates the calculated values against expected results.
    The test can be run in two modes: automated (main=False) for regression
    testing, or manual (main=True) with plotting for visual inspection.

    Args:
        main (bool, optional): If True, run in manual mode with plotting enabled.
            Defaults to False, which runs automated testing without visualization.

    Returns:
        None. The function executes the test and raises assertions if validation fails.

    Raises:
        AssertionError: If the calculated indicator values do not match the
            expected values at the specified checkpoints, or if the minimum
            period is incorrect.

    Example:
        >>> test_run()  # Automated test
        >>> test_run(main=True)  # Manual test with plot
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
