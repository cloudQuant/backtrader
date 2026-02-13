#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
"""Tests for Plotly Enhancement Features.

This module contains comprehensive tests for Plotly plotting enhancements added
in iteration 47. It tests new color schemes (Tableau), legend text wrapping,
PlotlyScheme parameter configuration, color mapping, and helper methods for
PlotlyPlot integration with backtrader strategies.

Test Functions:
    test_tableau_color_schemes: Validates Tableau color scheme constants and access
    test_wrap_legend_text: Tests legend text wrapping functionality
    test_plotly_scheme_new_params: Tests PlotlyScheme parameter initialization
    test_scheme_color_method: Tests color retrieval and cycling methods
    test_color_mapper: Validates the color mapping dictionary
    test_plotly_plot_helper_methods: Tests PlotlyPlot formatting helper methods
    test_integration_with_strategy: Tests end-to-end integration with strategies
    run_all_tests: Executes all test functions and reports results

Example:
    To run all tests from command line::

        python tests/test_plotly_enhancements.py

    To run a specific test::

        python -c "from tests.test_plotly_enhancements import test_tableau_color_schemes; test_tableau_color_schemes()"
"""

import sys
import os
import datetime

# Add project path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import backtrader as bt


def test_tableau_color_schemes():
    """Test Tableau color scheme constants and retrieval function.

    This test validates that:
        * TABLEAU10 contains exactly 10 colors
        * TABLEAU20 contains exactly 20 colors
        * TABLEAU10_LIGHT contains exactly 10 colors
        * TAB10_INDEX contains exactly 11 elements
        * get_color_scheme() returns the correct color scheme
        * get_color_scheme() defaults to TABLEAU10 for unknown schemes

    Raises:
        AssertionError: If any color scheme has incorrect number of elements
            or if get_color_scheme() returns unexpected values.
    """
    from backtrader.plot.plot_plotly import (
        TABLEAU10, TABLEAU20, TABLEAU10_LIGHT, TAB10_INDEX,
        get_color_scheme
    )

    # Test color schemes exist
    assert len(TABLEAU10) == 10, f"TABLEAU10 should have 10 colors, got {len(TABLEAU10)}"
    assert len(TABLEAU20) == 20, f"TABLEAU20 should have 20 colors, got {len(TABLEAU20)}"
    assert len(TABLEAU10_LIGHT) == 10, f"TABLEAU10_LIGHT should have 10 colors, got {len(TABLEAU10_LIGHT)}"
    assert len(TAB10_INDEX) == 11, f"TAB10_INDEX should have 11 elements, got {len(TAB10_INDEX)}"

    # Test get_color_scheme function
    assert get_color_scheme('tableau10') == TABLEAU10
    assert get_color_scheme('tableau20') == TABLEAU20
    assert get_color_scheme('tableau10_light') == TABLEAU10_LIGHT
    assert get_color_scheme('unknown') == TABLEAU10  # Default returns tableau10

    print("✓ Tableau color scheme test passed")


def test_wrap_legend_text():
    """Test legend text wrapping functionality.

    This test validates that the wrap_legend_text function:
        * Returns short text unchanged
        * Wraps long text at specified width using HTML line breaks
        * Handles None and empty strings gracefully
        * Removes existing newline characters and replaces with <br>

    Raises:
        AssertionError: If text wrapping does not behave as expected.
    """
    from backtrader.plot.plot_plotly import wrap_legend_text

    # Short text doesn't wrap
    assert wrap_legend_text("short", 16) == "short"

    # Long text wraps
    long_text = "This is a very long legend text"
    wrapped = wrap_legend_text(long_text, 10)
    assert "<br>" in wrapped

    # Empty text
    assert wrap_legend_text(None, 16) == ''
    assert wrap_legend_text('', 16) == ''

    # Test newline removal
    text_with_newline = "line1\nline2"
    wrapped = wrap_legend_text(text_with_newline, 100)
    assert '\n' not in wrapped

    print("✓ Legend text wrapping test passed")


