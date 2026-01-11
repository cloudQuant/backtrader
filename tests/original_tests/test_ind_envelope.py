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
"""Test module for the Envelope indicator.

This module contains tests for the Envelope technical indicator, which creates
upper and lower bands around a central moving average. The bands are typically
set at a fixed percentage above and below the central line.

The test validates that the Envelope indicator calculates values correctly
by comparing computed values against known expected results at specific
checkpoints in the data series.

Example:
    Run the test directly:
    $ python test_ind_envelope.py

    Or run via pytest:
    $ pytest tests/original_tests/test_ind_envelope.py -v
"""

import backtrader as bt
import backtrader.indicators as btind
import testcommon

# Number of data feeds to use in the test
chkdatas = 1

# Expected values for the Envelope indicator at specific checkpoints.
# Each inner list contains values for the top, middle, and bottom lines
# of the Envelope indicator at different checkpoint positions.
chkvals = [
    ["4063.463000", "3644.444667", "3554.693333"],
    ["4165.049575", "3735.555783", "3643.560667"],
    ["3961.876425", "3553.333550", "3465.826000"],
]

# Expected minimum period for the indicator
chkmin = 30

# The indicator class to test
chkind = btind.Envelope


class TS2(testcommon.TestStrategy):
    """Test strategy for Envelope indicator validation.

    This test strategy creates an SMA (Simple Moving Average) indicator and
    uses it as input data for the Envelope indicator. It inherits from
    TestStrategy which provides the validation framework for comparing
    computed values against expected results.

    Attributes:
        p.inddata (list): Will be populated with the SMA indicator to be used
            as input for the Envelope indicator.

    Note:
        The SMA is created before calling super().__init__() to ensure proper
        initialization order in the indicator chain.
    """

    def __init__(self):
        """Initialize the test strategy with an SMA indicator.

        Creates an SMA indicator on the strategy's data and assigns it to
        the inddata parameter. This SMA will be used as the input for the
        Envelope indicator during testing.
        """
        ind = btind.MovAv.SMA(self.data)
        self.p.inddata = [ind]
        super().__init__()


def test_run(main=True):
    """Run the Envelope indicator test.

    Executes the test by loading test data, running the test strategy with
    various configuration combinations (runonce/preload/exactbars modes),
    and validating the indicator values against expected results.

    Args:
        main (bool, optional): If True, enables verbose output for manual
            inspection. Defaults to True.

    Returns:
        None. The test runs assertions internally to validate results.

    Raises:
        AssertionError: If the computed indicator values do not match the
            expected values at the checkpoint positions.

    Note:
        This function is called both when running the module directly and
        when invoked through the pytest test framework. The test runs the
        strategy with multiple configuration combinations to ensure
        compatibility across different execution modes.
    """
    datas = [testcommon.getdata(i) for i in range(chkdatas)]
    testcommon.runtest(
        datas, TS2, main=main, plot=False, chkind=chkind, chkmin=chkmin, chkvals=chkvals
    )


if __name__ == "__main__":
    test_run(main=True)
