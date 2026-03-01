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

"""Test module for AccelerationDecelerationOscillator indicator.

This module tests the AccelerationDecelerationOscillator (AC) indicator implementation
in backtrader. The AC indicator is a momentum oscillator developed by Bill Williams
that measures the acceleration and deceleration of the driving force in the market.

The test validates:
1. Indicator calculation accuracy against expected values
2. Minimum period requirements
3. Multiple execution modes (runonce, preload, exactbars combinations)

Example:
    To run the test directly:
        python test_ind_accdecosc.py

    To run as part of pytest:
        pytest tests/original_tests/test_ind_accdecosc.py
"""

import backtrader as bt

import testcommon


# Number of data feeds to use for testing
chkdatas = 1

# Expected indicator values at specific checkpoints
# These values are validated against the computed AC indicator values
chkvals = [["-2.097441", "14.156647", "30.408335"]]

# Minimum period required for the indicator to produce valid values
chkmin = 38

# The indicator class being tested
chkind = bt.ind.AccelerationDecelerationOscillator


def test_run(main=False):
    """Run the AccelerationDecelerationOscillator indicator test.

    This function executes the test by loading test data, running the test strategy
    with the indicator, and validating the results against expected values.

    Args:
        main (bool, optional): If True, enables plot output for manual inspection.
            Defaults to False.

    Returns:
        None. The function runs the test and raises exceptions if validation fails.

    Raises:
        AssertionError: If computed indicator values do not match expected values.
        Exception: For any other errors during test execution.

    Example:
        Run test with plotting for manual inspection:
            test_run(main=True)

        Run test in automated mode:
            test_run(main=False)
    """
    # Load test data feeds
    datas = [testcommon.getdata(i) for i in range(chkdatas)]

    # Run the test with multiple configuration combinations
    # Tests various combinations of runonce, preload, and exactbars settings
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
