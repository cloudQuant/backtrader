#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
"""
内置标签页模块

提供以下内置标签页：
- AnalyzerTab: 分析器结果展示
- ConfigTab: 配置信息展示
- LogTab: 日志展示
- MetadataTab: 元数据展示
- SourceTab: 源码展示
- LiveTab: 实时配置标签页
"""

from .analyzer import AnalyzerTab
from .config import ConfigTab
from .log import LogTab
from .metadata import MetadataTab
from .source import SourceTab
from .live import LiveTab
from .performance import PerformanceTab

__all__ = [
    'AnalyzerTab',
    'ConfigTab',
    'LogTab',
    'MetadataTab',
    'SourceTab',
    'LiveTab',
    'PerformanceTab',
]
