#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
"""
Report Generation Module Tests

Tests the report generation functionality added in iteration 44
"""

import sys
import os
import datetime
import tempfile

# Add project path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import backtrader as bt


class SMACrossStrategy(bt.Strategy):
    """Simple Moving Average Crossover Strategy"""
    
    params = (
        ('fast_period', 10),
        ('slow_period', 30),
    )
    
    def __init__(self):
        self.fast_sma = bt.indicators.SMA(period=self.p.fast_period)
        self.slow_sma = bt.indicators.SMA(period=self.p.slow_period)
        self.crossover = bt.indicators.CrossOver(self.fast_sma, self.slow_sma)
    
    def next(self):
        if not self.position:
            if self.crossover > 0:
                self.buy()
        elif self.crossover < 0:
            self.close()


def test_performance_calculator_import():
    """Test PerformanceCalculator import"""
    from backtrader.reports import PerformanceCalculator

    assert PerformanceCalculator is not None
    print("✓ PerformanceCalculator import test passed")


def test_report_chart_import():
    """Test ReportChart import"""
    from backtrader.reports import ReportChart

    assert ReportChart is not None
    chart = ReportChart()
    assert hasattr(chart, 'plot_equity_curve')
    assert hasattr(chart, 'plot_return_bars')
    assert hasattr(chart, 'plot_drawdown')
    print("✓ ReportChart import test passed")


def test_report_generator_import():
    """Test ReportGenerator import"""
    from backtrader.reports import ReportGenerator

    assert ReportGenerator is not None
    print("✓ ReportGenerator import test passed")


def test_sqn_to_rating():
    """Test SQN rating conversion"""
    from backtrader.reports import PerformanceCalculator

    # Test ratings at each level
    assert PerformanceCalculator.sqn_to_rating(1.0) == "Poor"
    assert PerformanceCalculator.sqn_to_rating(1.7) == "Below Average"
    assert PerformanceCalculator.sqn_to_rating(2.0) == "Average"
    assert PerformanceCalculator.sqn_to_rating(2.5) == "Good"
    assert PerformanceCalculator.sqn_to_rating(3.5) == "Excellent"
    assert PerformanceCalculator.sqn_to_rating(6.0) == "Superb"
    assert PerformanceCalculator.sqn_to_rating(7.5) == "Holy Grail"

    # Test None and NaN
    assert PerformanceCalculator.sqn_to_rating(None) == "N/A"

    import math
    assert PerformanceCalculator.sqn_to_rating(math.nan) == "N/A"

    print("✓ SQN rating conversion test passed")


def test_cerebro_add_report_analyzers():
    """Test Cerebro adding report analyzers"""
    cerebro = bt.Cerebro()

    # Add report analyzers
    cerebro.add_report_analyzers(riskfree_rate=0.02)

    # Check that analyzers have been added
    assert len(cerebro.analyzers) > 0

    print("✓ Cerebro add report analyzers test passed")


def test_integration_with_strategy():
    """Test integration with strategy"""
    from backtrader.reports import PerformanceCalculator, ReportGenerator

    # Create cerebro
    cerebro = bt.Cerebro()

    # Add data
    data_path = os.path.join(os.path.dirname(__file__), 'datas', 'nvda-1999-2014.txt')
    if not os.path.exists(data_path):
        print("⚠ Test data file does not exist, skipping integration test")
        return
    
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
        todate=datetime.datetime(2000, 12, 31),
    )
    cerebro.adddata(data)
    cerebro.addstrategy(SMACrossStrategy)

    # Add report analyzers
    cerebro.add_report_analyzers()

    # Run strategy
    results = cerebro.run()
    strategy = results[0]

    # Test PerformanceCalculator
    calc = PerformanceCalculator(strategy)

    # Test getting all metrics
    metrics = calc.get_all_metrics()
    assert isinstance(metrics, dict)
    assert 'start_cash' in metrics
    assert 'total_return' in metrics
    assert 'sharpe_ratio' in metrics

    print(f"  - Initial capital: {metrics.get('start_cash')}")
    print(f"  - Total return: {metrics.get('total_return', 'N/A')}")
    print(f"  - Sharpe ratio: {metrics.get('sharpe_ratio', 'N/A')}")

    # Test strategy information
    strategy_info = calc.get_strategy_info()
    assert strategy_info['strategy_name'] == 'SMACrossStrategy'

    # Test data information
    data_info = calc.get_data_info()
    assert data_info.get('bars', 0) > 0

    print("✓ Strategy integration test passed")


