#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
"""
报告生成模块

提供回测报告生成功能，包括：
- PerformanceCalculator: 性能指标计算
- ReportChart: 报告专用图表生成
- ReportGenerator: 主报告生成器

使用示例:
    import backtrader as bt
    from backtrader.reports import ReportGenerator, PerformanceCalculator
    
    # 运行策略
    cerebro = bt.Cerebro()
    cerebro.addstrategy(MyStrategy)
    cerebro.adddata(data)
    results = cerebro.run()
    
    # 方式1：生成报告
    report = ReportGenerator(results[0])
    report.generate_html('report.html')
    report.generate_pdf('report.pdf')
    
    # 方式2：只获取指标
    calc = PerformanceCalculator(results[0])
    metrics = calc.get_all_metrics()
    print(metrics['sharpe_ratio'])
"""

from .performance import PerformanceCalculator
from .charts import ReportChart
from .reporter import ReportGenerator

__all__ = [
    'PerformanceCalculator',
    'ReportChart', 
    'ReportGenerator',
]
