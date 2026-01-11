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

"""Test module for the PriceOsc (Price Oscillator) indicator.

This module contains tests for the Price Oscillator indicator, which measures
the difference between two moving averages as a percentage. The Price Oscillator
is a momentum indicator that shows the relationship between two moving averages
and helps identify trend strength and potential reversals.

The test validates:
* Indicator calculation accuracy at specific checkpoint values
* Minimum period requirements (26 bars for default settings)
* Proper behavior across different execution modes (runonce/preload combinations)

Test Data:
    Uses 2006 daily OHLCV data from backtrader test fixtures.
    Expected checkpoint values:
    * osc: Price oscillator line values
    * signal: Signal line values
    * histo: Histogram (oscillator - signal) values
"""

import backtrader as bt

import testcommon

import backtrader.indicators as btind

# Number of data feeds to use for testing
chkdatas = 1

# Expected values at checkpoints [osc, signal, histo]
# Format: string representations of floating point values
chkvals = [["25.821368", "23.202675", "-9.927422"]]

# Expected minimum period for the indicator
chkmin = 26

# The indicator class being tested
chkind = btind.PriceOsc


def test_run(main=False):
    """Execute the Price Oscillator indicator test.

    This function loads test data and runs the indicator through multiple
    execution configurations to validate correctness. It tests various
    combinations of runonce, preload, and exactbars settings to ensure
    the indicator works correctly across all modes.

    The test creates a backtest with the PriceOsc indicator and validates
    that the calculated values match expected checkpoint values.

    Args:
        main (bool, optional): If True, enables plotting and verbose output
            for manual inspection. Defaults to False.

    Returns:
        list: A list of Cerebro instances, one for each configuration tested.
            Each Cerebro instance contains the executed strategy and indicator.

    Example:
        >>> test_run()
        [Cerebro instance 1, Cerebro instance 2, ...]

        >>> test_run(main=True)  # Enable plotting
        [Cerebro instance with plot]
    """
    # Load test data feeds
    datas = [testcommon.getdata(i) for i in range(chkdatas)]

    # Run the test with all configurations
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
    # Run the test with plotting when executed directly
    test_run(main=True)
