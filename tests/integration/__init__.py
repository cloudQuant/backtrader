"""Integration tests for Backtrader.

This package contains integration tests that verify the end-to-end functionality
of Backtrader with external systems and services. These tests typically require
additional dependencies or network access and are slower to run than unit tests.

Test Categories:
    CCXT Tests: Live trading integration with cryptocurrency exchanges via CCXT
    Broker Tests: Integration tests for various broker implementations
    Feed Tests: Data feed integration with external data sources

Running Integration Tests:
    Integration tests are not run by default. Use the following command to run
    them:

        pytest tests/integration/ -v

    Note: Some tests may require API keys or other credentials to be configured
    via environment variables.
"""
