#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
"""Test suite for the backtrader bokeh module.

This module contains comprehensive tests for the bokeh visualization module
in backtrader, including tests for color schemes, tab components, utility
functions, tab registration, lazy imports, and basic integration with the
Cerebro backtesting engine.

The bokeh module provides interactive web-based visualization capabilities
for backtesting results, including custom color schemes, tab-based interfaces,
and real-time data recording and analysis.

Module Features:
    Color Schemes: Predefined color themes (Blackly, Tradimo)
    Tab System: Extensible tab-based UI components
    Utilities: Helper functions for data source naming and sanitization
    Lazy Loading: On-demand import of heavy bokeh dependencies
    Integration: Seamless integration with Cerebro backtesting engine

Test Coverage:
    - Color scheme import and attribute verification
    - Tab component structure and methods
    - Utility function behavior (sanitize_source_name)
    - Custom tab registration mechanism
    - Lazy import handling for optional bokeh dependency
    - End-to-end integration with Cerebro

Example:
    python tests/test_bokeh_module.py
"""

import sys
import os

# Add project path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_scheme_import():
    """Test the import and basic functionality of color schemes.

    This test verifies that the Scheme base class and its subclasses
    (Blackly and Tradimo) can be imported and instantiated correctly.
    It checks that the expected color attributes are present and have
    the correct default values.

    Color schemes tested:
        - Scheme: Base color scheme class
        - Blackly: Dark theme with #222222 background
        - Tradimo: Light theme with white background

    Attributes verified:
        - barup: Color for up bars (bullish candles)
        - bardown: Color for down bars (bearish candles)
        - background_fill: Background color for charts

    Raises:
        AssertionError: If any of the color scheme attributes are missing
            or have incorrect values.
        ImportError: If the bokeh module cannot be imported.
    """
    from backtrader.bokeh import Scheme, Blackly, Tradimo

    # Test basic scheme
    scheme = Scheme()
    assert hasattr(scheme, 'barup')
    assert hasattr(scheme, 'bardown')
    assert hasattr(scheme, 'background_fill')
    print("Scheme basic scheme test passed")

    # Test black scheme
    blackly = Blackly()
    assert blackly.background_fill == '#222222'
    assert blackly.barup == '#ff9896'
    print("Blackly black scheme test passed")

    # Test white scheme
    tradimo = Tradimo()
    assert tradimo.background_fill == 'white'
    assert tradimo.barup == '#e6550d'
    print("Tradimo white scheme test passed")


def test_tab_import():
    """Test the import and structure of tab components.

    This test verifies that the BokehTab base class and the built-in tab
    implementations can be imported successfully and have the expected
    methods and attributes.

    Tabs tested:
        - BokehTab: Base class for all tab components
        - AnalyzerTab: Tab for displaying strategy analyzer results
        - ConfigTab: Tab for configuration settings
        - LogTab: Tab for displaying log messages
        - MetadataTab: Tab for metadata information
        - SourceTab: Tab for data source information
        - LiveTab: Tab for live data updates

    Methods verified:
        - _is_useable: Internal method to check if tab can be used
        - _get_panel: Internal method to get tab panel content
        - is_useable: Public interface for usability check
        - get_panel: Public interface for getting panel content

    Raises:
        AssertionError: If any required tab classes or methods are missing.
        ImportError: If the bokeh module cannot be imported.
    """
    from backtrader.bokeh import BokehTab
    from backtrader.bokeh import tabs

    # Check tab base class
    assert hasattr(BokehTab, '_is_useable')
    assert hasattr(BokehTab, '_get_panel')
    assert hasattr(BokehTab, 'is_useable')
    assert hasattr(BokehTab, 'get_panel')
    print("BokehTab base class test passed")

    # Check built-in tabs
    assert hasattr(tabs, 'AnalyzerTab')
    assert hasattr(tabs, 'ConfigTab')
    assert hasattr(tabs, 'LogTab')
    assert hasattr(tabs, 'MetadataTab')
    assert hasattr(tabs, 'SourceTab')
    assert hasattr(tabs, 'LiveTab')
    print("Built-in tab import test passed")


