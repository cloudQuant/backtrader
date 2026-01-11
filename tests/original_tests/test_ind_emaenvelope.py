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

"""Test module for EMAEnvelope indicator.

This module tests the Exponential Moving Average (EMA) Envelope indicator
implementation in backtrader. The EMA Envelope creates bands above and below
an EMA by adding/subtracting a percentage of the EMA value.

The test validates:
1. Indicator calculation accuracy at specific data points
2. Minimum period requirements
3. Compatibility across different execution modes (runonce/preload combinations)

Expected values are pre-calculated for three checkpoints:
* Top envelope (upper band)
* Middle EMA (center line)
* Bottom envelope (lower band)

Example:
    Run the test directly to see a plot:
        python test_ind_emaenvelope.py

    Run via pytest for automated testing:
        pytest test_ind_emaenvelope.py -v
"""

import backtrader as bt

import testcommon

import backtrader.indicators as btind

# Number of data feeds to test
chkdatas = 1

# Expected indicator values at checkpoints for validation
# Each inner list contains [top_envelope, middle_ema, bottom_envelope] values
chkvals = [
    ["4070.115719", "3644.444667", "3581.728712"],
    ["4171.868612", "3735.555783", "3671.271930"],
    ["3968.362826", "3553.333550", "3492.185494"],
]

# Expected minimum period before indicator produces valid values
chkmin = 30

# Indicator class being tested
chkind = btind.EMAEnvelope


def test_run(main=False):
    """Run the EMAEnvelope indicator test.

    This function executes the test by loading data feeds, running the
    test strategy with multiple configuration combinations, and validating
    the indicator output against expected values.

    The test runs with different combinations of:
    * runonce mode (True/False)
    * preload mode (True/False)
    * exactbars settings

    Args:
        main (bool, optional): If True, enable plotting and detailed output
            for manual inspection. Defaults to False, which runs in
            automated test mode.

    Returns:
        None: The function runs the test and raises assertions if
            validation fails.

    Example:
        Run in automated mode:
            test_run()

        Run with plotting for manual inspection:
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
