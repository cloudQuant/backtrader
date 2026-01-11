"""Additional test suite for backtrader framework.

This module contains extended test coverage for the backtrader quantitative trading
framework, including tests for indicators, strategies, errors, and store functionality.
These tests complement the original test suite by covering additional edge cases,
error conditions, and extended functionality.

The test suite is organized into the following categories:
    - Indicator tests: Basic operations and calculations
    - Error handling tests: Exception classes and error scenarios
    - Store tests: Base store class validation
    - Strategy tests: Trading strategy behavior validation
    - Analyzer tests: Performance metric calculations

Example:
    To run all additional tests::

        $ python -m pytest tests/add_tests/ -v

    To run a specific test file::

        $ python -m pytest tests/add_tests/test_ind_basicops.py -v

Note:
    Tests in this module use common utilities from testcommon.py including:
        - getdata(): Load test data feeds
        - runtest(): Execute backtests with multiple configurations
        - TestStrategy: Base strategy for indicator validation
"""

import backtrader as bt

# Test suite for extended backtrader coverage