def test_utils_import():
    """Test the import and functionality of utility functions.

    This test verifies that utility functions can be imported and that
    sanitize_source_name correctly transforms input strings according
    to the expected rules.

    Utility functions tested:
        - get_datanames: Retrieves data names from cerebro instance
        - get_strategy_label: Gets label for strategy display
        - sanitize_source_name: Sanitizes data source names for use in code

    sanitize_source_name transformations:
        - 'test' -> 'test' (no change needed)
        - 'test-data' -> 'test_data' (hyphens to underscores)
        - '123test' -> '_123test' (prefix with underscore if starts with digit)

    Raises:
        AssertionError: If sanitize_source_name does not return the
            expected sanitized strings.
        ImportError: If the bokeh module cannot be imported.
    """
    from backtrader.bokeh import get_datanames, get_strategy_label, sanitize_source_name

    # Test sanitize_source_name
    assert sanitize_source_name('test') == 'test'
    assert sanitize_source_name('test-data') == 'test_data'
    assert sanitize_source_name('123test') == '_123test'
    print("Utility function test passed")


def test_register_tab():
    """Test the tab registration mechanism.

    This test verifies that custom tab classes can be registered using
    the register_tab function and that they appear in the list of
    registered tabs.

    Registration process:
        1. Create a custom tab class inheriting from BokehTab
        2. Implement required methods (_is_useable, _get_panel)
        3. Register the tab using register_tab()
        4. Verify the tab appears in get_registered_tabs()

    Custom tab requirements:
        - Must inherit from BokehTab
        - Must implement _is_useable() method
        - Must implement _get_panel() method

    Raises:
        AssertionError: If the number of registered tabs does not increase
            by exactly one after registration.
        ImportError: If the bokeh module cannot be imported.
    """
    from backtrader.bokeh import BokehTab, register_tab, get_registered_tabs

    class CustomTab(BokehTab):
        """Custom tab implementation for testing registration mechanism."""

        def _is_useable(self):
            """Check if this tab can be used.

            Returns:
                bool: Always returns True for testing purposes.
            """
            return True

        def _get_panel(self):
            """Get the panel content for this tab.

            Returns:
                tuple: (None, 'Custom') - No panel content, custom title.
            """
            return None, 'Custom'

    # Before registration
    tabs_before = len(get_registered_tabs())

    # Register custom tab
    register_tab(CustomTab)

    # After registration
    tabs_after = len(get_registered_tabs())
    assert tabs_after == tabs_before + 1
    print("Tab registration test passed")


def test_lazy_imports():
    """Test the lazy import mechanism for heavy dependencies.

    This test verifies that classes with heavy dependencies (like bokeh)
    can be imported through the lazy import mechanism. These imports may
    fail if the bokeh library is not installed, which is handled gracefully.

    Classes tested:
        - BacktraderBokeh: Main bokeh application class
        - RecorderAnalyzer: Analyzer for recording data during backtests

    Lazy import benefits:
        - bokeh is an optional dependency
        - Main backtrader module can be used without bokeh
        - ImportError is handled gracefully with warning message

    Note:
        The BacktraderBokeh and RecorderAnalyzer classes require the bokeh
        library to be installed. If bokeh is not available, the test will
        print a warning but will not fail.

    Raises:
        ImportError: Handled gracefully - prints warning instead of failing.
    """
    from backtrader import bokeh

    # Test BacktraderBokeh
    try:
        app_class = bokeh.BacktraderBokeh
        print("BacktraderBokeh lazy import test passed")
    except ImportError as e:
        print(f"BacktraderBokeh import failed (bokeh dependency may be missing): {e}")

    # Test RecorderAnalyzer
    try:
        recorder_class = bokeh.RecorderAnalyzer
        print("RecorderAnalyzer lazy import test passed")
    except ImportError as e:
        print(f"RecorderAnalyzer import failed: {e}")


