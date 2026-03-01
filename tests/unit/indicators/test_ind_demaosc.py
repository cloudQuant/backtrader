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

"""Test module for the DEMAOsc (Double Exponential Moving Average Oscillator) indicator.

This module contains test cases for the DEMA Oscillator indicator, which measures
the deviation of price from the Double Exponential Moving Average (DEMA). The DEMA
was introduced by Patrick G. Mulloy in 1994 to reduce the lag associated with
traditional moving averages.

The oscillator is calculated as the difference between the data (price) and the
DEMA: osc = data - DEMA(data). This oscillates around zero, showing when price
is above (positive) or below (negative) the DEMA.

Test Configuration:
    - Data source: 2006 daily price data (single data feed)
    - Indicator: DEMAOsc (auto-generated from DEMA using OscillatorMixIn)
    - Expected minimum period: 59 bars
    - Expected values at checkpoints:
        * Index 0: 4.376754
        * Middle checkpoint: 7.292791
        * Final checkpoint: 9.371585

Example:
    Run the test from command line:
    $ python test_ind_demaosc.py

    Or import and run programmatically:
    >>> from test_ind_demaosc import test_run
    >>> test_run(main=False)
"""
import backtrader as bt

import testcommon

import backtrader.indicators as btind

# Test configuration module variables
chkdatas = 1
chkvals = [["4.376754", "7.292791", "9.371585"]]

chkmin = 59
chkind = btind.DEMAOsc


def test_run(main=False):
    """Run the DEMAOsc indicator test with multiple backtest configurations.

    This function executes a comprehensive test of the DEMAOsc indicator by:
    1. Loading test data from CSV files
    2. Running the indicator through multiple configuration combinations
       (different settings for runonce, preload, and exactbars modes)
    3. Validating the calculated values against expected checkpoints
    4. Optionally plotting results for visual inspection

    The test matrix ensures the indicator works correctly across all execution
    modes supported by backtrader.

    Args:
        main (bool, optional): If True, enables detailed output and plotting
            for manual inspection. If False, runs silently for automated testing.
            Defaults to False.

    Returns:
        None. The function executes the test but does not return a value.
        Test results are validated internally by the TestStrategy.

    Raises:
        AssertionError: If calculated indicator values do not match expected
            values at the specified checkpoints.

    Example:
        >>> test_run(main=False)  # Automated testing
        >>> test_run(main=True)   # Manual inspection with plots
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
