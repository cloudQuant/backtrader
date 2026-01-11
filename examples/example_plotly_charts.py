#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
"""
Plotly interactive chart examples.

This example demonstrates how to use the Plotly backend for high-performance interactive charts:
1. Basic usage - using cerebro.plot(backend='plotly')
2. Custom color schemes - Tableau10/Tableau20, etc.
3. Custom decimal places and legend width
4. Save as HTML file

Usage:
    python examples/example_plotly_charts.py
"""

import datetime
import os
import sys

# Add project path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import backtrader as bt


class PlotlySMAStrategy(bt.Strategy):
    """Dual moving average crossover strategy."""
    params = (('fast_period', 10), ('slow_period', 30),)
    
    def __init__(self):
        """Initialize strategy."""
        self.sma_fast = bt.indicators.SMA(self.data.close, period=self.p.fast_period)
        self.sma_slow = bt.indicators.SMA(self.data.close, period=self.p.slow_period)
        self.crossover = bt.indicators.CrossOver(self.sma_fast, self.sma_slow)
        self.rsi = bt.indicators.RSI(self.data.close, period=14)
    
    def next(self):
        """Execute strategy logic on each bar."""
        if not self.position:
            if self.crossover > 0:
                self.buy()
        elif self.crossover < 0:
            self.close()


def example_basic_plotly():
    """Example 1: Basic Plotly plotting."""
    print("\n" + "=" * 60)
    print("Example 1: Basic Plotly Plotting")
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
        fromdate=datetime.datetime(2010, 1, 1),
        todate=datetime.datetime(2010, 6, 30),
    )
    cerebro.adddata(data, name='NVDA')
    cerebro.addstrategy(SMACrossStrategy)
    cerebro.broker.setcash(100000)
    
    print("Running strategy...")
    cerebro.run()
    
    # Plot using Plotly backend
    print("Plotting with Plotly backend...")
    cerebro.plot(backend='plotly', style='candle')
    print("✓ Basic Plotly plotting completed")


def example_custom_scheme():
    """Example 2: Custom color scheme."""
    print("\n" + "=" * 60)
    print("Example 2: Custom Color Scheme")
    print("=" * 60)
    
    from backtrader.plot.plot_plotly import PlotlyPlot, PlotlyScheme
    
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
    cerebro.addstrategy(SMACrossStrategy)
    
    results = cerebro.run()
    
    # Create custom color scheme
    scheme = PlotlyScheme(
        decimal_places=2,           # Display price with 2 decimal places
        max_legend_text_width=20,   # Maximum legend width
        color_scheme='tableau20',   # Use Tableau20 color scheme
        fillalpha=0.3,              # Fill transparency
    )
    
    # Plot with custom scheme
    plotter = PlotlyPlot(scheme=scheme, style='candle')
    figs = plotter.plot(results[0])
    
    # Save as HTML
    output_file = 'plotly_custom_scheme.html'
    figs[0].write_html(output_file)
    print(f"✓ Custom color chart saved to: {output_file}")


def example_save_html():
    """Example 3: Save as HTML file."""
    print("\n" + "=" * 60)
    print("Example 3: Save as HTML File")
    print("=" * 60)
    
    from backtrader.plot.plot_plotly import PlotlyPlot
    
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
    cerebro.addstrategy(PlotlySMAStrategy)
    
    results = cerebro.run()
    
    # Create plotter and plot
    plotter = PlotlyPlot(style='candle', decimal_places=2)
    figs = plotter.plot(results[0])
    
    # Save as standalone HTML file
    output_file = os.path.join(os.path.dirname(__file__), 'output', 'plotly_chart.html')
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    figs[0].write_html(output_file, include_plotlyjs=True)
    print(f"✓ Chart saved to: {output_file}")
    print("  Can be opened in browser to view interactive chart")


def example_color_schemes():
    """Example 4: Display different color schemes."""
    print("\n" + "=" * 60)
    print("Example 4: Display Different Color Schemes")
    print("=" * 60)
    
    from backtrader.plot.plot_plotly import (
        TABLEAU10, TABLEAU20, TABLEAU10_LIGHT, get_color_scheme
    )
    
    print("\nTableau10 color scheme (10 colors):")
    for i, color in enumerate(TABLEAU10):
        print(f"  {i}: {color}")
    
    print("\nTableau20 color scheme (20 colors):")
    for i, color in enumerate(TABLEAU20[:10]):
        print(f"  {i}: {color}")
    print("  ... (20 colors total)")
    
    print("\nTableau10 Light color scheme (10 light colors):")
    for i, color in enumerate(TABLEAU10_LIGHT[:5]):
        print(f"  {i}: {color}")
    print("  ... (10 colors total)")
    
    # Test getting color schemes
    print("\nUsing get_color_scheme() to get colors:")
    print(f"  get_color_scheme('tableau10'): {len(get_color_scheme('tableau10'))} colors")
    print(f"  get_color_scheme('tableau20'): {len(get_color_scheme('tableau20'))} colors")


if __name__ == '__main__':
    print("=" * 60)
    print("Plotly Interactive Chart Examples")
    print("=" * 60)
    
    # Run all examples
    example_color_schemes()
    example_save_html()  # Generate plotly_chart.html file
    
    print("\n" + "=" * 60)
    print("Examples completed!")
    output_dir = os.path.join(os.path.dirname(__file__), 'output')
    print(f"Generated files located at: {output_dir}")
    print("  - plotly_chart.html")
    print("=" * 60)
