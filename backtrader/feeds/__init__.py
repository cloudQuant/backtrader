#!/usr/bin/env python
"""Data Feeds Module - Data source implementations.

This module provides data feed implementations for various data sources
including CSV files, pandas DataFrames, Yahoo Finance, Quandl, InfluxDB,
and the unified bt_api_py live interface.

Data Feed Types:
    - CSV Feeds: GenericCSVData, BTCSV, MT4CSV, SierraChart, VChartCSV
    - Pandas: PandasData for pandas DataFrame integration
    - Online: Yahoo Finance, Quandl, BtApiFeed
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

from .chainer import Chainer as Chainer
from .rollover import RollOver as RollOver
from .vchartfile import VChartFile as VChartFile
from .btapifeed import BtApiFeed as BtApiFeed
