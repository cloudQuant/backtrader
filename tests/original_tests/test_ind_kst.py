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

"""Test module for the KST (Know Sure Thing) indicator.

This module contains test cases for the KST momentum indicator developed by
Martin Pring. The KST is a summed momentum indicator that combines multiple
rate-of-change (ROC) values with different periods, smoothed by moving averages,
and weighted by factors to produce a single momentum value with a signal line.

The test validates:
1. Indicator calculation accuracy across multiple data feeds
2. Minimum period requirements (48 bars)
3. Expected values at specific checkpoints in the data

Example:
    Run the test directly with plotting enabled:
    >>> python test_ind_kst.py

    Run via pytest:
    >>> pytest tests/original_tests/test_ind_kst.py -v
"""

import backtrader as bt

import testcommon


# Module-level test configuration
chkdatas = 1
chkvals = [["18.966300", "33.688645", "27.643797"], ["11.123593", "37.882890", "16.602624"]]

chkmin = 48
chkind = bt.ind.KST


def test_run(main=False):
    """Execute the KST indicator test with configured parameters.

    This function loads test data feeds and runs the backtest using the
    TestStrategy to validate KST indicator calculations. The test compares
    computed indicator values against expected checkpoint values.

    Args:
        main (bool, optional): If True, enables plotting and detailed output
            for manual inspection. Defaults to False.

    Returns:
        None: The function runs the test but does not return a value.
            Results are validated within the TestStrategy.stop() method.

    Raises:
        AssertionError: If indicator values do not match expected values
            at the checkpoint bars.

    Note:
        The expected checkpoint values are:
        - Data feed 1: ["18.966300", "33.688645", "27.643797"]
        - Data feed 2: ["11.123593", "37.882890", "16.602624"]

        These represent the KST line values at three different checkpoints:
        index 0 (first valid bar), midpoint, and last bar.
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
