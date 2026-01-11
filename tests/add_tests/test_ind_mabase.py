#!/usr/bin/env python
"""Test module for Moving Average Base indicator validation.

This module tests the Moving Average Base (MABase) indicator by validating its
calculations against known expected values. The test loads historical OHLCV data,
applies the indicator with a 30-period period, and verifies that the calculated
values match the expected results at specific checkpoint indices.

The test is designed to work with the backtrader framework's testing infrastructure,
running the indicator through multiple execution modes (runonce/preload combinations)
to ensure compatibility across different backtesting configurations.

Module Constants:
    chkdatas (int): Number of data feeds to test with (default: 1).
    chkvals (list): Expected indicator values at checkpoint indices for validation.
    chkmin (int): Expected minimum period before indicator produces valid output (30).
    chkind (type): Indicator class to test (btind.SMA - Simple Moving Average).
"""

import backtrader as bt
import backtrader.indicators as btind

from . import testcommon

chkdatas = 1
chkvals = [
    ["4063.463000", "3644.444667", "3554.693333"],
]

chkmin = 30
chkind = btind.SMA


def test_run(main=False):
    """Execute the Moving Average Base indicator test.

    This function loads test data, creates a test strategy with the SMA indicator,
    and runs it through multiple configuration combinations to validate that the
    indicator produces correct results across different execution modes.

    The test validates:
    1. Indicator calculations match expected values at checkpoint indices
    2. Minimum period is correctly calculated
    3. Indicator works across different runonce/preload/exactbars configurations

    Args:
        main (bool, optional): If True, enable detailed output and plot results
            for manual inspection. Defaults to False.

    Returns:
        None: The function runs the test but does not return a value.
            Results are validated through assertions within the test strategy.

    Raises:
        AssertionError: If indicator values do not match expected results at
            checkpoint indices, or if minimum period calculation is incorrect.

    Example:
        Run test with automated validation only:
        >>> test_run()

        Run test with plotting for manual inspection:
        >>> test_run(main=True)
    """
    datas = [testcommon.getdata(i) for i in range(chkdatas)]
    testcommon.runtest(
        datas,
        testcommon.TestStrategy,
        main=main,
        plot=main,
        chkind=chkind,
        chkmin=chkmin,
        chkargs={"period": 30},
        chkvals=chkvals,
    )


if __name__ == "__main__":
    test_run(main=True)
