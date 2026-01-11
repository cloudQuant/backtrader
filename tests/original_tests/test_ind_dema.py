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

"""Test module for the Double Exponential Moving Average (DEMA) indicator.

This module contains tests to verify the correct calculation and behavior
of the DEMA indicator in the backtrader framework. DEMA is a technical
indicator that reduces lag in exponential moving averages by using
a combination of single and double EMAs.

The test validates that the DEMA indicator produces expected values
for a given dataset after a minimum period of warmup bars.

Example:
    Run the test directly:
        python test_ind_dema.py

    Or run with plotting enabled:
        pytest test_ind_dema.py -v -s
"""

import backtrader as bt

import testcommon

import backtrader.indicators as btind

# Number of data feeds to test
chkdatas = 1

# Expected DEMA values at specific points in the data
chkvals = [["4115.563246", "3852.837209", "3665.728415"]]

# Minimum period required before DEMA calculations are valid
chkmin = 59

# The indicator class being tested
chkind = btind.DEMA


def test_run(main=False):
    """Run the DEMA indicator test.

    This function loads test data, executes the test strategy, and verifies
    that the DEMA indicator produces the expected values. It uses the
    common test infrastructure to perform the validation.

    Args:
        main (bool, optional): If True, enables plotting and interactive
            execution. Defaults to False.

    Returns:
        None

    Raises:
        AssertionError: If the calculated DEMA values do not match the
            expected values in chkvals.

    Example:
        test_run(main=False)  # Run test without plotting
        test_run(main=True)   # Run test with plotting enabled
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
