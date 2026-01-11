#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
"""
Bokeh interactive chart examples.

This example demonstrates how to use the Bokeh module for interactive visualization:
1. Using different themes - Scheme, Blackly, Tradimo
2. Using RecorderAnalyzer to record data
3. Custom tabs

Usage:
    python examples/example_bokeh_charts.py

Dependencies:
    pip install bokeh
"""

import datetime
import os
import sys

# Add project path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import backtrader as bt


class BokehSMAStrategy(bt.Strategy):
    """Dual moving average crossover strategy."""
    params = (('fast_period', 10), ('slow_period', 30),)
    
    def __init__(self):
        """Initialize strategy."""
        self.sma_fast = bt.indicators.SMA(self.data.close, period=self.p.fast_period)
        self.sma_slow = bt.indicators.SMA(self.data.close, period=self.p.slow_period)
        self.crossover = bt.indicators.CrossOver(self.sma_fast, self.sma_slow)
    
    def next(self):
        """Execute strategy logic on each bar."""
        if not self.position:
            if self.crossover > 0:
                self.buy()
        elif self.crossover < 0:
            self.close()


def example_schemes():
    """Example 1: Demonstrate different themes."""
    print("\n" + "=" * 60)
    print("Example 1: Bokeh Theme Demonstration")
    print("=" * 60)
    
    from backtrader.bokeh import Scheme, Blackly, Tradimo
    
    # Default theme
    scheme = Scheme()
    print("\nDefault theme (Scheme):")
    print(f"  Background color: {scheme.background_fill}")
    print(f"  Up color: {scheme.barup}")
    print(f"  Down color: {scheme.bardown}")
    
    # Black theme
    blackly = Blackly()
    print("\nBlack theme (Blackly):")
    print(f"  Background color: {blackly.background_fill}")
    print(f"  Up color: {blackly.barup}")
    print(f"  Down color: {blackly.bardown}")
    
    # White theme
    tradimo = Tradimo()
    print("\nWhite theme (Tradimo):")
    print(f"  Background color: {tradimo.background_fill}")
    print(f"  Up color: {tradimo.barup}")
    print(f"  Down color: {tradimo.bardown}")
    
    print("\n✓ Theme demonstration completed")


def example_utils():
    """Example 2: Utility functions."""
    print("\n" + "=" * 60)
    print("Example 2: Bokeh Utility Functions")
    print("=" * 60)
    
    from backtrader.bokeh import sanitize_source_name
    
    # Test name sanitization
    print("\nName sanitization (sanitize_source_name):")
    print(f"  'test' -> '{sanitize_source_name('test')}'")
    print(f"  'test-data' -> '{sanitize_source_name('test-data')}'")
    print(f"  '123test' -> '{sanitize_source_name('123test')}'")
    print(f"  'my.data.name' -> '{sanitize_source_name('my.data.name')}'")
    
    print("\n✓ Utility function demonstration completed")


def example_tabs():
    """Example 3: Tab system."""
    print("\n" + "=" * 60)
    print("Example 3: Bokeh Tab System")
    print("=" * 60)
    
    from backtrader.bokeh import BokehTab, tabs, register_tab, get_registered_tabs
    
    print("\nBuilt-in tab types:")
    tab_types = ['AnalyzerTab', 'ConfigTab', 'LogTab', 'MetadataTab', 'SourceTab', 'LiveTab']
    for tab_type in tab_types:
        if hasattr(tabs, tab_type):
            print(f"  ✓ {tab_type}")
    
    # Show registered tabs
    registered = get_registered_tabs()
    print(f"\nRegistered tabs count: {len(registered)}")
    
    # Demonstrate custom tabs
    print("\nCustom tab example:")
    print("""
    from backtrader.bokeh import BokehTab, register_tab
    
    class CustomTab(BokehTab):
        def _is_useable(self):
            return True
        
        def _get_panel(self):
            # Return (panel, title) tuple
            return None, 'Custom Tab'
    
    # Register custom tab
    register_tab(CustomTab)
    """)
    
    print("✓ Tab system demonstration completed")


def example_recorder_analyzer():
    """Example 4: RecorderAnalyzer usage."""
    print("\n" + "=" * 60)
    print("Example 4: RecorderAnalyzer Data Recording")
    print("=" * 60)
    
    cerebro = bt.Cerebro()
    
    # Load data
    data_path = os.path.join(os.path.dirname(__file__), '..', 'tests', 'datas', 'nvda-1999-2014.txt')
    if not os.path.exists(data_path):
        print(f"Data file does not exist: {data_path}")
        return
    
    data = bt.feeds.GenericCSVData(
        dataname=data_path,
        dtformat='%Y-%m-%d',
        datetime=0, open=1, high=2, low=3, close=4, volume=5, openinterest=-1,
        fromdate=datetime.datetime(2000, 1, 1),
        todate=datetime.datetime(2013, 6, 30),
    )
    cerebro.adddata(data, name='NVDA')
    cerebro.addstrategy(BokehSMAStrategy)
    
    # Add RecorderAnalyzer
    try:
        from backtrader.bokeh import RecorderAnalyzer
        cerebro.addanalyzer(RecorderAnalyzer, indicators=True)
        
        print("Running strategy...")
        results = cerebro.run()
        
        # Get recorded data
        recorder = results[0].analyzers.recorderanalyzer
        analysis = recorder.get_analysis()
        
        print("\nRecorded data keys:")
        for key in analysis.keys():
            print(f"  - {key}")
        
        if 'data' in analysis:
            data_records = analysis['data']
            print(f"\nRecorded data count: {len(data_records) if isinstance(data_records, list) else 'N/A'}")
        
        print("\n✓ RecorderAnalyzer demonstration completed")
    except ImportError as e:
        print(f"⚠ Need to install bokeh: pip install bokeh")
        print(f"  Error: {e}")


