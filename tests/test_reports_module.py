#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
"""
报告生成模块测试

测试迭代44中添加的报告生成功能
"""

import sys
import os
import datetime
import tempfile

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import backtrader as bt


class SMACrossStrategy(bt.Strategy):
    """简单移动平均线交叉策略"""
    
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
    """测试 PerformanceCalculator 导入"""
    from backtrader.reports import PerformanceCalculator
    
    assert PerformanceCalculator is not None
    print("✓ PerformanceCalculator 导入测试通过")


def test_report_chart_import():
    """测试 ReportChart 导入"""
    from backtrader.reports import ReportChart
    
    assert ReportChart is not None
    chart = ReportChart()
    assert hasattr(chart, 'plot_equity_curve')
    assert hasattr(chart, 'plot_return_bars')
    assert hasattr(chart, 'plot_drawdown')
    print("✓ ReportChart 导入测试通过")


def test_report_generator_import():
    """测试 ReportGenerator 导入"""
    from backtrader.reports import ReportGenerator
    
    assert ReportGenerator is not None
    print("✓ ReportGenerator 导入测试通过")


def test_sqn_to_rating():
    """测试 SQN 评级转换"""
    from backtrader.reports import PerformanceCalculator
    
    # 测试各级别评级
    assert PerformanceCalculator.sqn_to_rating(1.0) == "Poor"
    assert PerformanceCalculator.sqn_to_rating(1.7) == "Below Average"
    assert PerformanceCalculator.sqn_to_rating(2.0) == "Average"
    assert PerformanceCalculator.sqn_to_rating(2.5) == "Good"
    assert PerformanceCalculator.sqn_to_rating(3.5) == "Excellent"
    assert PerformanceCalculator.sqn_to_rating(6.0) == "Superb"
    assert PerformanceCalculator.sqn_to_rating(7.5) == "Holy Grail"
    
    # 测试 None 和 NaN
    assert PerformanceCalculator.sqn_to_rating(None) == "N/A"
    
    import math
    assert PerformanceCalculator.sqn_to_rating(math.nan) == "N/A"
    
    print("✓ SQN 评级转换测试通过")


def test_cerebro_add_report_analyzers():
    """测试 Cerebro 添加报告分析器"""
    cerebro = bt.Cerebro()
    
    # 添加报告分析器
    cerebro.add_report_analyzers(riskfree_rate=0.02)
    
    # 检查分析器已添加
    assert len(cerebro.analyzers) > 0
    
    print("✓ Cerebro 添加报告分析器测试通过")


def test_integration_with_strategy():
    """测试与策略的集成"""
    from backtrader.reports import PerformanceCalculator, ReportGenerator
    
    # 创建 cerebro
    cerebro = bt.Cerebro()
    
    # 添加数据
    data_path = os.path.join(os.path.dirname(__file__), 'datas', 'nvda-1999-2014.txt')
    if not os.path.exists(data_path):
        print("⚠ 测试数据文件不存在，跳过集成测试")
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
    
    # 添加报告分析器
    cerebro.add_report_analyzers()
    
    # 运行策略
    results = cerebro.run()
    strategy = results[0]
    
    # 测试 PerformanceCalculator
    calc = PerformanceCalculator(strategy)
    
    # 测试获取所有指标
    metrics = calc.get_all_metrics()
    assert isinstance(metrics, dict)
    assert 'start_cash' in metrics
    assert 'total_return' in metrics
    assert 'sharpe_ratio' in metrics
    
    print(f"  - 初始资金: {metrics.get('start_cash')}")
    print(f"  - 总收益率: {metrics.get('total_return', 'N/A')}")
    print(f"  - 夏普比率: {metrics.get('sharpe_ratio', 'N/A')}")
    
    # 测试策略信息
    strategy_info = calc.get_strategy_info()
    assert strategy_info['strategy_name'] == 'SMACrossStrategy'
    
    # 测试数据信息
    data_info = calc.get_data_info()
    assert data_info.get('bars', 0) > 0
    
    print("✓ 策略集成测试通过")


