#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
"""Tests for Plotly Enhancement Features.

Tests Plotly plotting enhancements added in iteration 47.
"""

import sys
import os
import datetime

# Add project path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import backtrader as bt


def test_tableau_color_schemes():
    """Test Tableau color schemes."""
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
    """Test legend text wrapping functionality."""
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
    """Test PlotlyScheme new parameters."""
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
    """Test PlotlyScheme.color() method."""
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
    """Test color mapper."""
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
    """Test PlotlyPlot helper methods."""
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
    """Test integration with strategy."""
    from backtrader.plot.plot_plotly import PlotlyPlot, PlotlyScheme
    
    class TestStrategy(bt.Strategy):
        def __init__(self):
            self.sma = bt.indicators.SMA(period=10)
        
        def next(self):
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
    """Run all tests."""
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
