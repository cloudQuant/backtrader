#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
from .csvgeneric import *
from .btcsv import *
from .vchartcsv import *
from .vchart import *
from .yahoo import *
from .quandl import *
from .sierrachart import *
from .mt4csv import *
from .pandafeed import *
from .influxfeed import *

try:
    from .ibdata import *
except ImportError:
    pass  # The user may not have ibpy installed

try:
    from .vcdata import *
except ImportError:
    pass  # The user may not have something installed

try:
    from .oanda import OandaData
except ImportError:
    pass  # The user may not have something installed


from .vchartfile import VChartFile

from .rollover import RollOver
from .chainer import Chainer
