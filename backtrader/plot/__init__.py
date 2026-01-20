#!/usr/bin/env python
"""Plotting Module - Visualization for backtesting results.

This module provides plotting functionality using matplotlib to visualize
strategy performance, indicators, and trading signals.

Classes:
    Plot: Main plotting class using matplotlib.
    Plot_OldSync: Old synchronization mode plotting.
    PlotlyPlot: Plotly-based interactive plotting.
    PlotScheme: Plotting configuration and styling.

Example:
    Plotting cerebro results:
    >>> cerebro = bt.Cerebro()
    >>> # ... add data, strategy, etc.
    >>> results = cerebro.run()
    >>> cerebro.plot()
"""

import sys
import traceback

try:
    import matplotlib
except ImportError:
    raise ImportError("Matplotlib seems to be missing. Needed for plotting support")
else:
    touse = "TKAgg" if sys.platform != "darwin" else "MacOSX"
    try:
        matplotlib.use(touse)
    except Exception as e:
        # if another backend has already been loaded, an exception will be
        # generated and this can be skipped
        traceback.format_exception(type(e), e, e.__traceback__)
        pass


from .plot import Plot as Plot
from .plot import Plot_OldSync as Plot_OldSync
from .plot_plotly import PlotlyPlot as PlotlyPlot
from .scheme import PlotScheme as PlotScheme
