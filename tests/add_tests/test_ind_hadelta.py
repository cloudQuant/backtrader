#!/usr/bin/env python
"""Tests for the haDelta (Heikin-Ashi Delta) indicator.

This module contains test cases for the haDelta indicator, which measures the
difference between Heikin-Ashi close prices and their simple moving average.
The indicator is used to identify momentum changes in the Heikin-Ashi chart.

The test validates that the haDelta indicator correctly calculates values
across different data feeds and execution modes (runonce, preload, exactbars).

Example:
    Run the test directly from command line:
        python test_ind_hadelta.py

    Or import and run programmatically:
        from tests.add_tests.test_ind_hadelta import test_run
        test_run(main=True)
"""

import backtrader as bt
import backtrader.indicators as btind
from . import testcommon

# Number of data feeds to use in the test
chkdatas = 1

# Expected indicator values at checkpoints for validation
# Format: [value_at_checkpoint_0, value_at_checkpoint_1, value_at_checkpoint_2]
# Each inner list represents a different line of the indicator
chkvals = [
    ["8.536393", "33.289375", "46.992371"],
    ["13.866583", "28.956875", "69.517198"],
]

# Expected minimum period for the indicator
chkmin = 4

# The indicator class to test
chkind = btind.haDelta


def test_run(main=False):
    """Run the haDelta indicator test suite.

    This function loads test data feeds and runs the indicator through multiple
    execution modes (runonce/preload combinations) to validate correct behavior.

    The test compares calculated indicator values against expected values at
    specific checkpoints to ensure accuracy.

    Args:
        main (bool, optional): If True, enables plotting and verbose output.
            Useful for manual inspection during development. Defaults to False.

    Returns:
        list: A list of Cerebro instances, one for each configuration tested.
            Each instance contains the results of a backtest run.

    Example:
        >>> test_run()
        [Cerebro instance 1, Cerebro instance 2, ...]

        >>> test_run(main=True)
        # Displays plot and detailed output
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