def example_backtrader_bokeh():
    """Example 5: Complete BacktraderBokeh usage."""
    print("\n" + "=" * 60)
    print("Example 5: Complete BacktraderBokeh Usage")
    print("=" * 60)
    
    print("""
Complete example code using BacktraderBokeh:

    import backtrader as bt
    from backtrader.bokeh import BacktraderBokeh, Blackly
    
    # Create strategy
    cerebro = bt.Cerebro()
    cerebro.adddata(data)
    cerebro.addstrategy(MyStrategy)
    
    # Run strategy
    results = cerebro.run()
    
    # Visualize with BacktraderBokeh
    b = BacktraderBokeh(
        style='bar',           # Chart style: 'bar', 'line', 'candle'
        scheme=Blackly(),      # Use black theme
        output_mode='show',    # 'show' display, 'save' save, 'memory' memory
    )
    
    # Plot
    b.plot(results)
    
Notes:
1. Need to install bokeh: pip install bokeh
2. output_mode='show' will open in browser
3. Can customize theme colors
    """)
    
    print("✓ BacktraderBokeh usage instructions completed")


def example_save_bokeh_html():
    """Example 6: Save Bokeh chart as HTML (optional)."""
    print("\n" + "=" * 60)
    print("Example 6: Save Bokeh Chart as HTML")
    print("=" * 60)
    print("\nNote: BacktraderBokeh chart generation requires complete Bokeh configuration")
    print("If errors occur, please refer to the following code for use in your project:")
    print('''
    from backtrader.bokeh import BacktraderBokeh, Blackly
    
    # After running strategy
    results = cerebro.run()
    strategy = results[0]
    
    # Create Bokeh plotter
    b = BacktraderBokeh(style='bar', scheme=Blackly())
    b.plot(strategy=strategy, show=True)  # Open in browser
    # Or save to file
    # b.plot(strategy=strategy, show=False, filename='chart.html')
    ''')
    
    cerebro = bt.Cerebro()
    
    # Load data
    data_path = os.path.join(os.path.dirname(__file__), '..', 'tests', 'datas', 'nvda-1999-2014.txt')
    if not os.path.exists(data_path):
        print(f"Data file does not exist: {data_path}")
        return
    
    data = bt.feeds.GenericCSVData(
        dataname=data_path,
        dtformat='%Y-%m-%d',
        datetime=0, open=1, high=2, low=3, close=4, volume=5, openinterest=-1,
        fromdate=datetime.datetime(2000, 1, 1),
        todate=datetime.datetime(2013, 6, 30),
    )
    cerebro.adddata(data, name='NVDA')
    cerebro.addstrategy(BokehSMAStrategy)
    cerebro.broker.setcash(100000)
    
    # Add analyzers to display performance metrics (using 0 as risk-free rate)
    cerebro.add_report_analyzers(riskfree_rate=0.0)
    
    print("Running strategy...")
    results = cerebro.run()
    
    # Set output directory
    output_dir = os.path.join(os.path.dirname(__file__), 'output')
    os.makedirs(output_dir, exist_ok=True)
    output_file_path = os.path.join(output_dir, 'bokeh_chart.html')
    
    try:
        from backtrader.bokeh import BacktraderBokeh, Blackly
        
        # Create Bokeh plotter
        b = BacktraderBokeh(
            style='bar',
            scheme=Blackly(),
        )
        
        # Plot and save (pass strategy instance, not results)
        strategy = results[0]
        b.plot(strategy=strategy, show=False, filename=output_file_path)
        print(f"✓ Bokeh chart saved to: {output_file_path}")
    except ImportError as e:
        print(f"⚠ Need to install bokeh: pip install bokeh")
        print(f"  Error: {e}")
    except Exception as e:
        print(f"\n⚠ Bokeh chart generation skipped: {e}")
        print("  Bokeh chart generation requires complete environment configuration")
        print("  The above theme, utility function, and tab examples ran successfully")


if __name__ == '__main__':
    print("=" * 60)
    print("Bokeh Interactive Chart Examples")
    print("=" * 60)
    
    # Run all examples
    example_schemes()
    example_utils()
    example_tabs()
    example_backtrader_bokeh()
    example_save_bokeh_html()  # Try to generate bokeh_chart.html
    
    print("\n" + "=" * 60)
    print("Examples completed!")
    print("Bokeh module features demonstrated:")
    print("  ✓ Theme configuration (Scheme, Blackly, Tradimo)")
    print("  ✓ Utility functions (sanitize_source_name)")
    print("  ✓ Tab system (BokehTab)")
    print("=" * 60)
