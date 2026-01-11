#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
"""
Backtest report generation examples.

This example demonstrates how to use the report generation module:
1. One-click HTML report generation
2. Generate JSON report to export data
3. Use PerformanceCalculator to get performance metrics
4. Print performance summary

Usage:
    python examples/example_report_generation.py

Dependencies:
    pip install jinja2  # HTML reports
    pip install weasyprint  # PDF reports (optional)
"""

import datetime
import os
import sys

# Add project path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import backtrader as bt


class ReportSMAStrategy(bt.Strategy):
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


def example_quick_report():
    """Example 1: One-click report generation."""
    print("\n" + "=" * 60)
    print("Example 1: One-click HTML Report Generation")
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
    cerebro.addstrategy(ReportSMAStrategy)
    cerebro.broker.setcash(100000)
    
    # Add analyzers required for reports
    cerebro.add_report_analyzers()
    
    print("Running strategy...")
    cerebro.run()
    
    # One-click report generation
    output_dir = os.path.join(os.path.dirname(__file__), 'output')
    os.makedirs(output_dir, exist_ok=True)
    output_file = os.path.join(output_dir, 'backtest_report.html')
    cerebro.generate_report(
        output_file,
        format='html',
        user='Example User',
        memo='Dual Moving Average Crossover Strategy Backtest'
    )
    
    print(f"✓ HTML report generated: {output_file}")


def example_json_export():
    """Example 2: JSON data export."""
    print("\n" + "=" * 60)
    print("Example 2: JSON Data Export")
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
    cerebro.addstrategy(ReportSMAStrategy)
    cerebro.add_report_analyzers()
    
    cerebro.run()
    
    # Generate JSON report
    output_dir = os.path.join(os.path.dirname(__file__), 'output')
    os.makedirs(output_dir, exist_ok=True)
    output_file = os.path.join(output_dir, 'backtest_report.json')
    cerebro.generate_report(output_file, format='json')
    
    # Read and display partial content
    import json
    with open(output_file, 'r', encoding='utf-8') as f:
        report_data = json.load(f)
    
    print(f"\nJSON report structure:")
    for key in report_data.keys():
        print(f"  - {key}")
    
    print(f"\nStrategy information:")
    strategy = report_data.get('strategy', {})
    print(f"  Strategy name: {strategy.get('strategy_name')}")
    print(f"  Strategy params: {strategy.get('params')}")
    
    print(f"\n✓ JSON report generated: {output_file}")


def example_performance_calculator():
    """Example 3: Using PerformanceCalculator."""
    print("\n" + "=" * 60)
    print("Example 3: Using PerformanceCalculator to Get Performance Metrics")
    print("=" * 60)
    
    from backtrader.reports import PerformanceCalculator
    
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
    cerebro.addstrategy(ReportSMAStrategy)
    cerebro.broker.setcash(100000)
    cerebro.add_report_analyzers()
    
    results = cerebro.run()
    strategy = results[0]
    
    # Create performance calculator
    calc = PerformanceCalculator(strategy)
    
    # Get various metrics
    print("\nProfit & Loss Metrics (PnL):")
    pnl = calc.get_pnl_metrics()
    print(f"  Initial capital: ${pnl.get('start_cash', 0):,.2f}")
    print(f"  Final value: ${pnl.get('end_value', 0):,.2f}")
    print(f"  Net profit: ${pnl.get('net_profit', 0):,.2f}")
    print(f"  Total return: {pnl.get('total_return', 0):.2%}")
    
    print("\nRisk Metrics:")
    risk = calc.get_risk_metrics()
    print(f"  Max drawdown: {risk.get('max_pct_drawdown', 0):.2%}")
    print(f"  Sharpe ratio: {risk.get('sharpe_ratio', 'N/A')}")
    
    print("\nTrade Statistics:")
    trades = calc.get_trade_metrics()
    print(f"  Total trades: {trades.get('total_trades', 0)}")
    print(f"  Win rate: {trades.get('win_rate', 'N/A')}")
    
    print("\nSQN Rating:")
    kpi = calc.get_kpi_metrics()
    print(f"  SQN score: {kpi.get('sqn_score', 'N/A')}")
    print(f"  SQN rating: {kpi.get('sqn_human', 'N/A')}")
    
    print("\n✓ Performance metrics retrieval completed")


