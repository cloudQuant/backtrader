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

"""Test module for Vortex indicator.

This module contains test cases for the Vortex indicator implementation in
backtrader. The Vortex indicator is a technical analysis tool used to identify
trend reversals and confirm current trends. It consists of two oscillators:
- Plus Vortex (VI+): Measures upward trend movement
- Minus Vortex (VI-): Measures downward trend movement

The test module validates that the Vortex indicator produces expected values
for given data feeds under specified conditions.

Module Variables:
    chkdatas (int): Number of data feeds to test (set to 1).
    chkvals (list): Expected values for the Vortex indicator lines. Contains
        two sublists with expected values for [vi_plus, vi_minus, diff] for
        each data feed.
    chkmin (int): Minimum period required for the indicator (set to 15).
    chkind (type): The Vortex indicator class being tested.
"""

import backtrader as bt

import testcommon

import backtrader.indicators as btind

chkdatas = 1
chkvals = [["1.245434", "0.921076", "1.062278"], ["0.707948", "0.966375", "0.803849"]]

chkmin = 15
chkind = btind.Vortex


def test_run(main=False):
    """Execute the Vortex indicator test.

    This function loads test data, runs the test strategy with the Vortex
    indicator, and validates the results against expected values. The test
    compares the actual indicator output with predefined expected values to
    ensure correct implementation.

    Args:
        main (bool): If True, enables plot visualization for the test results.
            When False, runs the test without generating plots. Default is False.

    Returns:
        None

    Raises:
        AssertionError: If the actual indicator values do not match the expected
            values specified in chkvals.
        Exception: Any exceptions raised during data loading, strategy execution,
            or indicator calculation.
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
