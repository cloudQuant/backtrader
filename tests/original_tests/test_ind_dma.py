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

"""Test module for the DMA (Displaced Moving Average) indicator.

This module contains tests for the DMA indicator, which calculates a displaced
moving average that can be shifted forward or backward in time. The test validates
that the indicator produces expected values at specific checkpoints and that
the minimum period is correctly calculated.

The DMA indicator is useful for:
* Identifying trends by comparing moving averages with different displacements
* Reducing lag in trading signals by displacing the moving average
* Creating crossover systems with displaced averages

Test Configuration:
    * Data Source: 2006-day-001.txt (daily OHLCV data)
    * Indicator: btind.DMA (Displaced Moving Average)
    * Expected Minimum Period: 30 bars
    * Checkpoint Values: Pre-calculated DMA values at specific indices

Example:
    To run this test directly::

        python test_ind_dma.py

    To run via pytest::

        pytest tests/original_tests/test_ind_dma.py -v
"""

import backtrader as bt

import testcommon

import backtrader.indicators as btind

# Number of data feeds to use for testing
chkdatas = 1

# Expected DMA values at checkpoints (end, middle, start of valid period)
# Format: [value_at_end, value_at_middle, value_at_start]
chkvals = [["4121.903804", "3677.634675", "3579.962958"]]


# Expected minimum period for the DMA indicator
chkmin = 30

# The indicator class being tested
chkind = btind.DMA


def test_run(main=False):
    """Run the DMA indicator test with configurable execution mode.

    This function loads test data, creates a backtest strategy with the DMA
    indicator, and runs the test across multiple configurations (runonce,
    preload, exactbars) to ensure compatibility.

    The test validates:
        * Minimum period calculation (30 bars)
        * Indicator values at three checkpoints
        * Proper execution in all backtest modes

    Args:
        main (bool, optional): If True, enables plotting and detailed output
            for manual inspection. When run as the main script, this is set
            to True. Defaults to False.

    Returns:
        None. The test is executed and results are validated internally.

    Raises:
        AssertionError: If indicator values don't match expected results or
            if minimum period is incorrectly calculated.

    Example:
        >>> test_run(main=True)  # Run with plotting
        >>> test_run(main=False)  # Run silently for automated testing
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
