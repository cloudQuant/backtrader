#!/usr/bin/env python
"""Backtrader - Python Trading Framework.

A feature-rich Python framework for backtesting and trading with support for
multiple data feeds, brokers, and analysis tools.

This module serves as the main entry point for the backtrader package,
exposing all public APIs through a unified namespace.

Example:
    Basic usage::

        import backtrader as bt

        cerebro = bt.Cerebro()
        data = bt.feeds.GenericCSVData(dataname='data.csv')
        cerebro.adddata(data)
        cerebro.addstrategy(MyStrategy)
        results = cerebro.run()
        cerebro.plot()

Core Components:
    - **Cerebro**: Main engine that orchestrates backtesting
    - **Strategy**: Base class for trading strategies
    - **Indicator**: Base class for technical indicators
    - **Analyzer**: Base class for performance analyzers
    - **Broker**: Simulated broker for order execution
    - **Feed**: Data feed classes for market data input

Subpackages:
    - analyzers: Performance analysis tools (Sharpe, Drawdown, etc.)
    - brokers: Broker implementations (IB, OANDA, etc.)
    - feeds: Data feed implementations (CSV, Pandas, Yahoo, etc.)
    - indicators: Technical indicators (SMA, RSI, MACD, etc.)
    - observers: Chart observers for visualization
    - sizers: Position sizing algorithms
    - stores: Data store implementations
    - filters: Data filtering utilities

Attributes:
    __version__ (str): Package version string
    __btversion__ (tuple): Package version as tuple

See Also:
    - Documentation: https://www.backtrader.com/docu/
    - GitHub: https://github.com/mementum/backtrader
"""

# Load contributed indicators and studies
from .indicators import contrib as _indicators_contrib

from . import analyzers as analyzers
from . import broker as broker
from . import brokers as brokers
from . import commissions as commissions
from . import commissions as comms
from . import errors as errors
from . import feeds as feeds
from . import filters as filters
from . import indicators as ind
from . import indicators as indicators
from . import observers as obs
from . import observers as observers
from . import signals as signals
from . import sizers as sizers
from . import stores as stores
from . import talib as talib
from . import timer as timer
from . import utils as utils
from .analyzer import *
from .broker import *
from .cerebro import *
from .comminfo import *
from .dataseries import *
from .errors import *
from .feed import *
from .flt import *
from .functions import *
from .indicator import *
from .linebuffer import *
from .lineiterator import *
from .lineseries import *
from .observer import *
from .order import *
from .position import *
from .resamplerfilter import *
from .signal import *
from .sizer import *
from .sizers import SizerFix  # old sizer for compatibility
from .store import Store
from .strategy import *
from .timer import *
from .trade import *
from .utils import date2num, num2date, num2dt, num2time, time2num
from .version import __btversion__, __version__
from .writer import *

# import backtrader.studies.contrib

# from backtrader import vectors
