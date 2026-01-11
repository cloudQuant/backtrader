#!/usr/bin/env python
"""Test module for HurstExponent indicator.

This module contains tests for the HurstExponent indicator implementation in
backtrader. The Hurst exponent is used to measure the long-term memory of time
series data, helping to identify trends and mean-reverting behavior.

The test validates that the HurstExponent indicator produces expected values
when applied to test data with a specified period. Expected values are
pre-calculated and compared against actual indicator outputs.

Example:
    Run the test directly:
        python test_ind_hurst.py

    Or run via pytest:
        pytest tests/add_tests/test_ind_hurst.py -v
"""

import warnings

import backtrader as bt

# Ignore numpy warnings during HurstExponent calculation (insufficient degrees of freedom)
warnings.filterwarnings("ignore", message="Degrees of freedom <= 0 for slice")
warnings.filterwarnings("ignore", message="invalid value encountered in")

import backtrader.indicators as btind

from . import testcommon

chkdatas = 1
chkvals = [
    ["0.209985", "0.299843", "0.432428"],
]

chkmin = 100
chkind = btind.HurstExponent


def test_run(main=False):
    """Run the HurstExponent indicator test.

    This function executes a test of the HurstExponent indicator by:
    1. Loading test data
    2. Creating a strategy with the indicator
    3. Running the backtest
    4. Comparing actual values against expected values

    Args:
        main (bool): If True, enables plotting and standalone execution mode.
                     When False (default), runs in test mode without plotting.
                     Defaults to False.

    Returns:
        None

    Raises:
        AssertionError: If the indicator values do not match expected values
                       within the tolerance defined in testcommon.

    Note:
        The expected values (chkvals) represent the Hurst exponent values
        that should be produced by the indicator for the given test data.
    """
    datas = [testcommon.getdata(i) for i in range(chkdatas)]
    testcommon.runtest(
        datas,
        testcommon.TestStrategy,
        main=main,
        plot=main,
        chkind=chkind,
        chkmin=chkmin,
        chkargs={"period": 100},
        chkvals=chkvals,
    )


if __name__ == "__main__":
    test_run(main=True)
