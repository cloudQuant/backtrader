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

"""Test module for SMMAEnvelope indicator.

This module contains tests for the Smoothed Moving Average (SMMA) Envelope
indicator, which creates bands around a SMMA at a percentage distance above
and below the average. The module validates that the SMMAEnvelope indicator
produces expected output values when applied to test data.

The test uses predefined data sources and expected values to verify the
correctness of the indicator calculation.
"""

import backtrader as bt

import testcommon

import backtrader.indicators as btind

# Number of data feeds to test
chkdatas = 1

# Expected output values for the SMMAEnvelope indicator
# Each inner list contains expected values for different data points
# Format: [top_envelope, smma, bottom_envelope] for each test case
chkvals = [
    ["4021.569725", "3644.444667", "3616.427648"],
    ["4122.108968", "3735.555783", "3706.838340"],
    ["3921.030482", "3553.333550", "3526.016957"],
]

# Minimum period required for the indicator to produce valid output
chkmin = 30

# The indicator class being tested
chkind = btind.SMMAEnvelope


def test_run(main=False):
    """Run the SMMAEnvelope indicator test.

    This function loads test data, executes the test strategy with the
    SMMAEnvelope indicator, and validates the output against expected values.

    The test performs the following steps:
    1. Loads test data feeds
    2. Runs the test strategy using the TestStrategy class
    3. Validates indicator output against expected values in chkvals
    4. Optionally plots results and runs in standalone mode

    Args:
        main (bool, optional): If True, enables plotting and standalone
            execution mode. When False, runs in test mode without plotting.
            Defaults to False.

    Returns:
        None

    Raises:
        AssertionError: If the actual indicator values do not match the
            expected values in chkvals.
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
