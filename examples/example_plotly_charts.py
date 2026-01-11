#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
"""
Plotly 交互式图表示例

本示例展示如何使用 Plotly 后端绑制高性能交互式图表：
1. 基本用法 - 使用 cerebro.plot(backend='plotly')
2. 自定义配色方案 - Tableau10/Tableau20 等
3. 自定义小数位数和图例宽度
4. 保存为 HTML 文件

运行方式：
    python examples/example_plotly_charts.py
"""

import datetime
import os
import sys

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import backtrader as bt


class PlotlySMAStrategy(bt.Strategy):
    """双均线交叉策略"""
    params = (('fast_period', 10), ('slow_period', 30),)
    
    def __init__(self):
        self.sma_fast = bt.indicators.SMA(self.data.close, period=self.p.fast_period)
        self.sma_slow = bt.indicators.SMA(self.data.close, period=self.p.slow_period)
        self.crossover = bt.indicators.CrossOver(self.sma_fast, self.sma_slow)
        self.rsi = bt.indicators.RSI(self.data.close, period=14)
    
    def next(self):
        if not self.position:
            if self.crossover > 0:
                self.buy()
        elif self.crossover < 0:
            self.close()


def example_basic_plotly():
    """示例1: 基本 Plotly 绑图"""
    print("\n" + "=" * 60)
    print("示例1: 基本 Plotly 绑图")
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
        fromdate=datetime.datetime(2010, 1, 1),
        todate=datetime.datetime(2010, 6, 30),
    )
    cerebro.adddata(data, name='NVDA')
    cerebro.addstrategy(SMACrossStrategy)
    cerebro.broker.setcash(100000)
    
    print("运行策略...")
    cerebro.run()
    
    # 使用 Plotly 后端绑图
    print("使用 Plotly 后端绑图...")
    cerebro.plot(backend='plotly', style='candle')
    print("✓ 基本 Plotly 绑图完成")


def example_custom_scheme():
    """示例2: 自定义配色方案"""
    print("\n" + "=" * 60)
    print("示例2: 自定义配色方案")
    print("=" * 60)
    
    from backtrader.plot.plot_plotly import PlotlyPlot, PlotlyScheme
    
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
    cerebro.addstrategy(SMACrossStrategy)
    
    results = cerebro.run()
    
    # 创建自定义配色方案
    scheme = PlotlyScheme(
        decimal_places=2,           # 价格显示2位小数
        max_legend_text_width=20,   # 图例最大宽度
        color_scheme='tableau20',   # 使用 Tableau20 配色
        fillalpha=0.3,              # 填充透明度
    )
    
    # 使用自定义方案绑图
    plotter = PlotlyPlot(scheme=scheme, style='candle')
    figs = plotter.plot(results[0])
    
    # 保存为 HTML
    output_file = 'plotly_custom_scheme.html'
    figs[0].write_html(output_file)
    print(f"✓ 自定义配色图表已保存到: {output_file}")


def example_save_html():
    """示例3: 保存为 HTML 文件"""
    print("\n" + "=" * 60)
    print("示例3: 保存为 HTML 文件")
    print("=" * 60)
    
    from backtrader.plot.plot_plotly import PlotlyPlot
    
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
    cerebro.addstrategy(PlotlySMAStrategy)
    
    results = cerebro.run()
    
    # 创建绑图器并绑图
    plotter = PlotlyPlot(style='candle', decimal_places=2)
    figs = plotter.plot(results[0])
    
    # 保存为独立 HTML 文件
    output_file = os.path.join(os.path.dirname(__file__), 'output', 'plotly_chart.html')
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    figs[0].write_html(output_file, include_plotlyjs=True)
    print(f"✓ 图表已保存到: {output_file}")
    print("  可以用浏览器打开查看交互式图表")


def example_color_schemes():
    """示例4: 展示不同配色方案"""
    print("\n" + "=" * 60)
    print("示例4: 展示不同配色方案")
    print("=" * 60)
    
    from backtrader.plot.plot_plotly import (
        TABLEAU10, TABLEAU20, TABLEAU10_LIGHT, get_color_scheme
    )
    
    print("\nTableau10 配色方案 (10色):")
    for i, color in enumerate(TABLEAU10):
        print(f"  {i}: {color}")
    
    print("\nTableau20 配色方案 (20色):")
    for i, color in enumerate(TABLEAU20[:10]):
        print(f"  {i}: {color}")
    print("  ... (共20色)")
    
    print("\nTableau10 Light 配色方案 (10色浅色):")
    for i, color in enumerate(TABLEAU10_LIGHT[:5]):
        print(f"  {i}: {color}")
    print("  ... (共10色)")
    
    # 测试获取配色方案
    print("\n使用 get_color_scheme() 获取配色:")
    print(f"  get_color_scheme('tableau10'): {len(get_color_scheme('tableau10'))} 色")
    print(f"  get_color_scheme('tableau20'): {len(get_color_scheme('tableau20'))} 色")


if __name__ == '__main__':
    print("=" * 60)
    print("Plotly 交互式图表示例")
    print("=" * 60)
    
    # 运行所有示例
    example_color_schemes()
    example_save_html()  # 生成 plotly_chart.html 文件
    
    print("\n" + "=" * 60)
    print("示例运行完成！")
    output_dir = os.path.join(os.path.dirname(__file__), 'output')
    print(f"生成的文件位于: {output_dir}")
    print("  - plotly_chart.html")
    print("=" * 60)
