#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
"""
Bokeh 交互式图表示例

本示例展示如何使用 Bokeh 模块进行交互式可视化：
1. 使用不同主题 - Scheme, Blackly, Tradimo
2. 使用 RecorderAnalyzer 记录数据
3. 自定义标签页

运行方式：
    python examples/example_bokeh_charts.py

依赖：
    pip install bokeh
"""

import datetime
import os
import sys

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import backtrader as bt


class BokehSMAStrategy(bt.Strategy):
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


def example_schemes():
    """示例1: 展示不同主题"""
    print("\n" + "=" * 60)
    print("示例1: Bokeh 主题展示")
    print("=" * 60)
    
    from backtrader.bokeh import Scheme, Blackly, Tradimo
    
    # 默认主题
    scheme = Scheme()
    print("\n默认主题 (Scheme):")
    print(f"  背景色: {scheme.background_fill}")
    print(f"  上涨颜色: {scheme.barup}")
    print(f"  下跌颜色: {scheme.bardown}")
    
    # 黑色主题
    blackly = Blackly()
    print("\n黑色主题 (Blackly):")
    print(f"  背景色: {blackly.background_fill}")
    print(f"  上涨颜色: {blackly.barup}")
    print(f"  下跌颜色: {blackly.bardown}")
    
    # 白色主题
    tradimo = Tradimo()
    print("\n白色主题 (Tradimo):")
    print(f"  背景色: {tradimo.background_fill}")
    print(f"  上涨颜色: {tradimo.barup}")
    print(f"  下跌颜色: {tradimo.bardown}")
    
    print("\n✓ 主题展示完成")


def example_utils():
    """示例2: 工具函数"""
    print("\n" + "=" * 60)
    print("示例2: Bokeh 工具函数")
    print("=" * 60)
    
    from backtrader.bokeh import sanitize_source_name
    
    # 测试名称清理
    print("\n名称清理 (sanitize_source_name):")
    print(f"  'test' -> '{sanitize_source_name('test')}'")
    print(f"  'test-data' -> '{sanitize_source_name('test-data')}'")
    print(f"  '123test' -> '{sanitize_source_name('123test')}'")
    print(f"  'my.data.name' -> '{sanitize_source_name('my.data.name')}'")
    
    print("\n✓ 工具函数演示完成")


def example_tabs():
    """示例3: 标签页系统"""
    print("\n" + "=" * 60)
    print("示例3: Bokeh 标签页系统")
    print("=" * 60)
    
    from backtrader.bokeh import BokehTab, tabs, register_tab, get_registered_tabs
    
    print("\n内置标签页类型:")
    tab_types = ['AnalyzerTab', 'ConfigTab', 'LogTab', 'MetadataTab', 'SourceTab', 'LiveTab']
    for tab_type in tab_types:
        if hasattr(tabs, tab_type):
            print(f"  ✓ {tab_type}")
    
    # 展示已注册的标签页
    registered = get_registered_tabs()
    print(f"\n已注册标签页数量: {len(registered)}")
    
    # 演示自定义标签页
    print("\n自定义标签页示例:")
    print("""
    from backtrader.bokeh import BokehTab, register_tab
    
    class CustomTab(BokehTab):
        def _is_useable(self):
            return True
        
        def _get_panel(self):
            # 返回 (panel, title) 元组
            return None, 'Custom Tab'
    
    # 注册自定义标签页
    register_tab(CustomTab)
    """)
    
    print("✓ 标签页系统演示完成")


def example_recorder_analyzer():
    """示例4: RecorderAnalyzer 使用"""
    print("\n" + "=" * 60)
    print("示例4: RecorderAnalyzer 数据记录")
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
    cerebro.addstrategy(BokehSMAStrategy)
    
    # 添加 RecorderAnalyzer
    try:
        from backtrader.bokeh import RecorderAnalyzer
        cerebro.addanalyzer(RecorderAnalyzer, indicators=True)
        
        print("运行策略...")
        results = cerebro.run()
        
        # 获取记录的数据
        recorder = results[0].analyzers.recorderanalyzer
        analysis = recorder.get_analysis()
        
        print("\n记录的数据键:")
        for key in analysis.keys():
            print(f"  - {key}")
        
        if 'data' in analysis:
            data_records = analysis['data']
            print(f"\n记录的数据条数: {len(data_records) if isinstance(data_records, list) else 'N/A'}")
        
        print("\n✓ RecorderAnalyzer 演示完成")
    except ImportError as e:
        print(f"⚠ 需要安装 bokeh: pip install bokeh")
        print(f"  错误: {e}")


