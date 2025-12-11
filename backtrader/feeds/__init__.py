#!/usr/bin/env python
from .btcsv import *
from .csvgeneric import *
from .influxfeed import *
from .mt4csv import *
from .pandafeed import *
from .quandl import *
from .sierrachart import *
from .vchart import *
from .vchartcsv import *
from .yahoo import *

try:
    from .ibdata import *
except ImportError:
    pass  # The user may not have ibpy installed

try:
    from .vcdata import *
except ImportError:
    pass  # The user may not have something installed

try:
    from .oanda import OandaData as OandaData
except ImportError:
    pass  # The user may not have something installed


from .chainer import Chainer as Chainer
from .rollover import RollOver as RollOver
from .vchartfile import VChartFile as VChartFile
