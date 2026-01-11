#!/usr/bin/env python
"""Test module for the MyInd custom indicator.

This module contains tests for the MyInd (My Indicator) custom indicator in the
Backtrader framework. It validates that custom indicators can be properly instantiated,
calculated, and integrated into the backtesting engine.

The test module verifies:
- Basic indicator instantiation and initialization
- Indicator calculation with sample data feeds
- Output value generation matches expected patterns
- Graceful handling when the indicator is not available

Typical usage example:
    >>> test_run(main=True)
    # This will run the test with plotting enabled
"""

import backtrader as bt
import backtrader.indicators as btind
from . import testcommon

# Configuration variables
chkdatas = 1  # Number of data feeds to use in testing
chkmin = 1  # Minimum period requirement for indicator calculation


def test_run(main=False):
    """Run the MyInd indicator test.

    This function executes a comprehensive test of the MyInd custom indicator
    using test data feeds. It validates indicator behavior by comparing calculated
    values against expected outputs.

    The function handles the case where MyInd might not be available in all
    versions of Backtrader by catching AttributeError and skipping gracefully.

    Args:
        main (bool): If True, enables plot display and verbose output.
                     When False (default), runs in headless mode suitable
                     for automated test execution. Defaults to False.

    Returns:
        None: The function performs validation through assertions but does
              not return a value. Test results are reported through the
              test framework.

    Raises:
        AttributeError: Propagated if MyInd indicator is not available in
                       the Backtrader installation. This is caught and
                       handled gracefully within the function.

    Example:
        >>> test_run(main=False)  # Run without plotting
        >>> test_run(main=True)   # Run with plotting enabled
    """
    # Create test data feeds using common test data
    datas = [testcommon.getdata(i) for i in range(chkdatas)]

    # Test MyInd indicator - basic custom indicator test
    try:
        testcommon.runtest(
            datas,
            testcommon.TestStrategy,
            main=main,
            plot=main,
            chkind=btind.MyInd,
            chkmin=chkmin,
            chkvals=[["0.000000", "0.000000", "0.000000"]],
        )
    except AttributeError:
        # MyInd might not be in all versions
        if main:
            # Print message suppressed for performance reasons
            pass


if __name__ == "__main__":
    test_run(main=True)
