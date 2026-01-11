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

"""Test module for the PctChange (Percentage Change) indicator.

This module contains test cases for the PctChange indicator, which calculates
the percentage change between consecutive data points. The test validates that
the indicator produces expected values at specific checkpoints in the data.

The test uses standard backtrader test data files and runs the indicator through
multiple execution modes (runonce/preload combinations) to ensure compatibility.

Example:
    To run this test directly:
        python test_ind_pctchange.py

    To run via pytest:
        pytest test_ind_pctchange.py -v
"""

import backtrader as bt

import testcommon

import backtrader.indicators as btind

# Number of data feeds to use in the test
chkdatas = 1

# Expected values at checkpoints for validation
# Format: list of lists, where each inner list contains string representations
# of expected values for each line of the indicator at specific checkpoint bars
chkvals = [["0.002704", "0.034162", "0.043717"]]

# Expected minimum period before indicator starts producing values
chkmin = 31

# The indicator class being tested
chkind = btind.PctChange


def test_run(main=False):
    """Run the PctChange indicator test.

    This function executes a comprehensive test of the PctChange indicator by:
    1. Loading test data from predefined data files
    2. Running the indicator through the TestStrategy
    3. Validating output against expected values at checkpoints

    The test can run in two modes:
    - main=False: Runs silently without plotting (for automated testing)
    - main=True: Enables plotting and detailed output (for manual inspection)

    Args:
        main (bool, optional): If True, run in interactive mode with plotting.
            Defaults to False, which runs silently for automated testing.

    Returns:
        None. The function executes the test and raises assertions if
        validation fails.

    Raises:
        AssertionError: If the indicator values do not match expected values
            at the checkpoint bars.

    Example:
        >>> test_run(main=False)  # Silent mode for automated testing
        >>> test_run(main=True)   # Interactive mode with plotting
    """
    # Load data feeds for the test
    datas = [testcommon.getdata(i) for i in range(chkdatas)]

    # Run the test with the configured parameters
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
