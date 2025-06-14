#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
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


from .plot import Plot, Plot_OldSync
from .scheme import PlotScheme