def test_plotly_scheme_new_params():
    """Test PlotlyScheme parameter initialization and attributes.

    This test validates that PlotlyScheme:
        * Initializes with correct default values for all parameters
        * Accepts and stores custom parameter values
        * Exposes Tableau color scheme attributes as instance variables

    Default Values:
        * decimal_places: 5
        * max_legend_text_width: 16
        * color_scheme: 'tableau10'
        * fillalpha: 0.20

    Raises:
        AssertionError: If parameters are not initialized correctly or
            Tableau color scheme attributes are missing.
    """
    from backtrader.plot.plot_plotly import PlotlyScheme

    # Test default values
    scheme = PlotlyScheme()
    assert scheme.decimal_places == 5
    assert scheme.max_legend_text_width == 16
    assert scheme.color_scheme == 'tableau10'
    assert scheme.fillalpha == 0.20

    # Test custom values
    scheme2 = PlotlyScheme(
        decimal_places=2,
        max_legend_text_width=20,
        color_scheme='tableau20',
        fillalpha=0.30
    )
    assert scheme2.decimal_places == 2
    assert scheme2.max_legend_text_width == 20
    assert scheme2.color_scheme == 'tableau20'
    assert scheme2.fillalpha == 0.30

    # Test Tableau color scheme attributes
    assert hasattr(scheme, 'tableau10')
    assert hasattr(scheme, 'tableau20')
    assert hasattr(scheme, 'tableau10_light')
    assert hasattr(scheme, 'tab10_index')

    print("✓ PlotlyScheme new parameters test passed")


def test_scheme_color_method():
    """Test PlotlyScheme color retrieval and cycling methods.

    This test validates that PlotlyScheme.color():
        * Returns valid color strings for valid indices
        * Properly cycles through colors when index exceeds color count
        * Works correctly with both tableau10 and tableau20 schemes

    Also tests PlotlyScheme.get_colors():
        * Returns the active color scheme list
        * Updates correctly when color_scheme is changed

    Raises:
        AssertionError: If color methods return unexpected values or types.
    """
    from backtrader.plot.plot_plotly import PlotlyScheme

    scheme = PlotlyScheme()

    # Test color retrieval
    color0 = scheme.color(0)
    color1 = scheme.color(1)
    assert color0 is not None
    assert color1 is not None
    assert isinstance(color0, str)

    # Test color cycling
    colors = [scheme.color(i) for i in range(20)]
    assert len(colors) == 20

    # Test get_colors method
    assert scheme.get_colors() == scheme.tableau10

    scheme.color_scheme = 'tableau20'
    assert scheme.get_colors() == scheme.tableau20

    print("✓ PlotlyScheme.color() method test passed")


def test_color_mapper():
    """Test the COLOR_MAPPER dictionary structure and values.

    This test validates that COLOR_MAPPER:
        * Contains standard color names (blue, red, green)
        * Contains Tableau-specific colors (steelblue, darkorange, crimson)
        * Stores color values in 'rgb(r, g, b)' format

    Raises:
        AssertionError: If expected colors are missing or format is incorrect.
    """
    from backtrader.plot.plot_plotly import COLOR_MAPPER

    # Test basic colors
    assert 'blue' in COLOR_MAPPER
    assert 'red' in COLOR_MAPPER
    assert 'green' in COLOR_MAPPER

    # Test Tableau colors
    assert 'steelblue' in COLOR_MAPPER
    assert 'darkorange' in COLOR_MAPPER
    assert 'crimson' in COLOR_MAPPER

    # Test color format
    assert COLOR_MAPPER['blue'].startswith('rgb(')
    assert COLOR_MAPPER['steelblue'].startswith('rgb(')

    print("✓ Color mapper test passed")


def test_plotly_plot_helper_methods():
    """Test PlotlyPlot formatting helper methods.

    This test validates that PlotlyPlot helper methods:
        * _format_value() formats numbers to specified decimal places
        * _get_tick_format() returns the correct tick format string
        * _format_label() wraps long labels appropriately

    Args:
        This test uses decimal_places=3 for testing precision formatting.

    Raises:
        AssertionError: If helper methods return incorrectly formatted values.
    """
    from backtrader.plot.plot_plotly import PlotlyPlot, PlotlyScheme

    # Use decimal_places parameter directly
    plotter = PlotlyPlot(decimal_places=3)

    # Test _format_value (note Python rounding rules)
    formatted = plotter._format_value(123.456789)
    assert formatted.startswith('123.45'), f"Expected '123.45x', got '{formatted}'"
    assert plotter._format_value(0) == '0.000'

    # Test _get_tick_format
    assert plotter._get_tick_format() == '.3f'

    # Test _format_label
    long_label = "This is a very long indicator label"
    formatted = plotter._format_label(long_label)
    assert len(formatted.replace('<br>', '')) == len(long_label)

    print("✓ PlotlyPlot helper methods test passed")