def test_html_report_generation():
    """Test HTML report generation"""
    from backtrader.reports import ReportGenerator

    # Create cerebro
    cerebro = bt.Cerebro()

    # Add data
    data_path = os.path.join(os.path.dirname(__file__), 'datas', 'nvda-1999-2014.txt')
    if not os.path.exists(data_path):
        print("⚠ Test data file does not exist, skipping HTML report test")
        return
    
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
        todate=datetime.datetime(2000, 6, 30),
    )
    cerebro.adddata(data)
    cerebro.addstrategy(SMACrossStrategy)
    cerebro.add_report_analyzers()
    
    results = cerebro.run()

    # Generate HTML report
    with tempfile.NamedTemporaryFile(suffix='.html', delete=False) as f:
        output_path = f.name

    try:
        report = ReportGenerator(results[0])
        report.generate_html(output_path, user='Test User', memo='Test memo')

        # Check that file was created
        assert os.path.exists(output_path)

        # Check file contents
        with open(output_path, 'r', encoding='utf-8') as f:
            content = f.read()
            assert 'SMACrossStrategy' in content
            assert 'Test User' in content
            assert 'Test memo' in content

        print("✓ HTML report generation test passed")
    finally:
        if os.path.exists(output_path):
            os.remove(output_path)


def test_json_report_generation():
    """Test JSON report generation"""
    from backtrader.reports import ReportGenerator
    import json

    # Create cerebro
    cerebro = bt.Cerebro()

    # Add data
    data_path = os.path.join(os.path.dirname(__file__), 'datas', 'nvda-1999-2014.txt')
    if not os.path.exists(data_path):
        print("⚠ Test data file does not exist, skipping JSON report test")
        return
    
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
        todate=datetime.datetime(2000, 6, 30),
    )
    cerebro.adddata(data)
    cerebro.addstrategy(SMACrossStrategy)
    cerebro.add_report_analyzers()
    
    results = cerebro.run()

    # Generate JSON report
    with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
        output_path = f.name

    try:
        report = ReportGenerator(results[0])
        report.generate_json(output_path)

        # Check that file was created
        assert os.path.exists(output_path)

        # Check JSON content
        with open(output_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            assert 'strategy' in data
            assert 'metrics' in data
            assert data['strategy']['strategy_name'] == 'SMACrossStrategy'

        print("✓ JSON report generation test passed")
    finally:
        if os.path.exists(output_path):
            os.remove(output_path)


def test_cerebro_generate_report():
    """Test Cerebro.generate_report() method"""
    # Create cerebro
    cerebro = bt.Cerebro()

    # Add data
    data_path = os.path.join(os.path.dirname(__file__), 'datas', 'nvda-1999-2014.txt')
    if not os.path.exists(data_path):
        print("⚠ Test data file does not exist, skipping Cerebro.generate_report test")
        return
    
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
        todate=datetime.datetime(2000, 6, 30),
    )
    cerebro.adddata(data)
    cerebro.addstrategy(SMACrossStrategy)
    cerebro.add_report_analyzers()
    
    cerebro.run()

    # Test report generation through Cerebro
    with tempfile.NamedTemporaryFile(suffix='.html', delete=False) as f:
        output_path = f.name

    try:
        cerebro.generate_report(output_path, format='html', user='Cerebro Test')

        assert os.path.exists(output_path)

        with open(output_path, 'r', encoding='utf-8') as f:
            content = f.read()
            assert 'SMACrossStrategy' in content

        print("✓ Cerebro.generate_report() test passed")
    finally:
        if os.path.exists(output_path):
            os.remove(output_path)


def test_print_summary():
    """Test printing summary"""
    from backtrader.reports import ReportGenerator

    # Create cerebro
    cerebro = bt.Cerebro()

    # Add data
    data_path = os.path.join(os.path.dirname(__file__), 'datas', 'nvda-1999-2014.txt')
    if not os.path.exists(data_path):
        print("⚠ Test data file does not exist, skipping print summary test")
        return
    
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
        todate=datetime.datetime(2000, 6, 30),
    )
    cerebro.adddata(data)
    cerebro.addstrategy(SMACrossStrategy)
    cerebro.add_report_analyzers()
    
    results = cerebro.run()

    # Print summary
    report = ReportGenerator(results[0])
    report.print_summary()

    print("✓ Print summary test passed")


def run_all_tests():
    """Run all tests"""
    print("=" * 60)
    print("Report Generation Module Tests")
    print("=" * 60)
    
    tests = [
        test_performance_calculator_import,
        test_report_chart_import,
        test_report_generator_import,
        test_sqn_to_rating,
        test_cerebro_add_report_analyzers,
        test_integration_with_strategy,
        test_html_report_generation,
        test_json_report_generation,
        test_cerebro_generate_report,
        test_print_summary,
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
    print(f"Test completed: {passed} passed, {failed} failed")
    print("=" * 60)
    
    return failed == 0


if __name__ == '__main__':
    success = run_all_tests()
    sys.exit(0 if success else 1)
