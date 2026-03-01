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

"""Test module for SMA Oscillator indicator.

This module contains tests for the SMAOsc (Simple Moving Average Oscillator)
indicator, which measures the deviation of price from its simple moving average.
The oscillator is calculated as the difference between the data source and
its SMA, providing insight into overbought/oversold conditions.

The test validates that the indicator produces expected values at specific
checkpoints when run with various Backtrader configuration combinations
(runonce, preload, exactbars settings).

Typical usage example:
    >>> test_run(main=True)

Module-level variables:
    chkdatas: Number of data feeds to use in the test.
    chkvals: Expected indicator values at checkpoint positions.
    chkmin: Expected minimum period before indicator produces valid values.
    chkind: The indicator class being tested (SMAOsc).
"""

import backtrader as bt

import testcommon

import backtrader.indicators as btind

chkdatas = 1
chkvals = [["56.477000", "51.185333", "2.386667"]]

chkmin = 30
chkind = btind.SMAOsc


def test_run(main=False):
    """Execute the SMA Oscillator indicator test.

    Runs the test strategy with the SMAOsc indicator using a single data feed.
    The test validates indicator calculations against expected values at
    specific checkpoint positions. When run with main=True, plots the results.

    The function loads test data, creates a backtest with the TestStrategy,
    and runs it through multiple configuration combinations (runonce, preload,
    exactbars) to ensure compatibility across all execution modes.

    Args:
        main (bool, optional): If True, enables plotting and verbose output
            for manual inspection. Defaults to False.

    Returns:
        None: The function executes the test but does not return a value.
            Results are validated internally by the TestStrategy.

    Raises:
        None: This function does not raise exceptions directly. Test failures
            are handled by the underlying test framework.

    Example:
        >>> test_run(main=True)  # Run with plotting enabled
        >>> test_run()  # Run in automated test mode
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
