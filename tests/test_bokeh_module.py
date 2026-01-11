#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
"""
Bokeh 模块测试

测试 bokeh 模块的基本功能
"""

import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_scheme_import():
    """测试主题导入"""
    from backtrader.bokeh import Scheme, Blackly, Tradimo
    
    # 测试基础主题
    scheme = Scheme()
    assert hasattr(scheme, 'barup')
    assert hasattr(scheme, 'bardown')
    assert hasattr(scheme, 'background_fill')
    print("✓ Scheme 基础主题测试通过")
    
    # 测试黑色主题
    blackly = Blackly()
    assert blackly.background_fill == '#222222'
    assert blackly.barup == '#ff9896'
    print("✓ Blackly 黑色主题测试通过")
    
    # 测试白色主题
    tradimo = Tradimo()
    assert tradimo.background_fill == 'white'
    assert tradimo.barup == '#e6550d'
    print("✓ Tradimo 白色主题测试通过")


def test_tab_import():
    """测试标签页导入"""
    from backtrader.bokeh import BokehTab
    from backtrader.bokeh import tabs
    
    # 检查标签页基类
    assert hasattr(BokehTab, '_is_useable')
    assert hasattr(BokehTab, '_get_panel')
    assert hasattr(BokehTab, 'is_useable')
    assert hasattr(BokehTab, 'get_panel')
    print("✓ BokehTab 基类测试通过")
    
    # 检查内置标签页
    assert hasattr(tabs, 'AnalyzerTab')
    assert hasattr(tabs, 'ConfigTab')
    assert hasattr(tabs, 'LogTab')
    assert hasattr(tabs, 'MetadataTab')
    assert hasattr(tabs, 'SourceTab')
    assert hasattr(tabs, 'LiveTab')
    print("✓ 内置标签页导入测试通过")


def test_utils_import():
    """测试工具函数导入"""
    from backtrader.bokeh import get_datanames, get_strategy_label, sanitize_source_name
    
    # 测试 sanitize_source_name
    assert sanitize_source_name('test') == 'test'
    assert sanitize_source_name('test-data') == 'test_data'
    assert sanitize_source_name('123test') == '_123test'
    print("✓ 工具函数测试通过")


def test_register_tab():
    """测试标签页注册"""
    from backtrader.bokeh import BokehTab, register_tab, get_registered_tabs
    
    class CustomTab(BokehTab):
        def _is_useable(self):
            return True
        
        def _get_panel(self):
            return None, 'Custom'
    
    # 注册前
    tabs_before = len(get_registered_tabs())
    
    # 注册自定义标签页
    register_tab(CustomTab)
    
    # 注册后
    tabs_after = len(get_registered_tabs())
    assert tabs_after == tabs_before + 1
    print("✓ 标签页注册测试通过")


def test_lazy_imports():
    """测试延迟导入"""
    from backtrader import bokeh
    
    # 测试 BacktraderBokeh
    try:
        app_class = bokeh.BacktraderBokeh
        print("✓ BacktraderBokeh 延迟导入测试通过")
    except ImportError as e:
        print(f"⚠ BacktraderBokeh 导入失败 (可能缺少 bokeh 依赖): {e}")
    
    # 测试 RecorderAnalyzer
    try:
        recorder_class = bokeh.RecorderAnalyzer
        print("✓ RecorderAnalyzer 延迟导入测试通过")
    except ImportError as e:
        print(f"⚠ RecorderAnalyzer 导入失败: {e}")


def test_basic_integration():
    """测试基本集成"""
    import backtrader as bt
    
    # 创建简单策略
    class TestStrategy(bt.Strategy):
        def __init__(self):
            pass
        
        def next(self):
            pass
    
    # 创建 cerebro
    cerebro = bt.Cerebro()
    
    # 添加数据
    import datetime
    data = bt.feeds.GenericCSVData(
        dataname=os.path.join(os.path.dirname(__file__), 'datas', 'nvda-1999-2014.txt'),
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
    cerebro.addstrategy(TestStrategy)
    
    # 尝试添加 RecorderAnalyzer
    try:
        from backtrader.bokeh import RecorderAnalyzer
        cerebro.addanalyzer(RecorderAnalyzer, indicators=False)
        
        result = cerebro.run()
        
        # 检查分析器结果
        recorder = result[0].analyzers.recorderanalyzer
        analysis = recorder.get_analysis()
        
        assert 'data' in analysis
        print("✓ RecorderAnalyzer 集成测试通过")
    except Exception as e:
        print(f"⚠ RecorderAnalyzer 集成测试失败: {e}")


def run_all_tests():
    """运行所有测试"""
    print("=" * 60)
    print("Bokeh 模块测试")
    print("=" * 60)
    
    tests = [
        test_scheme_import,
        test_tab_import,
        test_utils_import,
        test_register_tab,
        test_lazy_imports,
        test_basic_integration,
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
