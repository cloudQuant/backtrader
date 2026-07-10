#!/usr/bin/env python
"""Plotting module exports.

This module provides plotting classes via lazy loading so optional matplotlib
dependencies are imported only when needed.
"""

import sys
import traceback

from .plot_plotly import PlotlyPlot
from .scheme import PlotScheme

__all__ = ["Plot", "Plot_OldSync", "PlotlyPlot", "PlotScheme"]


def _load_matplotlib_plotter():
    """Load matplotlib-dependent plotters on demand."""
    try:
        import matplotlib
    except ImportError:
        raise ImportError("Matplotlib seems to be missing. Needed for plotting support") from None

    touse = "TKAgg" if sys.platform != "darwin" else "MacOSX"
    try:
        matplotlib.use(touse)
    except Exception as e:
        # if another backend has already been loaded, an exception will be
        # generated and this can be skipped
        traceback.format_exception(type(e), e, e.__traceback__)

    from . import plot

    return plot


def __getattr__(name):
    """Lazy import plotters.

    - `Plot` and `Plot_OldSync` require matplotlib.
    - `PlotlyPlot` and `PlotScheme` are independent of matplotlib.
    """
    if name == "Plot":
        return _load_matplotlib_plotter().Plot
    if name == "Plot_OldSync":
        return _load_matplotlib_plotter().Plot_OldSync
    if name == "__all__":
        return __all__

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
