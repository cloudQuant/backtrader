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

"""Test module for the EMA Oscillator (EMAOsc) indicator.

This module tests the Exponential Moving Average Oscillator indicator, which
calculates the difference between a fast EMA and a slow EMA to identify
momentum and potential trend reversals.

The test validates:
1. Indicator calculation accuracy at specific checkpoints
2. Proper minimum period handling
3. Compatibility across different execution modes (runonce, preload, exactbars)

Test Data:
    Uses 2006 daily OHLCV data for validation.
    Expected values are validated at the beginning, middle, and end of the dataset.

Example:
    Run the test standalone:
        python test_ind_emaosc.py

    Run with plotting:
        pytest test_ind_emaosc.py::test_run -k True
"""

import backtrader as bt

import testcommon

import backtrader.indicators as btind

# Number of data feeds to use in the test
chkdatas = 1

# Expected values for the oscillator's output lines at specific checkpoints
# Format: [line1_values, line2_values, line3_values]
# Each inner list contains string representations of float values
chkvals = [["49.824281", "51.185333", "-24.648712"]]

# Expected minimum period before the indicator produces valid output
chkmin = 30

# The indicator class being tested
chkind = btind.EMAOsc


def test_run(main=False):
    """Execute the EMA Oscillator indicator test.

    This function loads test data, creates a test strategy with the EMA Oscillator
    indicator, and validates the calculated values against expected results across
    multiple execution modes.

    The test runs through different combinations of:
    - runonce (True/False): Batch vs bar-by-bar processing
    - preload (True/False): Preload data vs streaming data
    - exactbars (-2, -1, False): Different memory optimization modes

    Args:
        main (bool, optional): If True, enables plotting and verbose output for
            manual inspection. Defaults to False.

    Returns:
        None. The function raises an assertion error if test validation fails.

    Raises:
        AssertionError: If calculated indicator values do not match expected values
            at any checkpoint, or if minimum period is incorrect.

    Example:
        >>> test_run(main=False)  # Run test silently
        >>> test_run(main=True)   # Run test with plotting
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
