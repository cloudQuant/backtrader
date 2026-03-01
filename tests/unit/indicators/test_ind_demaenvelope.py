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

"""Test module for DEMA Envelope indicator.

This module contains tests for the Double Exponential Moving Average (DEMA)
Envelope indicator in the backtrader framework. The DEMA Envelope consists
of an upper and lower band placed around a DEMA line, typically at a fixed
percentage distance above and below the central DEMA value.

The test validates that the DEMA Envelope indicator produces expected values
at specific checkpoint dates when applied to historical price data. It tests
the indicator across different execution modes (runonce/preload combinations)
to ensure consistent behavior.

Test Configuration:
    - Data source: 2006 daily price data (single data feed)
    - Indicator: DEMAEnvelope with default parameters
    - Expected minimum period: 59 bars
    - Checkpoints: 3 dates with expected top, middle, and bottom band values
"""

import backtrader as bt

import testcommon

import backtrader.indicators as btind

# Number of data feeds to use in the test
chkdatas = 1

# Expected indicator values at checkpoint dates
# Each inner list contains [top_band, middle_band, bottom_band] values
# as strings to match floating point precision
chkvals = [
    ["4115.563246", "3852.837209", "3665.728415"],
    ["4218.452327", "3949.158140", "3757.371626"],
    ["4012.674165", "3756.516279", "3574.085205"],
]

# Expected minimum period before indicator produces valid values
chkmin = 59

# Indicator class to test
chkind = btind.DEMAEnvelope


def test_run(main=False):
    """Run the DEMA Envelope indicator test.

    This function loads test data and executes the indicator test using the
    common test infrastructure. It tests the DEMAEnvelope indicator against
    expected values at predefined checkpoint dates.

    The test runs with multiple configuration combinations (runonce, preload,
    exactbars) when main=False to ensure the indicator works correctly across
    all execution modes.

    Args:
        main (bool, optional): If True, run in single mode with plotting enabled.
            Useful for manual inspection and debugging. Defaults to False.

    Returns:
        list: A list of Cerebro instances, one for each configuration tested.
            When main=True, returns a single instance with plot enabled.
    """
    # Load test data feeds
    datas = [testcommon.getdata(i) for i in range(chkdatas)]

    # Run the test with the configured parameters
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
    """Entry point for direct script execution.

    When the script is run directly (not imported), this block executes the
    test with plotting enabled for visual inspection of results.
    """
    test_run(main=True)
