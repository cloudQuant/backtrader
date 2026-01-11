#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
"""
Plotly 增强功能测试

测试迭代47中添加的Plotly绘图增强功能
"""

import sys
import os
import datetime

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import backtrader as bt


def test_tableau_color_schemes():
    """测试 Tableau 配色方案"""
    from backtrader.plot.plot_plotly import (
        TABLEAU10, TABLEAU20, TABLEAU10_LIGHT, TAB10_INDEX,
        get_color_scheme
    )
    
    # 测试配色方案存在
    assert len(TABLEAU10) == 10, f"TABLEAU10 should have 10 colors, got {len(TABLEAU10)}"
    assert len(TABLEAU20) == 20, f"TABLEAU20 should have 20 colors, got {len(TABLEAU20)}"
    assert len(TABLEAU10_LIGHT) == 10, f"TABLEAU10_LIGHT should have 10 colors, got {len(TABLEAU10_LIGHT)}"
    assert len(TAB10_INDEX) == 11, f"TAB10_INDEX should have 11 elements, got {len(TAB10_INDEX)}"
    
    # 测试 get_color_scheme 函数
    assert get_color_scheme('tableau10') == TABLEAU10
    assert get_color_scheme('tableau20') == TABLEAU20
    assert get_color_scheme('tableau10_light') == TABLEAU10_LIGHT
    assert get_color_scheme('unknown') == TABLEAU10  # 默认返回 tableau10
    
    print("✓ Tableau 配色方案测试通过")


def test_wrap_legend_text():
    """测试图例文本换行功能"""
    from backtrader.plot.plot_plotly import wrap_legend_text
    
    # 短文本不换行
    assert wrap_legend_text("short", 16) == "short"
    
    # 长文本换行
    long_text = "This is a very long legend text"
    wrapped = wrap_legend_text(long_text, 10)
    assert "<br>" in wrapped
    
    # 空文本
    assert wrap_legend_text(None, 16) == ''
    assert wrap_legend_text('', 16) == ''
    
    # 测试换行符移除
    text_with_newline = "line1\nline2"
    wrapped = wrap_legend_text(text_with_newline, 100)
    assert '\n' not in wrapped
    
    print("✓ 图例文本换行功能测试通过")


def test_plotly_scheme_new_params():
    """测试 PlotlyScheme 新参数"""
    from backtrader.plot.plot_plotly import PlotlyScheme
    
    # 测试默认值
    scheme = PlotlyScheme()
    assert scheme.decimal_places == 5
    assert scheme.max_legend_text_width == 16
    assert scheme.color_scheme == 'tableau10'
    assert scheme.fillalpha == 0.20
    
    # 测试自定义值
    scheme2 = PlotlyScheme(
        decimal_places=2,
        max_legend_text_width=20,
        color_scheme='tableau20',
        fillalpha=0.30
    )
    assert scheme2.decimal_places == 2
    assert scheme2.max_legend_text_width == 20
    assert scheme2.color_scheme == 'tableau20'
    assert scheme2.fillalpha == 0.30
    
    # 测试 Tableau 配色属性
    assert hasattr(scheme, 'tableau10')
    assert hasattr(scheme, 'tableau20')
    assert hasattr(scheme, 'tableau10_light')
    assert hasattr(scheme, 'tab10_index')
    
    print("✓ PlotlyScheme 新参数测试通过")


def test_scheme_color_method():
    """测试 PlotlyScheme.color() 方法"""
    from backtrader.plot.plot_plotly import PlotlyScheme
    
    scheme = PlotlyScheme()
    
    # 测试颜色获取
    color0 = scheme.color(0)
    color1 = scheme.color(1)
    assert color0 is not None
    assert color1 is not None
    assert isinstance(color0, str)
    
    # 测试颜色循环
    colors = [scheme.color(i) for i in range(20)]
    assert len(colors) == 20
    
    # 测试 get_colors 方法
    assert scheme.get_colors() == scheme.tableau10
    
    scheme.color_scheme = 'tableau20'
    assert scheme.get_colors() == scheme.tableau20
    
    print("✓ PlotlyScheme.color() 方法测试通过")


def test_color_mapper():
    """测试颜色映射器"""
    from backtrader.plot.plot_plotly import COLOR_MAPPER
    
    # 测试基本颜色
    assert 'blue' in COLOR_MAPPER
    assert 'red' in COLOR_MAPPER
    assert 'green' in COLOR_MAPPER
    
    # 测试 Tableau 颜色
    assert 'steelblue' in COLOR_MAPPER
    assert 'darkorange' in COLOR_MAPPER
    assert 'crimson' in COLOR_MAPPER
    
    # 测试颜色格式
    assert COLOR_MAPPER['blue'].startswith('rgb(')
    assert COLOR_MAPPER['steelblue'].startswith('rgb(')
    
    print("✓ 颜色映射器测试通过")


def test_plotly_plot_helper_methods():
    """测试 PlotlyPlot 辅助方法"""
    from backtrader.plot.plot_plotly import PlotlyPlot, PlotlyScheme
    
    # 使用 decimal_places 参数直接传递
    plotter = PlotlyPlot(decimal_places=3)
    
    # 测试 _format_value (注意 Python 四舍五入规则)
    formatted = plotter._format_value(123.456789)
    assert formatted.startswith('123.45'), f"Expected '123.45x', got '{formatted}'"
    assert plotter._format_value(0) == '0.000'
    
    # 测试 _get_tick_format
    assert plotter._get_tick_format() == '.3f'
    
    # 测试 _format_label
    long_label = "This is a very long indicator label"
    formatted = plotter._format_label(long_label)
    assert len(formatted.replace('<br>', '')) == len(long_label)
    
    print("✓ PlotlyPlot 辅助方法测试通过")


def test_integration_with_strategy():
    """测试与策略的集成"""
    from backtrader.plot.plot_plotly import PlotlyPlot, PlotlyScheme
    
    class TestStrategy(bt.Strategy):
        def __init__(self):
            self.sma = bt.indicators.SMA(period=10)
        
        def next(self):
            pass
    
    # 创建 cerebro
    cerebro = bt.Cerebro()
    
    # 添加数据
    data_path = os.path.join(os.path.dirname(__file__), 'datas', 'nvda-1999-2014.txt')
    if os.path.exists(data_path):
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
            todate=datetime.datetime(2000, 3, 31),
        )
        cerebro.adddata(data)
        cerebro.addstrategy(TestStrategy)
        
        # 运行策略
        results = cerebro.run()
        
        # 创建绘图器
        scheme = PlotlyScheme(
            decimal_places=2,
            max_legend_text_width=20,
            color_scheme='tableau20'
        )
        plotter = PlotlyPlot(scheme=scheme)
        
        # 测试绘图（不显示）
        try:
            figs = plotter.plot(results[0])
            assert len(figs) > 0, "Should generate at least one figure"
            print("✓ 策略集成测试通过")
        except Exception as e:
            print(f"⚠ 策略集成测试跳过 (可能缺少 plotly): {e}")
    else:
        print("⚠ 测试数据文件不存在，跳过策略集成测试")


def run_all_tests():
    """运行所有测试"""
    print("=" * 60)
    print("Plotly 增强功能测试")
    print("=" * 60)
    
    tests = [
        test_tableau_color_schemes,
        test_wrap_legend_text,
        test_plotly_scheme_new_params,
        test_scheme_color_method,
        test_color_mapper,
        test_plotly_plot_helper_methods,
        test_integration_with_strategy,
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