def example_print_summary():
    """Example 4: Print performance summary."""
    print("\n" + "=" * 60)
    print("Example 4: Print Performance Summary")
    print("=" * 60)
    
    from backtrader.reports import ReportGenerator
    
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
        todate=datetime.datetime(2010, 12, 31),
    )
    cerebro.adddata(data, name='NVDA')
    cerebro.addstrategy(ReportSMAStrategy)
    cerebro.broker.setcash(100000)
    cerebro.add_report_analyzers()
    
    results = cerebro.run()
    
    # Print summary
    report = ReportGenerator(results[0])
    report.print_summary()
    
    print("\n✓ Performance summary printing completed")


def example_sqn_rating():
    """Example 5: SQN rating explanation."""
    print("\n" + "=" * 60)
    print("Example 5: SQN Rating Explanation")
    print("=" * 60)
    
    from backtrader.reports import PerformanceCalculator
    
    print("\nSQN (System Quality Number) Rating Standards:")
    print("-" * 40)
    
    ratings = [
        (1.0, "Poor"),
        (1.7, "Below Average"),
        (2.0, "Average"),
        (2.5, "Good"),
        (3.5, "Excellent"),
        (6.0, "Superb"),
        (7.5, "Holy Grail"),
    ]
    
    for sqn, expected in ratings:
        actual = PerformanceCalculator.sqn_to_rating(sqn)
        print(f"  SQN = {sqn:.1f} -> {actual}")
    
    print("\nSQN Calculation Formula:")
    print("  SQN = sqrt(number_of_trades) * (average_profit / profit_std_dev)")
    print("\nRating Ranges:")
    print("  < 1.6:       Poor")
    print("  1.6 - 1.9:   Below Average")
    print("  1.9 - 2.4:   Average")
    print("  2.4 - 2.9:   Good")
    print("  2.9 - 5.0:   Excellent")
    print("  5.0 - 6.9:   Superb")
    print("  >= 7.0:      Holy Grail")
    
    print("\n✓ SQN rating explanation completed")


def example_pdf_report():
    """Example 6: Generate PDF report."""
    print("\n" + "=" * 60)
    print("Example 6: Generate PDF Report")
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
    cerebro.addstrategy(ReportSMAStrategy)
    cerebro.broker.setcash(100000)
    cerebro.add_report_analyzers()
    
    print("Running strategy...")
    cerebro.run()
    
    # Generate PDF report
    output_dir = os.path.join(os.path.dirname(__file__), 'output')
    os.makedirs(output_dir, exist_ok=True)
    output_file = os.path.join(output_dir, 'backtest_report.pdf')
    try:
        cerebro.generate_report(
            output_file,
            format='pdf',
            user='Example User',
            memo='Dual Moving Average Crossover Strategy Backtest - PDF Report'
        )
        print(f"✓ PDF report generated: {output_file}")
    except ImportError as e:
        print(f"⚠ PDF generation requires weasyprint: pip install weasyprint")
        print(f"  Error: {e}")
        print("  Note: weasyprint may require system-level dependencies (GTK, Pango, etc.)")
    except Exception as e:
        print(f"⚠ PDF generation failed: {e}")


if __name__ == '__main__':
    print("=" * 60)
    print("Backtest Report Generation Examples")
    print("=" * 60)
    
    # Run all examples
    example_sqn_rating()           # SQN rating explanation
    example_quick_report()         # Generate HTML report
    example_json_export()          # Generate JSON report
    example_performance_calculator()  # Performance metrics calculation
    example_print_summary()        # Print performance summary
    example_pdf_report()           # Generate PDF report
    
    print("\n" + "=" * 60)
    print("Examples completed!")
    output_dir = os.path.join(os.path.dirname(__file__), 'output')
    print(f"Generated files located at: {output_dir}")
    print("  - backtest_report.html")
    print("  - backtest_report.json")
    print("  - backtest_report.pdf")
    print("=" * 60)
