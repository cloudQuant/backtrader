#!/usr/bin/env python
"""Observers Module - Strategy monitoring observers.

This module provides observers for monitoring and recording strategy
execution. Observers track metrics like cash, value, drawdown, trades,
and benchmark data during backtesting.

Available Observers:
    - Benchmark: Benchmark data (price) for comparison
    - Broker: Cash and value tracking
    - BuySell: Buy/sell signal visualization
    - DrawDown: Drawdown tracking and visualization
    - LogReturns: Log returns tracking
    - TimeReturn: Returns by time period
    - Trades: Trade tracking

Example:
    Adding observers to a strategy:
    >>> cerebro.addobserver(bt.observers.DrawDown)
    >>> cerebro.addobserver(bt.observers.Trades)
"""

# The modules below should/must define __all__ with the Indicator objects
# of prepend an "_" (underscore) to private classes/variables

from .benchmark import *
from .broker import *
from .buysell import *
from .drawdown import *
from .logreturns import *
from .timereturn import *
from .trades import *
