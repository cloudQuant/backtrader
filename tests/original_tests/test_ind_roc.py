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

"""Test module for Rate of Change (ROC) indicator.

This module tests the ROC (Rate of Change) indicator implementation in backtrader.
The ROC indicator measures the percentage change in price over a specified period,
calculated as:

    ROC = ((price - price_n_periods_ago) / price_n_periods_ago) * 100

The test validates:
* Indicator value calculations at specific checkpoints
* Minimum period requirements
* Compatibility across different execution modes (runonce, preload, exactbars)

Example:
    To run the test with plotting:
        python test_ind_roc.py

    To run as part of the test suite:
        pytest tests/original_tests/test_ind_roc.py
"""

import backtrader as bt

import testcommon

import backtrader.indicators as btind

# Number of data feeds to use in the test
chkdatas = 1

# Expected ROC indicator values at specific checkpoints
# These values represent the percentage change at different points in the data
chkvals = [
    ["0.016544", "-0.009477", "0.019050"],
]

# Expected minimum period before indicator produces valid values
# ROC needs this many bars of history before calculation
chkmin = 13

# The ROC indicator class being tested
chkind = btind.ROC


def test_run(main=False):
    """Run the ROC indicator test.

    This function executes a backtest using the ROC indicator and validates
    that the calculated values match the expected values at specific checkpoints.
    The test runs through multiple configuration combinations (runonce, preload,
    exactbars) to ensure compatibility across all execution modes.

    Args:
        main (bool, optional): If True, enables plotting for visual inspection.
            When run as the main script, this is set to True. Defaults to False.

    Returns:
        None: The function runs the test but does not return a value.
            Results are validated internally by the TestStrategy.

    Raises:
        AssertionError: If indicator values do not match expected values at
            any checkpoint, or if minimum period is incorrect.

    Example:
        >>> test_run(main=False)  # Run test without plotting
        >>> test_run(main=True)   # Run test with plotting enabled
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
