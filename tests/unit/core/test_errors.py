#!/usr/bin/env python
"""Test error classes and exception handling in backtrader.

This module tests the error classes provided by the backtrader framework,
ensuring that exceptions can be properly raised, caught, and manipulated.
Error handling is critical for robust strategy development and backtesting.

The main error class tested is:
    StrategySkipError: Used to skip strategy execution during backtesting

Example:
    Run tests directly::

        $ python tests/add_tests/test_errors.py

    Or via pytest::

        $ python -m pytest tests/add_tests/test_errors.py -v
"""

import backtrader as bt

import os
import sys

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def test_errors(main=False):
    """Test that error classes exist and can be instantiated.

    This function verifies that the StrategySkipError exception class can be:
        1. Instantiated with a custom error message
        2. Raised and caught properly
        3. Converted to a string matching the original message

    The StrategySkipError is used to signal that a strategy should be skipped
    during backtesting, typically when certain preconditions are not met.

    Args:
        main (bool, optional): If True, print test results for manual inspection.
            Defaults to False.

    Raises:
        AssertionError: If the error message doesn't match the expected value.

    Example:
        >>> test_errors(main=True)
        Errors test passed
    """
    # Test StrategySkipError - verifies exception can be raised with custom message
    try:
        raise bt.errors.StrategySkipError("Test skip error")
    except bt.errors.StrategySkipError as e:
        if main:
            # Optionally print for manual verification (disabled for performance)
            # print(f'Caught StrategySkipError: {e}')
            pass
        # Verify the error message is preserved correctly
        assert str(e) == "Test skip error"

    if main:
        # Optionally print test completion (disabled for performance)
        # print('Errors test passed')
        pass


def test_business_exception_hierarchy():
    """The Sprint 3 category exceptions exist and stay backward compatible.

    DataError / BrokerError / OrderError / ConfigError must all derive from
    BacktraderError (so existing ``except BacktraderError`` keeps working), and
    OrderError must derive from BrokerError. They are exported at both
    ``bt.errors`` and the top-level ``bt`` namespace.
    """
    for name in ("DataError", "BrokerError", "OrderError", "ConfigError"):
        cls = getattr(bt.errors, name)
        assert issubclass(cls, bt.errors.BacktraderError)
        # exported at top level via star import
        assert getattr(bt, name) is cls

    # OrderError is a kind of BrokerError
    assert issubclass(bt.errors.OrderError, bt.errors.BrokerError)

    # legacy classes unchanged
    assert issubclass(bt.errors.StrategySkipError, bt.errors.BacktraderError)

    # instances carry their message and are catchable as the base
    try:
        raise bt.errors.OrderError("bad order size")
    except bt.errors.BrokerError as e:  # caught via the parent category
        assert str(e) == "bad order size"


if __name__ == "__main__":
    # Run tests with main=True when executed directly
    test_errors(main=True)