def example_backtrader_bokeh():
    """示例5: BacktraderBokeh 完整使用"""
    print("\n" + "=" * 60)
    print("示例5: BacktraderBokeh 完整使用")
    print("=" * 60)
    
    print("""
使用 BacktraderBokeh 的完整示例代码：

    import backtrader as bt
    from backtrader.bokeh import BacktraderBokeh, Blackly
    
    # 创建策略
    cerebro = bt.Cerebro()
    cerebro.adddata(data)
    cerebro.addstrategy(MyStrategy)
    
    # 运行策略
    results = cerebro.run()
    
    # 使用 BacktraderBokeh 可视化
    b = BacktraderBokeh(
        style='bar',           # 图表样式: 'bar', 'line', 'candle'
        scheme=Blackly(),      # 使用黑色主题
        output_mode='show',    # 'show' 显示, 'save' 保存, 'memory' 内存
    )
    
    # 绑图
    b.plot(results)
    
注意事项：
1. 需要安装 bokeh: pip install bokeh
2. output_mode='show' 会在浏览器中打开
3. 可以自定义主题颜色
    """)
    
    print("✓ BacktraderBokeh 使用说明完成")


def example_save_bokeh_html():
    """示例6: 保存 Bokeh 图表为 HTML (可选)"""
    print("\n" + "=" * 60)
    print("示例6: 保存 Bokeh 图表为 HTML")
    print("=" * 60)
    print("\n注意: BacktraderBokeh 图表生成需要完整的 Bokeh 配置")
    print("如果出现错误，请参考以下代码在您的项目中使用：")
    print('''
    from backtrader.bokeh import BacktraderBokeh, Blackly
    
    # 运行策略后
    results = cerebro.run()
    strategy = results[0]
    
    # 创建 Bokeh 绑图器
    b = BacktraderBokeh(style='bar', scheme=Blackly())
    b.plot(strategy=strategy, show=True)  # 在浏览器中打开
    # 或者保存到文件
    # b.plot(strategy=strategy, show=False, filename='chart.html')
    ''')
    
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
    cerebro.addstrategy(BokehSMAStrategy)
    cerebro.broker.setcash(100000)
    
    # 添加分析器以便显示绩效指标（使用0作为无风险利率）
    cerebro.add_report_analyzers(riskfree_rate=0.0)
    
    print("运行策略...")
    results = cerebro.run()
    
    # 设置输出目录
    output_dir = os.path.join(os.path.dirname(__file__), 'output')
    os.makedirs(output_dir, exist_ok=True)
    output_file_path = os.path.join(output_dir, 'bokeh_chart.html')
    
    try:
        from backtrader.bokeh import BacktraderBokeh, Blackly
        
        # 创建 Bokeh 绑图器
        b = BacktraderBokeh(
            style='bar',
            scheme=Blackly(),
        )
        
        # 绑图并保存（传入策略实例，而不是 results）
        strategy = results[0]
        b.plot(strategy=strategy, show=False, filename=output_file_path)
        print(f"✓ Bokeh 图表已保存到: {output_file_path}")
    except ImportError as e:
        print(f"⚠ 需要安装 bokeh: pip install bokeh")
        print(f"  错误: {e}")
    except Exception as e:
        print(f"\n⚠ Bokeh 图表生成跳过: {e}")
        print("  Bokeh 图表生成需要完整的环境配置")
        print("  上面的主题、工具函数和标签页示例已成功运行")


if __name__ == '__main__':
    print("=" * 60)
    print("Bokeh 交互式图表示例")
    print("=" * 60)
    
    # 运行所有示例
    example_schemes()
    example_utils()
    example_tabs()
    example_backtrader_bokeh()
    example_save_bokeh_html()  # 尝试生成 bokeh_chart.html
    
    print("\n" + "=" * 60)
    print("示例运行完成！")
    print("Bokeh 模块功能展示：")
    print("  ✓ 主题配置 (Scheme, Blackly, Tradimo)")
    print("  ✓ 工具函数 (sanitize_source_name)")
    print("  ✓ 标签页系统 (BokehTab)")
    print("=" * 60)
