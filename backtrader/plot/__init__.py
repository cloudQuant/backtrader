#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import sys


try:
    import matplotlib
except ImportError:
    raise ImportError(
        'Matplotlib seems to be missing. Needed for plotting support')
else:
    touse = 'TKAgg' if sys.platform != 'darwin' else 'MacOSX'
    try:
        matplotlib.use(touse)
    except:
        # if another backend has already been loaded, an exception will be
        # generated and this can be skipped
        pass


from .plot import Plot, Plot_OldSync
from .scheme import PlotScheme
