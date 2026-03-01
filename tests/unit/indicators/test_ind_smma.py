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

"""Test module for the SMMA (Smoothed Moving Average) indicator.

This module contains test cases to verify the correctness of the SMMA
indicator implementation in backtrader.
"""

import backtrader as bt

import testcommon

import backtrader.indicators as btind

# Number of data feeds to use in the test
chkdatas = 1

# Expected SMMA values for verification
chkvals = [
    ["4021.569725", "3644.444667", "3616.427648"],
]

# Minimum period required for the indicator
chkmin = 30

# Indicator class to test
chkind = btind.SMMA


def test_run(main=False):
    """Run the SMMA indicator test.

    Args:
        main (bool): If True, runs in main mode with plotting enabled.
            Defaults to False.

    Returns:
        None
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
