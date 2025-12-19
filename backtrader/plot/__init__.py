#!/usr/bin/env python
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
        traceback.format_exception(e)
        pass


from .plot import Plot as Plot
from .plot import Plot_OldSync as Plot_OldSync
from .plot_plotly import PlotlyPlot as PlotlyPlot
from .scheme import PlotScheme as PlotScheme