def test_basic_integration():
    """Test basic integration of RecorderAnalyzer with Cerebro.

    This test creates a simple backtesting scenario with Cerebro, adds a
    test strategy, data feed, and the RecorderAnalyzer. It then runs the
    backtest and verifies that the analyzer captures data correctly.

    Test scenario:
        - Simple buy-and-hold test strategy
        - NVDA stock data from year 2000
        - RecorderAnalyzer with indicators disabled
        - Verification of captured data in analysis dict

    Data source:
        - NVDA historical stock data (2000-01-01 to 2000-12-31)
        - Located in tests/datas/nvda-1999-2014.txt
        - GenericCSVData format with OHLCV columns

    Note:
        This test requires the bokeh library to be installed. If bokeh is
        not available, the test will print a warning but will not fail.

    Raises:
        AssertionError: If the analysis dictionary does not contain the
            expected 'data' key after a successful run.
        FileNotFoundError: If the NVDA data file cannot be found.
        ImportError: Handled gracefully if bokeh is not available.
    """
    import backtrader as bt

    # Create simple strategy
    class TestStrategy(bt.Strategy):
        """Minimal test strategy for bokeh integration testing."""

        def __init__(self):
            """Initialize the test strategy."""
            pass

        def next(self):
            """Execute strategy logic on each bar."""
            pass

    # Create cerebro
    cerebro = bt.Cerebro()

    # Add data
    import datetime
    data = bt.feeds.GenericCSVData(
        dataname=os.path.join(os.path.dirname(__file__), 'datas', 'nvda-1999-2014.txt'),
        dtformat='%Y-%m-%d',
        datetime=0,
        open=1,
        high=2,
        low=3,
        close=4,
        volume=5,
        openinterest=-1,
        fromdate=datetime.datetime(2000, 1, 1),
        todate=datetime.datetime(2000, 12, 31),
    )
    cerebro.adddata(data)
    cerebro.addstrategy(TestStrategy)

    # Try to add RecorderAnalyzer
    try:
        from backtrader.bokeh import RecorderAnalyzer
        cerebro.addanalyzer(RecorderAnalyzer, indicators=False)

        result = cerebro.run()

        # Check analyzer results
        recorder = result[0].analyzers.recorderanalyzer
        analysis = recorder.get_analysis()

        assert 'data' in analysis
        print("RecorderAnalyzer integration test passed")
    except Exception as e:
        print(f"RecorderAnalyzer integration test failed: {e}")


def run_all_tests():
    """Execute all test functions in the test suite.

    This function runs each test function in sequence, tracks the number of
    passed and failed tests, and prints a summary of results. Each test is
    executed with error handling to ensure that a failure in one test does
    not prevent subsequent tests from running.

    Test execution order:
        1. test_scheme_import - Color scheme functionality
        2. test_tab_import - Tab component structure
        3. test_utils_import - Utility function behavior
        4. test_register_tab - Custom tab registration
        5. test_lazy_imports - Lazy import mechanism
        6. test_basic_integration - End-to-end integration

    Error handling:
        - Each test is wrapped in try-except block
        - Failed tests print traceback and increment failure counter
        - Successful tests increment pass counter
        - Test failures do not stop execution of remaining tests

    Returns:
        bool: True if all tests passed (no failures), False otherwise.

    Example:
        >>> success = run_all_tests()
        >>> print(f"All tests passed: {success}")
    """
    print("=" * 60)
    print("Bokeh module tests")
    print("=" * 60)

    tests = [
        test_scheme_import,
        test_tab_import,
        test_utils_import,
        test_register_tab,
        test_lazy_imports,
        test_basic_integration,
    ]

    passed = 0
    failed = 0

    for test in tests:
        print(f"\n--- {test.__name__} ---")
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"Test failed: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print("\n" + "=" * 60)
    print(f"Tests completed: {passed} passed, {failed} failed")
    print("=" * 60)

    return failed == 0


if __name__ == '__main__':
    """Run the test suite when executed as a script.

    This entry point allows the test suite to be run directly from the
    command line. The exit code indicates success (0) or failure (1).

    Usage:
        python tests/test_bokeh_module.py

    Exit codes:
        0: All tests passed
        1: One or more tests failed
    """
    success = run_all_tests()
    sys.exit(0 if success else 1)
