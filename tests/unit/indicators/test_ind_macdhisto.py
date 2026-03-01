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

"""Test module for MACDHisto indicator validation.

This module contains tests for the MACDHisto (Moving Average Convergence
Divergence Histogram) indicator in the backtrader framework. It validates
that the indicator produces expected values across different data feeds
and execution modes.

The MACDHisto indicator is a momentum oscillator that calculates the
difference between the MACD line and the signal line, providing a visual
representation of the convergence and divergence of these two moving
averages.

Test Configuration:
    - Data feeds: 1 (uses 2006-day-001.txt)
    - Expected values: 3 checkpoints with 3 values each (macd, signal, histo)
    - Minimum period: 34 bars
    - Indicator class: btind.MACDHisto

Typical usage:
    Run as a script to execute the test with plotting:
        $ python test_ind_macdhisto.py

    Or import and run programmatically:
        >>> from test_ind_macdhisto import test_run
        >>> test_run(main=False)
"""

import backtrader as bt
import backtrader.indicators as btind
import testcommon

# Number of data feeds to test with
chkdatas = 1

# Expected values at checkpoints for validation
# Each inner list contains: [macd_value, signal_value, histogram_value]
# Values are taken from three different checkpoints in the data
chkvals = [
    ["25.821368", "32.469404", "1.772445"],
    ["21.977853", "26.469735", "-2.845646"],
    ["3.843516", "5.999669", "4.618090"],
]

# Expected minimum period before indicator produces valid values
chkmin = 34

# The indicator class being tested
chkind = btind.MACDHisto


def test_run(main=False):
    """Execute the MACDHisto indicator test.

    This function loads test data, creates a test strategy, and runs the
    backtest to validate that the MACDHisto indicator produces expected
    values at predefined checkpoints.

    The test validates indicator calculations across different execution
    modes (runonce/preload combinations) to ensure consistent behavior.

    Args:
        main (bool, optional): If True, enables plotting and verbose output
            for manual inspection. If False, runs silently for automated
            testing. Defaults to False.

    Returns:
        None: The function executes the test but does not return a value.
            Results are validated internally by the TestStrategy.

    Raises:
        AssertionError: If indicator values do not match expected values
            at checkpoints, or if minimum period is incorrect.

    Example:
        >>> test_run(main=False)
        # Runs test silently
        >>> test_run(main=True)
        # Runs test with plot output
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
