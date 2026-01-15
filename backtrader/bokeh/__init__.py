#!/usr/bin/env python
"""
Backtrader Bokeh Module

Provides Bokeh-based live plotting functionality, including:
- Real-time data push and chart updates
- Extensible tab system
- Navigation controls (pause/play/forward/backward)
- Theme system (black/white themes)
- Memory optimization (lookback control)

Example:
    import backtrader as bt
    from backtrader.bokeh import LivePlotAnalyzer, Blackly

    cerebro = bt.Cerebro()
    cerebro.adddata(data)
    cerebro.addstrategy(MyStrategy)

    # Add live plot analyzer
    cerebro.addanalyzer(LivePlotAnalyzer,
                       scheme=Blackly(),
                       lookback=100)

    cerebro.run()
"""

from . import tabs
from .schemes import Blackly, Scheme, Tradimo
from .tab import BokehTab
from .utils import get_datanames, get_strategy_label, sanitize_source_name

# Custom tab registry
_custom_tabs = []


def register_tab(tab_class):
    """Register a custom tab.

    Args:
        tab_class: Tab class that inherits from BokehTab
    """
    if not issubclass(tab_class, BokehTab):
        raise ValueError("tab_class must be a subclass of BokehTab")
    _custom_tabs.append(tab_class)


def get_registered_tabs():
    """Get all registered custom tabs."""
    return _custom_tabs.copy()


# Lazy import to avoid circular dependencies
def __getattr__(name):
    """Lazy load module attributes."""
    if name == "BacktraderBokeh":
        from .app import BacktraderBokeh

        return BacktraderBokeh
    elif name == "LivePlotAnalyzer":
        from .analyzers import LivePlotAnalyzer

        return LivePlotAnalyzer
    elif name == "RecorderAnalyzer":
        from .analyzers import RecorderAnalyzer

        return RecorderAnalyzer
    elif name == "LiveClient":
        from .live import LiveClient

        return LiveClient
    elif name == "LiveDataHandler":
        from .live import LiveDataHandler

        return LiveDataHandler

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "BacktraderBokeh",
    "Scheme",
    "Blackly",
    "Tradimo",
    "BokehTab",
    "LivePlotAnalyzer",
    "RecorderAnalyzer",
    "LiveClient",
    "LiveDataHandler",
    "tabs",
    "register_tab",
    "get_registered_tabs",
    "get_datanames",
    "get_strategy_label",
    "sanitize_source_name",
]
