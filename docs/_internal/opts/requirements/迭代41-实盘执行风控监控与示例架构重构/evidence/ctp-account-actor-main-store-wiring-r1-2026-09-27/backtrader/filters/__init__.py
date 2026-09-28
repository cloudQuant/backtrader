#!/usr/bin/env python
"""Data Filters Module - Data transformation and filtering.

This module provides filter classes for transforming and filtering
data feeds. Filters can be used to resample data, fill missing values,
calculate derived data types like Heikin Ashi candles, and more.

Available Filters:
    - CalendarDays: Filter for calendar day operations.
    - DataFilter: Base class for data filtering.
    - DataFiller: Fill missing data values.
    - DaySteps: Filter for day step operations.
    - HeikinAshi: Calculate Heikin Ashi candles.
    - Renko: Calculate Renko bricks.
    - Session: Filter for session operations.
    - BSplitter: Split data into multiple parts.

Example:
    Using a filter with data:
    >>> data = bt.feeds.GenericCSVData(dataname='data.csv')
    >>> cerebro.adddata(data)
    >>> cerebro.adddata(bt.feeds.GenericCSVData(dataname='data2.csv'),
    ...                  filter=bt.filters.HeikinAshi())
"""

from ..flt import Filter as Filter
from .bsplitter import *
from .calendardays import *
from .datafiller import *
from .datafilter import *
from .daysteps import *
from .heikinashi import *
from .renko import *
from .session import *
