#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
"""
Built-in tabs module.

Provides the following built-in tabs:
- AnalyzerTab: Analyzer results display
- ConfigTab: Configuration info display
- LogTab: Log display
- MetadataTab: Metadata display
- SourceTab: Source code display
- LiveTab: Live configuration tab
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
