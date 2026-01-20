#!/usr/bin/env python
"""Date/Time Conversion Utilities Module.

This module provides functions for converting between datetime objects
and numeric representations used internally by backtrader. It also
provides timezone handling utilities.

Exports:
    date2num: Convert datetime to internal float representation.
    num2date: Convert internal float to datetime.
    num2dt: Alias for num2date.
    time2num: Convert time to internal float representation.
    num2time: Convert internal float to time.
    tzparse: Parse timezone string.
    Localizer: Timezone localization helper.
    TZLocal: Local timezone instance.
    UTC: UTC timezone instance.
    TIME_MAX/TIME_MIN: Maximum/minimum time values.

Example:
    >>> from backtrader.utils import date2num, num2date
    >>> import datetime
    >>> dt = datetime.datetime(2020, 1, 1)
    >>> num = date2num(dt)
    >>> print(num2date(num))
    2020-01-01 00:00:00+00:00
"""

# from backtrader.utils.cython_func import date2num
# from backtrader.utils.cython_func import num2dt
# from backtrader.utils.cython_func import num2date
# from backtrader.utils.cython_func import time2num
# from backtrader.utils.cython_func import num2time


from .dateintern import (
    TIME_MAX,
    TIME_MIN,
    UTC,
    Localizer,
    TZLocal,
    date2num,
    datetime2str,
    datetime2timestamp,
    get_last_timeframe_timestamp,
    num2date,
    num2dt,
    num2time,
    str2datetime,
    time2num,
    timestamp2datetime,
    tzparse,
)

__all__ = (
    "num2date",
    "num2dt",
    "date2num",
    "time2num",
    "num2time",
    "get_last_timeframe_timestamp",
    "UTC",
    "TZLocal",
    "Localizer",
    "tzparse",
    "TIME_MAX",
    "TIME_MIN",
    "timestamp2datetime",
    "datetime2timestamp",
    "str2datetime",
    "datetime2str",
)
