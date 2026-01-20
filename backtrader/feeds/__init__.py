#!/usr/bin/env python
"""Data Feeds Module - Data source implementations.

This module provides data feed implementations for various data sources
including CSV files, pandas DataFrames, Yahoo Finance, Interactive Brokers,
OANDA, Quandl, InfluxDB, and more.

Data Feed Types:
    - CSV Feeds: GenericCSVData, BTCSV, MT4CSV, SierraChart, VChartCSV
    - Pandas: PandasData for pandas DataFrame integration
    - Online: Yahoo Finance, OANDA, Interactive Brokers, Quandl
    - Utilities: Chainer, RollOver for data manipulation

Example:
    Loading data from a CSV file:
    >>> data = bt.feeds.GenericCSVData(
    ...     dataname='data.csv',
    ...     datetime=0,
    ...     open=1,
    ...     high=2,
    ...     low=3,
    ...     close=4,
    ...     volume=5
    ... )
    >>> cerebro.adddata(data)
"""

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
