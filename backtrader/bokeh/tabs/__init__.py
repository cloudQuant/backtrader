#!/usr/bin/env python
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
from .live import LiveTab
from .log import LogTab
from .metadata import MetadataTab
from .performance import PerformanceTab
from .source import SourceTab

__all__ = [
    "AnalyzerTab",
    "ConfigTab",
    "LogTab",
    "MetadataTab",
    "SourceTab",
    "LiveTab",
    "PerformanceTab",
]
