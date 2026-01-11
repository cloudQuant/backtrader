#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
"""
Backtrader Bokeh Module

提供基于 Bokeh 的实时绘图功能，包括：
- 实时数据推送和图表更新
- 可扩展的标签页系统
- 导航控制（暂停/播放/前进/后退）
- 主题系统（黑色/白色主题）
- 内存优化（lookback 控制）

使用示例:
    import backtrader as bt
    from backtrader.bokeh import LivePlotAnalyzer, Blackly
    
    cerebro = bt.Cerebro()
    cerebro.adddata(data)
    cerebro.addstrategy(MyStrategy)
    
    # 添加实时绘图分析器
    cerebro.addanalyzer(LivePlotAnalyzer,
                       scheme=Blackly(),
                       lookback=100)
    
    cerebro.run()
"""

from .schemes import Scheme, Blackly, Tradimo
from .tab import BokehTab
from . import tabs
from .utils import get_datanames, get_strategy_label, sanitize_source_name

# 自定义标签页注册表
_custom_tabs = []


def register_tab(tab_class):
    """注册自定义标签页
    
    Args:
        tab_class: 继承自 BokehTab 的标签页类
    """
    if not issubclass(tab_class, BokehTab):
        raise ValueError("tab_class must be a subclass of BokehTab")
    _custom_tabs.append(tab_class)


def get_registered_tabs():
    """获取所有注册的自定义标签页"""
    return _custom_tabs.copy()


# 延迟导入以避免循环依赖
def __getattr__(name):
    """延迟加载模块属性"""
    if name == 'BacktraderBokeh':
        from .app import BacktraderBokeh
        return BacktraderBokeh
    elif name == 'LivePlotAnalyzer':
        from .analyzers import LivePlotAnalyzer
        return LivePlotAnalyzer
    elif name == 'RecorderAnalyzer':
        from .analyzers import RecorderAnalyzer
        return RecorderAnalyzer
    elif name == 'LiveClient':
        from .live import LiveClient
        return LiveClient
    elif name == 'LiveDataHandler':
        from .live import LiveDataHandler
        return LiveDataHandler
    
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    'BacktraderBokeh',
    'Scheme',
    'Blackly',
    'Tradimo',
    'BokehTab',
    'LivePlotAnalyzer',
    'RecorderAnalyzer',
    'LiveClient',
    'LiveDataHandler',
    'tabs',
    'register_tab',
    'get_registered_tabs',
    'get_datanames',
    'get_strategy_label',
    'sanitize_source_name',
]