def test_html_report_generation():
    """测试 HTML 报告生成"""
    from backtrader.reports import ReportGenerator
    
    # 创建 cerebro
    cerebro = bt.Cerebro()
    
    # 添加数据
    data_path = os.path.join(os.path.dirname(__file__), 'datas', 'nvda-1999-2014.txt')
    if not os.path.exists(data_path):
        print("⚠ 测试数据文件不存在，跳过 HTML 报告测试")
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
    
    # 生成 HTML 报告
    with tempfile.NamedTemporaryFile(suffix='.html', delete=False) as f:
        output_path = f.name
    
    try:
        report = ReportGenerator(results[0])
        report.generate_html(output_path, user='Test User', memo='Test memo')
        
        # 检查文件已创建
        assert os.path.exists(output_path)
        
        # 检查文件内容
        with open(output_path, 'r', encoding='utf-8') as f:
            content = f.read()
            assert 'SMACrossStrategy' in content
            assert 'Test User' in content
            assert 'Test memo' in content
        
        print("✓ HTML 报告生成测试通过")
    finally:
        if os.path.exists(output_path):
            os.remove(output_path)


def test_json_report_generation():
    """测试 JSON 报告生成"""
    from backtrader.reports import ReportGenerator
    import json
    
    # 创建 cerebro
    cerebro = bt.Cerebro()
    
    # 添加数据
    data_path = os.path.join(os.path.dirname(__file__), 'datas', 'nvda-1999-2014.txt')
    if not os.path.exists(data_path):
        print("⚠ 测试数据文件不存在，跳过 JSON 报告测试")
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
    
    # 生成 JSON 报告
    with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
        output_path = f.name
    
    try:
        report = ReportGenerator(results[0])
        report.generate_json(output_path)
        
        # 检查文件已创建
        assert os.path.exists(output_path)
        
        # 检查 JSON 内容
        with open(output_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            assert 'strategy' in data
            assert 'metrics' in data
            assert data['strategy']['strategy_name'] == 'SMACrossStrategy'
        
        print("✓ JSON 报告生成测试通过")
    finally:
        if os.path.exists(output_path):
            os.remove(output_path)


def test_cerebro_generate_report():
    """测试 Cerebro.generate_report() 方法"""
    # 创建 cerebro
    cerebro = bt.Cerebro()
    
    # 添加数据
    data_path = os.path.join(os.path.dirname(__file__), 'datas', 'nvda-1999-2014.txt')
    if not os.path.exists(data_path):
        print("⚠ 测试数据文件不存在，跳过 Cerebro.generate_report 测试")
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
    
    # 测试通过 Cerebro 生成报告
    with tempfile.NamedTemporaryFile(suffix='.html', delete=False) as f:
        output_path = f.name
    
    try:
        cerebro.generate_report(output_path, format='html', user='Cerebro Test')
        
        assert os.path.exists(output_path)
        
        with open(output_path, 'r', encoding='utf-8') as f:
            content = f.read()
            assert 'SMACrossStrategy' in content
        
        print("✓ Cerebro.generate_report() 测试通过")
    finally:
        if os.path.exists(output_path):
            os.remove(output_path)


def test_print_summary():
    """测试打印摘要"""
    from backtrader.reports import ReportGenerator
    
    # 创建 cerebro
    cerebro = bt.Cerebro()
    
    # 添加数据
    data_path = os.path.join(os.path.dirname(__file__), 'datas', 'nvda-1999-2014.txt')
    if not os.path.exists(data_path):
        print("⚠ 测试数据文件不存在，跳过打印摘要测试")
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
    
    # 打印摘要
    report = ReportGenerator(results[0])
    report.print_summary()
    
    print("✓ 打印摘要测试通过")


def run_all_tests():
    """运行所有测试"""
    print("=" * 60)
    print("报告生成模块测试")
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
            print(f"✗ 测试失败: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    
    print("\n" + "=" * 60)
    print(f"测试完成: {passed} 通过, {failed} 失败")
    print("=" * 60)
    
    return failed == 0


if __name__ == '__main__':
    success = run_all_tests()
    sys.exit(0 if success else 1)