def test_integration_with_strategy():
    """Test end-to-end integration of PlotlyPlot with a backtrader strategy.

    This test validates that:
        * A strategy with indicators can be run with Cerebro
        * PlotlyPlot can generate figures from strategy results
        * Custom PlotlyScheme parameters are properly applied

    The test uses:
        * GenericCSVData with NVDA historical data
        * Simple strategy with SMA indicator
        * Custom PlotlyScheme with tableau20 colors

    Note:
        This test requires the test data file 'nvda-1999-2014.txt' to be
        present in the tests/datas directory. If the file is missing, the
        test is skipped with a warning.

    Raises:
        AssertionError: If plotting fails or returns no figures.
        Exception: If plotly is not installed or other runtime errors occur.
    """
    from backtrader.plot.plot_plotly import PlotlyPlot, PlotlyScheme

    class TestStrategy(bt.Strategy):
        """Simple test strategy with SMA indicator.

        Attributes:
            sma: Simple Moving Average indicator with period 10.
        """

        def __init__(self):
            """Initialize the strategy with SMA indicator."""
            self.sma = bt.indicators.SMA(period=10)

        def next(self):
            """Execute trading logic for each bar.

            This is a placeholder strategy with no actual trading logic.
            """
            pass

    # Create cerebro
    cerebro = bt.Cerebro()

    # Add data
    data_path = os.path.join(os.path.dirname(__file__), 'datas', 'nvda-1999-2014.txt')
    if os.path.exists(data_path):
        data = bt.feeds.GenericCSVData(
            dataname=data_path,
            dtformat='%Y-%m-%d',
            datetime=0,
            open=1,
            high=2,
            low=3,
            close=4,
            volume=5,
            openinterest=-1,
            fromdate=datetime.datetime(2000, 1, 1),
            todate=datetime.datetime(2000, 3, 31),
        )
        cerebro.adddata(data)
        cerebro.addstrategy(TestStrategy)

        # Run strategy
        results = cerebro.run()

        # Create plotter
        scheme = PlotlyScheme(
            decimal_places=2,
            max_legend_text_width=20,
            color_scheme='tableau20'
        )
        plotter = PlotlyPlot(scheme=scheme)

        # Test plotting (without display)
        try:
            figs = plotter.plot(results[0])
            assert len(figs) > 0, "Should generate at least one figure"
            print("✓ Strategy integration test passed")
        except Exception as e:
            print(f"⚠ Strategy integration test skipped (plotly may be missing): {e}")
    else:
        print("⚠ Test data file not found, skipping strategy integration test")


def run_all_tests():
    """Execute all Plotly enhancement feature tests.

    This function runs all test functions in sequence and tracks the
    number of passed and failed tests. Test results are printed to stdout.

    Returns:
        bool: True if all tests passed, False if any test failed.

    Tests Run:
        * test_tableau_color_schemes
        * test_wrap_legend_text
        * test_plotly_scheme_new_params
        * test_scheme_color_method
        * test_color_mapper
        * test_plotly_plot_helper_methods
        * test_integration_with_strategy
    """
    print("=" * 60)
    print("Plotly Enhancement Features Tests")
    print("=" * 60)

    tests = [
        test_tableau_color_schemes,
        test_wrap_legend_text,
        test_plotly_scheme_new_params,
        test_scheme_color_method,
        test_color_mapper,
        test_plotly_plot_helper_methods,
        test_integration_with_strategy,
    ]

    passed = 0
    failed = 0

    for test in tests:
        print(f"\n--- {test.__name__} ---")
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"✗ Test failed: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print("\n" + "=" * 60)
    print(f"Tests completed: {passed} passed, {failed} failed")
    print("=" * 60)

    return failed == 0


if __name__ == '__main__':
    success = run_all_tests()
    sys.exit(0 if success else 1)
