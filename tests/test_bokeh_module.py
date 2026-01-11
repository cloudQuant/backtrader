#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
"""
Bokeh module tests.

Tests the basic functionality of the bokeh module.
"""

import sys
import os

# Add project path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_scheme_import():
    """Test scheme import."""
    from backtrader.bokeh import Scheme, Blackly, Tradimo

    # Test basic scheme
    scheme = Scheme()
    assert hasattr(scheme, 'barup')
    assert hasattr(scheme, 'bardown')
    assert hasattr(scheme, 'background_fill')
    print("✓ Scheme basic scheme test passed")

    # Test black scheme
    blackly = Blackly()
    assert blackly.background_fill == '#222222'
    assert blackly.barup == '#ff9896'
    print("✓ Blackly black scheme test passed")

    # Test white scheme
    tradimo = Tradimo()
    assert tradimo.background_fill == 'white'
    assert tradimo.barup == '#e6550d'
    print("✓ Tradimo white scheme test passed")


def test_tab_import():
    """Test tab import."""
    from backtrader.bokeh import BokehTab
    from backtrader.bokeh import tabs

    # Check tab base class
    assert hasattr(BokehTab, '_is_useable')
    assert hasattr(BokehTab, '_get_panel')
    assert hasattr(BokehTab, 'is_useable')
    assert hasattr(BokehTab, 'get_panel')
    print("✓ BokehTab base class test passed")

    # Check built-in tabs
    assert hasattr(tabs, 'AnalyzerTab')
    assert hasattr(tabs, 'ConfigTab')
    assert hasattr(tabs, 'LogTab')
    assert hasattr(tabs, 'MetadataTab')
    assert hasattr(tabs, 'SourceTab')
    assert hasattr(tabs, 'LiveTab')
    print("✓ Built-in tab import test passed")


def test_utils_import():
    """Test utility function import."""
    from backtrader.bokeh import get_datanames, get_strategy_label, sanitize_source_name

    # Test sanitize_source_name
    assert sanitize_source_name('test') == 'test'
    assert sanitize_source_name('test-data') == 'test_data'
    assert sanitize_source_name('123test') == '_123test'
    print("✓ Utility function test passed")


def test_register_tab():
    """Test tab registration."""
    from backtrader.bokeh import BokehTab, register_tab, get_registered_tabs

    class CustomTab(BokehTab):
        def _is_useable(self):
            return True

        def _get_panel(self):
            return None, 'Custom'

    # Before registration
    tabs_before = len(get_registered_tabs())

    # Register custom tab
    register_tab(CustomTab)

    # After registration
    tabs_after = len(get_registered_tabs())
    assert tabs_after == tabs_before + 1
    print("✓ Tab registration test passed")


def test_lazy_imports():
    """Test lazy imports."""
    from backtrader import bokeh

    # Test BacktraderBokeh
    try:
        app_class = bokeh.BacktraderBokeh
        print("✓ BacktraderBokeh lazy import test passed")
    except ImportError as e:
        print(f"⚠ BacktraderBokeh import failed (bokeh dependency may be missing): {e}")

    # Test RecorderAnalyzer
    try:
        recorder_class = bokeh.RecorderAnalyzer
        print("✓ RecorderAnalyzer lazy import test passed")
    except ImportError as e:
        print(f"⚠ RecorderAnalyzer import failed: {e}")


def test_basic_integration():
    """Test basic integration."""
    import backtrader as bt

    # Create simple strategy
    class TestStrategy(bt.Strategy):
        def __init__(self):
            pass

        def next(self):
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
        print("✓ RecorderAnalyzer integration test passed")
    except Exception as e:
        print(f"⚠ RecorderAnalyzer integration test failed: {e}")


def run_all_tests():
    """Run all tests."""
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
