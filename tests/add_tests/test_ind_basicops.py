#!/usr/bin/env python
"""Test basic indicator operations in backtrader.

This module tests the basic operation indicators in the backtrader framework,
specifically the Highest and Lowest indicators. These indicators track the
maximum and minimum values over a specified period.

The tests validate:
    - Highest indicator: Returns the highest high over N periods
    - Lowest indicator: Returns the lowest low over N periods
    - Correct minimum period calculation
    - Proper value calculations across different data configurations

Test Configuration:
    - Data: Uses 2006 daily OHLCV data from test fixtures
    - Period: 20 bars for both Highest and Lowest indicators
    - Checkpoints: Validates values at start, middle, and end of data series

Example:
    Run tests directly::

        $ python tests/add_tests/test_ind_basicops.py

    Or via pytest::

        $ python -m pytest tests/add_tests/test_ind_basicops.py -v

Note:
    Expected values are based on actual indicator runs and represent
    ground truth for validation. These values may need updating if
    indicator implementation changes significantly.
"""

import backtrader as bt

import backtrader.indicators as btind

from . import testcommon

# Number of data feeds to use in tests
chkdatas = 1


def test_highest(main=False):
    """Test the Highest indicator calculation.

    The Highest indicator tracks the highest high value over a specified period.
    This test validates that the indicator correctly calculates maximum values
    at various checkpoints in the data series.

    Test Configuration:
        - Indicator: bt.ind.Highest (Highest high tracker)
        - Period: 20 bars
        - Data: Single data feed (2006 daily data)
        - Expected values:
            * Start (index 0): 4140.66
            * Middle: 3685.48
            * End: 3670.75

    Args:
        main (bool, optional): If True, enable plotting and detailed output.
            Defaults to False for automated testing.

    Raises:
        AssertionError: If calculated values don't match expected values,
            or if minimum period is incorrect.

    Example:
        >>> test_highest(main=True)
        # Runs test and plots results
    """
    # Expected values at checkpoints [start, middle, end]
    # These values are from actual indicator runs on 2006 daily data
    chkvals = [
        ["4140.660000", "3685.480000", "3670.750000"],  # From actual run
    ]
    chkmin = 20  # Expected minimum period (matches indicator period)
    chkind = btind.Highest  # Indicator class to test

    # Load test data feeds
    datas = [testcommon.getdata(i) for i in range(chkdatas)]

    # Run the test with multiple configurations (runonce, preload, etc.)
    # Note: testcommon.TestStrategy.stop() contains assertions for chkvals
    testcommon.runtest(
        datas,
        testcommon.TestStrategy,
        main=main,
        plot=main,
        chkind=chkind,
        chkmin=chkmin,
        chkargs={"period": 20},  # Indicator parameters
        chkvals=chkvals,
    )


def test_lowest(main=False):
    """Test the Lowest indicator calculation.

    The Lowest indicator tracks the lowest low value over a specified period.
    This test validates that the indicator correctly calculates minimum values
    at various checkpoints in the data series.

    Test Configuration:
        - Indicator: bt.ind.Lowest (Lowest low tracker)
        - Period: 20 bars
        - Data: Single data feed (2006 daily data)
        - Expected values:
            * Start (index 0): 3932.09
            * Middle: 3532.68
            * End: 3490.24

    Args:
        main (bool, optional): If True, enable plotting and detailed output.
            Defaults to False for automated testing.

    Raises:
        AssertionError: If calculated values don't match expected values,
            or if minimum period is incorrect.

    Example:
        >>> test_lowest(main=True)
        # Runs test and plots results
    """
    # Expected values at checkpoints [start, middle, end]
    # These values are from actual indicator runs on 2006 daily data
    chkvals = [
        ["3932.090000", "3532.680000", "3490.240000"],  # From actual run
    ]
    chkmin = 20  # Expected minimum period (matches indicator period)
    chkind = btind.Lowest  # Indicator class to test

    # Load test data feeds
    datas = [testcommon.getdata(i) for i in range(chkdatas)]

    # Run the test with multiple configurations (runonce, preload, etc.)
    # Note: testcommon.TestStrategy.stop() contains assertions for chkvals
    testcommon.runtest(
        datas,
        testcommon.TestStrategy,
        main=main,
        plot=main,
        chkind=chkind,
        chkmin=chkmin,
        chkargs={"period": 20},  # Indicator parameters
        chkvals=chkvals,
    )


def test_run(main=False):
    """Run all basic indicator operations tests.

    This function executes the complete test suite for basic indicator operations,
    including both Highest and Lowest indicator tests.

    The test suite validates:
        1. Highest indicator calculates correct maximum values
        2. Lowest indicator calculates correct minimum values
        3. Both indicators respect minimum period requirements
        4. Both indicators work across different execution modes

    Args:
        main (bool, optional): If True, enable plotting and detailed output.
            Defaults to False for automated testing.

    Example:
        >>> test_run(main=True)
        # Runs all tests with plotting enabled
    """
    # Note: testcommon.TestStrategy.stop() contains assertions for chkvals
    test_highest(main)
    test_lowest(main)


if __name__ == "__main__":
    # Run all tests with main=True when executed directly
    test_run(main=True)
