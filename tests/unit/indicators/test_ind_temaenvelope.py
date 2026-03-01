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
"""Test module for TEMA Envelope indicator.

This module tests the Triple Exponential Moving Average (TEMA) Envelope indicator
implementation in backtrader. The TEMA Envelope consists of three lines:
- Upper band: TEMA + (TEMA * deviation_percentage)
- Middle band: TEMA
- Lower band: TEMA - (TEMA * deviation_percentage)

The test validates that the indicator produces expected values at specific
checkpoints when processing historical price data.

Test Configuration:
    - Data Source: 2006 daily price data (single data feed)
    - Indicator: TEMAEnvelope
    - Minimum Period: 88 bars
    - Checkpoints: Three specific points in time for validation

Expected Values:
    The test validates three lines at three different checkpoints (first bar,
    last bar, and middle bar).
"""

import backtrader as bt

import testcommon

import backtrader.indicators as btind

# Number of data feeds to test with
chkdatas = 1

# Expected values for the TEMA Envelope indicator at checkpoints
# Each inner list contains [upper_band, middle_band, lower_band] as strings
chkvals = [
    ["4113.721705", "3862.386854", "3832.691054"],
    ["4216.564748", "3958.946525", "3928.508331"],
    ["4010.878663", "3765.827182", "3736.873778"],
]

# Expected minimum period before indicator produces valid values
chkmin = 88

# The indicator class being tested
chkind = btind.TEMAEnvelope


def test_run(main=False):
    """Run the TEMA Envelope indicator test.

    Loads test data, creates a strategy with the TEMAEnvelope indicator,
    and validates that the indicator produces expected values at specific
    checkpoints. The test can be run in two modes:

    1. Automated test mode (main=False): For pytest execution
    2. Main mode (main=True): For manual execution with plotting

    Args:
        main (bool, optional): If True, enables plotting and detailed output
            for manual inspection. If False, runs in automated test mode.
            Defaults to False.

    Returns:
        None. The function runs the test through testcommon.runtest() which
        internally creates Cerebro instances and executes the backtest.

    Raises:
        AssertionError: If indicator values at checkpoints do not match
            expected values.

    Example:
        >>> # Run automated test
        >>> test_run()

        >>> # Run with plotting for manual inspection
        >>> test_run(main=True)
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
