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

"""Test module for the Pretty Good Oscillator (PGO) indicator.

This module contains tests for the PGO (Pretty Good Oscillator) indicator
implementation in backtrader. The PGO indicator is a momentum oscillator that
measures the price position relative to its moving average, normalized by
the average true range.

Test Configuration:
    - Number of data feeds: 1 (uses 2006-day-001.txt)
    - Expected minimum period: 15 bars
    - Indicator class: backtrader.indicators.PGO
    - Expected values: ['0.543029', '-2.347884', '0.416325']

The test runs the PGO indicator through multiple execution modes (runonce,
preload, exactbars) to ensure consistent behavior across all configurations.
"""

import backtrader as bt

import testcommon

import backtrader.indicators as btind

# Test configuration constants
chkdatas = 1
chkvals = [["0.543029", "-2.347884", "0.416325"]]

chkmin = 15
chkind = btind.PGO


def test_run(main=False):
    """Run the PGO indicator test.

    Executes the PGO indicator test using the standard test framework. Loads
    test data, creates a strategy with the PGO indicator, and validates the
    calculated values against expected results at specific checkpoints.

    The test is run with different combinations of runonce, preload, and
    exactbars settings to ensure compatibility across all execution modes.

    Args:
        main (bool, optional): If True, enables plot generation for visual
            inspection. Defaults to False.

    Returns:
        None: The function runs the test but does not return a value.
            Results are validated internally by the test framework.

    Raises:
        AssertionError: If the calculated indicator values do not match
            the expected values at any checkpoint.

    Example:
        >>> test_run()  # Run test without plotting
        >>> test_run(main=True)  # Run test with plot generation
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
