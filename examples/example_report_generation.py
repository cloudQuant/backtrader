#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
"""
回测报告生成示例

本示例展示如何使用报告生成模块：
1. 一键生成 HTML 报告
2. 生成 JSON 报告导出数据
3. 使用 PerformanceCalculator 获取性能指标
4. 打印性能摘要

运行方式：
    python examples/example_report_generation.py

依赖：
    pip install jinja2  # HTML 报告
    pip install weasyprint  # PDF 报告 (可选)
"""

import datetime
import os
import sys

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import backtrader as bt


class ReportSMAStrategy(bt.Strategy):
    """双均线交叉策略"""
    params = (('fast_period', 10), ('slow_period', 30),)
    
    def __init__(self):
        self.sma_fast = bt.indicators.SMA(self.data.close, period=self.p.fast_period)
        self.sma_slow = bt.indicators.SMA(self.data.close, period=self.p.slow_period)
        self.crossover = bt.indicators.CrossOver(self.sma_fast, self.sma_slow)
    
    def next(self):
        if not self.position:
            if self.crossover > 0:
                self.buy()
        elif self.crossover < 0:
            self.close()


def example_quick_report():
    """示例1: 一键生成报告"""
    print("\n" + "=" * 60)
    print("示例1: 一键生成 HTML 报告")
    print("=" * 60)
    
    cerebro = bt.Cerebro()
    
    # 加载数据
    data_path = os.path.join(os.path.dirname(__file__), '..', 'tests', 'datas', 'nvda-1999-2014.txt')
    if not os.path.exists(data_path):
        print(f"数据文件不存在: {data_path}")
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
    
    # 添加报告所需的分析器
    cerebro.add_report_analyzers()
    
    print("运行策略...")
    cerebro.run()
    
    # 一键生成报告
    output_dir = os.path.join(os.path.dirname(__file__), 'output')
    os.makedirs(output_dir, exist_ok=True)
    output_file = os.path.join(output_dir, 'backtest_report.html')
    cerebro.generate_report(
        output_file,
        format='html',
        user='示例用户',
        memo='双均线交叉策略回测'
    )
    
    print(f"✓ HTML 报告已生成: {output_file}")


def example_json_export():
    """示例2: JSON 数据导出"""
    print("\n" + "=" * 60)
    print("示例2: JSON 数据导出")
    print("=" * 60)
    
    cerebro = bt.Cerebro()
    
    # 加载数据
    data_path = os.path.join(os.path.dirname(__file__), '..', 'tests', 'datas', 'nvda-1999-2014.txt')
    if not os.path.exists(data_path):
        print(f"数据文件不存在: {data_path}")
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
    
    # 生成 JSON 报告
    output_dir = os.path.join(os.path.dirname(__file__), 'output')
    os.makedirs(output_dir, exist_ok=True)
    output_file = os.path.join(output_dir, 'backtest_report.json')
    cerebro.generate_report(output_file, format='json')
    
    # 读取并显示部分内容
    import json
    with open(output_file, 'r', encoding='utf-8') as f:
        report_data = json.load(f)
    
    print(f"\nJSON 报告结构:")
    for key in report_data.keys():
        print(f"  - {key}")
    
    print(f"\n策略信息:")
    strategy = report_data.get('strategy', {})
    print(f"  策略名称: {strategy.get('strategy_name')}")
    print(f"  策略参数: {strategy.get('params')}")
    
    print(f"\n✓ JSON 报告已生成: {output_file}")


def example_performance_calculator():
    """示例3: 使用 PerformanceCalculator"""
    print("\n" + "=" * 60)
    print("示例3: 使用 PerformanceCalculator 获取性能指标")
    print("=" * 60)
    
    from backtrader.reports import PerformanceCalculator
    
    cerebro = bt.Cerebro()
    
    # 加载数据
    data_path = os.path.join(os.path.dirname(__file__), '..', 'tests', 'datas', 'nvda-1999-2014.txt')
    if not os.path.exists(data_path):
        print(f"数据文件不存在: {data_path}")
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
    
    # 创建性能计算器
    calc = PerformanceCalculator(strategy)
    
    # 获取各类指标
    print("\n收益指标 (PnL):")
    pnl = calc.get_pnl_metrics()
    print(f"  初始资金: ${pnl.get('start_cash', 0):,.2f}")
    print(f"  最终价值: ${pnl.get('end_value', 0):,.2f}")
    print(f"  净利润: ${pnl.get('net_profit', 0):,.2f}")
    print(f"  总收益率: {pnl.get('total_return', 0):.2%}")
    
    print("\n风险指标:")
    risk = calc.get_risk_metrics()
    print(f"  最大回撤: {risk.get('max_pct_drawdown', 0):.2%}")
    print(f"  夏普比率: {risk.get('sharpe_ratio', 'N/A')}")
    
    print("\n交易统计:")
    trades = calc.get_trade_metrics()
    print(f"  交易总数: {trades.get('total_trades', 0)}")
    print(f"  胜率: {trades.get('win_rate', 'N/A')}")
    
    print("\nSQN 评级:")
    kpi = calc.get_kpi_metrics()
    print(f"  SQN 分数: {kpi.get('sqn_score', 'N/A')}")
    print(f"  SQN 评级: {kpi.get('sqn_human', 'N/A')}")
    
    print("\n✓ 性能指标获取完成")


