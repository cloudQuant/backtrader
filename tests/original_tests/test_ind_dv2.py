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

"""Test module for DV2 (Detrended Price Oscillator Version 2) indicator.

This module contains tests for the DV2 indicator, which is a momentum oscillator
that measures the position of a security's price relative to a selected moving
average representation of price. The DV2 indicator is used to identify overbought
and oversold conditions and potential trend reversals.

The test validates that the DV2 indicator calculates values correctly across
different execution modes (runonce/preload combinations) and produces expected
results at specific checkpoints in the data.

Test Configuration:
    - Data Source: Single data feed (2006-day-001.txt)
    - Indicator: DV2 (Detrended Price Oscillator Version 2)
    - Expected Minimum Period: 253 bars
    - Expected Values: Three checkpoint values for validation

Example:
    Run the test directly with plotting enabled::

        python test_ind_dv2.py

    Or import and run programmatically::

        from tests.original_tests import test_ind_dv2
        test_ind_dv2.test_run()
"""

import backtrader as bt

import testcommon

import backtrader.indicators as btind

chkdatas = 1
chkvals = [
    ["17.460317", "55.952381", "80.555556"],
]

chkmin = 253
chkind = btind.DV2


def test_run(main=False):
    """Run the DV2 indicator test.

    Executes the DV2 indicator test by loading test data, creating a backtest
    strategy, and validating indicator calculations against expected values.
    The test runs across multiple configuration combinations to ensure
    compatibility.

    Args:
        main (bool, optional): If True, enables plotting and detailed output
            for manual inspection. Defaults to False.

    Returns:
        list: List of Cerebro instances, one for each configuration tested.
            The configurations include different combinations of runonce,
            preload, and exactbars settings.

    Example:
        Run test with plotting enabled::

            test_run(main=True)

        Run test silently for automated testing::

            test_run()
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
