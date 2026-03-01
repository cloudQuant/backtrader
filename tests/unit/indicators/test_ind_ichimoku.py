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

"""Test module for the Ichimoku Kinko Hyo indicator.

This module contains test cases for the Ichimoku Kinko Hyo (Ichimoku Cloud)
technical indicator implementation in backtrader. The Ichimoku indicator is
a trend-following system that consists of five lines:
1. Tenkan-sen (Conversion Line): Fast moving average
2. Kijun-sen (Base Line): Slow moving average
3. Senkou Span A (Leading Span A): Cloud boundary 1
4. Senkou Span B (Leading Span B): Cloud boundary 2
5. Chikou Span (Lagging Span): Current price shifted back

The test validates that the Ichimoku indicator produces expected values
for a given dataset, ensuring calculation accuracy across all component lines.

Example:
    Run the test directly from command line:
        python test_ind_ichimoku.py

    Or import and run programmatically:
        from tests.original_tests import test_ind_ichimoku
        test_ind_ichimoku.test_run(main=True)
"""

import backtrader as bt

import testcommon


# Number of data feeds to use for testing
chkdatas = 1

# Expected Ichimoku indicator values for validation
# Each inner list contains expected values for [tenkan_sen, kijun_sen, senkou_span_b]
# at different points in the data series
chkvals = [
    ["4110.000000", "3821.030000", "3748.785000"],
    ["4030.920000", "3821.030000", "3676.860000"],
    ["4057.485000", "3753.502500", "3546.152500"],
    ["3913.300000", "3677.815000", "3637.130000"],
    [("nan", "3682.320000"), "3590.910000", "3899.410000"],
]

# Minimum period required before Ichimoku calculations are valid
# This accounts for the lookback periods of the component lines
chkmin = 78

# The Ichimoku indicator class being tested
chkind = bt.ind.Ichimoku


def test_run(main=False):
    """Execute the Ichimoku indicator test.

    This function loads test data, runs the Ichimoku indicator calculation,
    and validates the results against expected values. The test uses the
    common test framework to execute the strategy and compare indicator outputs.

    Args:
        main (bool, optional): If True, enables plotting and interactive mode.
            When False (default), runs in headless mode suitable for automated
            testing. Defaults to False.

    Returns:
        None

    Raises:
        AssertionError: If the calculated Ichimoku values do not match the
            expected values in chkvals.

    Example:
        Run test without plotting:
            test_run()

        Run test with plotting:
            test_run(main=True)
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
