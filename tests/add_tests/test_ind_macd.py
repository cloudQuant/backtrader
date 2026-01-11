#!/usr/bin/env python
"""Test module for MACD (Moving Average Convergence Divergence) indicator.

This module tests the MACDHisto indicator from backtrader.indicators to ensure
correct calculation of MACD values including the MACD line, signal line, and
histogram. The test validates indicator outputs against known expected values
at specific checkpoints in the data.

The test uses sample data from 2006 and validates that the MACDHisto indicator
produces consistent results across different execution modes (runonce vs next,
preload vs non-preload, and various exactbars settings).

Test Configuration:
    - Data Source: 2006-day-001.txt (daily OHLCV data)
    - Indicator: MACDHisto (MACD Histogram)
    - Expected Minimum Period: 34 bars
    - Checkpoints: 3 validation points (first, middle, last accessible bars)
    - Lines Tested: macd, signal, histo (3 output lines)

Expected Values:
    At checkpoint 0 (first bar): macd=25.821368, signal=32.469404, histo=1.772445
    At checkpoint 1 (middle bar): macd=21.977853, signal=26.469735, histo=-2.845646
    At checkpoint 2 (last bar): macd=3.843516, signal=5.999669, histo=4.618090
"""

import backtrader as bt

import backtrader.indicators as btind

from . import testcommon

chkdatas = 1
chkvals = [
    ["25.821368", "32.469404", "1.772445"],
    ["21.977853", "26.469735", "-2.845646"],
    ["3.843516", "5.999669", "4.618090"],
]

chkmin = 34
chkind = btind.MACDHisto


def test_run(main=False):
    """Execute the MACD indicator test.

    This function loads test data, creates a test strategy with the MACDHisto
    indicator, and runs the backtest across multiple configuration combinations
    to validate the indicator's calculations.

    The test is run with different combinations of:
        - runonce (True/False): Batch processing vs bar-by-bar
        - preload (True/False): Preload all data vs load on demand
        - exactbars (-2, -1, False): Different memory management modes

    Args:
        main (bool, optional): If True, enables plotting and detailed output
            for manual inspection. Defaults to False, which runs automated
            assertion-based testing.

    Returns:
        None. The function executes the test and raises AssertionError if
            any validation fails.

    Raises:
        AssertionError: If calculated MACD values do not match expected values
            at any checkpoint, or if the minimum period is incorrect.
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
