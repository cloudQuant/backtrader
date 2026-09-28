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

import importlib
import os
import sys

_BOKEH_PACKAGE_ROOT = os.path.realpath(os.path.dirname(__file__))
_BOKEH_PACKAGE_PARENT = os.path.dirname(_BOKEH_PACKAGE_ROOT)


def _is_local_bokeh_module(module):
    """Return whether a top-level ``bokeh`` module resolves to this package."""
    module_file = getattr(module, "__file__", None)
    if module_file and os.path.realpath(module_file).startswith(_BOKEH_PACKAGE_ROOT + os.sep):
        return True

    return any(
        os.path.realpath(module_path) == _BOKEH_PACKAGE_ROOT
        for module_path in getattr(module, "__path__", ())
    )


def _ensure_external_bokeh():
    """Load the third-party Bokeh package when this package directory shadows it.

    Some test and embedded environments add ``backtrader/`` directly to
    ``sys.path``. In that layout, a bare ``import bokeh`` resolves to this
    package rather than the third-party dependency. Resolve the optional
    dependency while temporarily excluding that shadowing path.
    """
    loaded = sys.modules.get("bokeh")
    if loaded is not None and not _is_local_bokeh_module(loaded):
        return loaded

    original_path = sys.path[:]
    try:
        sys.path[:] = [
            entry
            for entry in sys.path
            if os.path.realpath(entry or os.getcwd()) != _BOKEH_PACKAGE_PARENT
        ]
        for name in list(sys.modules):
            module = sys.modules.get(name)
            if name == "bokeh" or name.startswith("bokeh."):
                if module is not None and _is_local_bokeh_module(module):
                    sys.modules.pop(name, None)
        return importlib.import_module("bokeh")
    except ImportError:
        return None
    finally:
        sys.path[:] = original_path


_ensure_external_bokeh()

if __name__ != "bokeh":
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
    if name == "LivePlotAnalyzer":
        from .analyzers import LivePlotAnalyzer

        return LivePlotAnalyzer
    if name == "RecorderAnalyzer":
        from .analyzers import RecorderAnalyzer

        return RecorderAnalyzer
    if name == "LiveClient":
        from .live import LiveClient

        return LiveClient
    if name == "LiveDataHandler":
        from .live import LiveDataHandler

        return LiveDataHandler
    if name == "BokehPlot":
        from .plot_adapter import BokehPlot

        return BokehPlot

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
    "BokehPlot",
    "tabs",
    "register_tab",
    "get_registered_tabs",
    "get_datanames",
    "get_strategy_label",
    "sanitize_source_name",
]