def example_print_summary():
    """示例4: 打印性能摘要"""
    print("\n" + "=" * 60)
    print("示例4: 打印性能摘要")
    print("=" * 60)
    
    from backtrader.reports import ReportGenerator
    
    cerebro = bt.Cerebro()
    
    # 加载数据
    data_path = os.path.join(os.path.dirname(__file__), '..', 'tests', 'datas', 'nvda-1999-2014.txt')
    if not os.path.exists(data_path):
        print(f"数据文件不存在: {data_path}")
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
    
    # 打印摘要
    report = ReportGenerator(results[0])
    report.print_summary()
    
    print("\n✓ 性能摘要打印完成")


def example_sqn_rating():
    """示例5: SQN 评级说明"""
    print("\n" + "=" * 60)
    print("示例5: SQN 评级说明")
    print("=" * 60)
    
    from backtrader.reports import PerformanceCalculator
    
    print("\nSQN (System Quality Number) 评级标准:")
    print("-" * 40)
    
    ratings = [
        (1.0, "Poor (差)"),
        (1.7, "Below Average (低于平均)"),
        (2.0, "Average (平均)"),
        (2.5, "Good (良好)"),
        (3.5, "Excellent (优秀)"),
        (6.0, "Superb (卓越)"),
        (7.5, "Holy Grail (圣杯)"),
    ]
    
    for sqn, expected in ratings:
        actual = PerformanceCalculator.sqn_to_rating(sqn)
        print(f"  SQN = {sqn:.1f} -> {actual}")
    
    print("\nSQN 计算公式:")
    print("  SQN = sqrt(交易次数) * (平均收益 / 收益标准差)")
    print("\n评级范围:")
    print("  < 1.6:       Poor")
    print("  1.6 - 1.9:   Below Average")
    print("  1.9 - 2.4:   Average")
    print("  2.4 - 2.9:   Good")
    print("  2.9 - 5.0:   Excellent")
    print("  5.0 - 6.9:   Superb")
    print("  >= 7.0:      Holy Grail")
    
    print("\n✓ SQN 评级说明完成")


def example_pdf_report():
    """示例6: 生成 PDF 报告"""
    print("\n" + "=" * 60)
    print("示例6: 生成 PDF 报告")
    print("=" * 60)
    
    cerebro = bt.Cerebro()
    
    # 加载数据
    data_path = os.path.join(os.path.dirname(__file__), '..', 'tests', 'datas', 'nvda-1999-2014.txt')
    if not os.path.exists(data_path):
        print(f"数据文件不存在: {data_path}")
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
    
    print("运行策略...")
    cerebro.run()
    
    # 生成 PDF 报告
    output_dir = os.path.join(os.path.dirname(__file__), 'output')
    os.makedirs(output_dir, exist_ok=True)
    output_file = os.path.join(output_dir, 'backtest_report.pdf')
    try:
        cerebro.generate_report(
            output_file,
            format='pdf',
            user='示例用户',
            memo='双均线交叉策略回测 - PDF报告'
        )
        print(f"✓ PDF 报告已生成: {output_file}")
    except ImportError as e:
        print(f"⚠ PDF 生成需要 weasyprint: pip install weasyprint")
        print(f"  错误: {e}")
        print("  提示: weasyprint 可能需要系统级依赖 (GTK, Pango 等)")
    except Exception as e:
        print(f"⚠ PDF 生成失败: {e}")


if __name__ == '__main__':
    print("=" * 60)
    print("回测报告生成示例")
    print("=" * 60)
    
    # 运行所有示例
    example_sqn_rating()           # SQN 评级说明
    example_quick_report()         # 生成 HTML 报告
    example_json_export()          # 生成 JSON 报告
    example_performance_calculator()  # 性能指标计算
    example_print_summary()        # 打印性能摘要
    example_pdf_report()           # 生成 PDF 报告
    
    print("\n" + "=" * 60)
    print("示例运行完成！")
    output_dir = os.path.join(os.path.dirname(__file__), 'output')
    print(f"生成的文件位于: {output_dir}")
    print("  - backtest_report.html")
    print("  - backtest_report.json")
    print("  - backtest_report.pdf")
    print("=" * 60)
