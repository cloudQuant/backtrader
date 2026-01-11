#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
"""
Report generation module.

Provides backtest report generation functionality, including:
- PerformanceCalculator: Performance metrics calculation
- ReportChart: Report-specific chart generation
- ReportGenerator: Main report generator

Usage example:
    import backtrader as bt
    from backtrader.reports import ReportGenerator, PerformanceCalculator

    # Run strategy
    cerebro = bt.Cerebro()
    cerebro.addstrategy(MyStrategy)
    cerebro.adddata(data)
    results = cerebro.run()

    # Method 1: Generate report
    report = ReportGenerator(results[0])
    report.generate_html('report.html')
    report.generate_pdf('report.pdf')

    # Method 2: Get metrics only
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
