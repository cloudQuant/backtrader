#!/usr/bin/env python
"""Utilities Module - Common utility functions and classes.

This module provides common utilities used throughout the backtrader framework
including data structures, date/time conversions, and helper functions.

Exports:
    AutoDict, AutoDictList, AutoOrderedDict, DotDict: Dictionary utilities.
    OrderedDict: Ordered dictionary from collections.
    num2date, date2num, num2dt, num2time, time2num: Date/time conversions.
    tzparse, Localizer, TIME_MAX: Timezone utilities.

Example:
    >>> from backtrader.utils import OrderedDict, date2num
    >>> od = OrderedDict()
    >>> od['key'] = 'value'
"""

from collections import OrderedDict as OrderedDict

from .autodict import AutoDict as AutoDict
from .autodict import AutoDictList as AutoDictList
from .autodict import AutoOrderedDict as AutoOrderedDict
from .autodict import DotDict as DotDict
from .dateintern import TIME_MAX as TIME_MAX
from .dateintern import UTC as UTC
from .dateintern import Localizer as Localizer
from .dateintern import TZLocal as TZLocal
from .dateintern import date2num as date2num
from .dateintern import num2date as num2date
from .dateintern import num2dt as num2dt
from .dateintern import num2time as num2time
from .dateintern import time2num as time2num
from .dateintern import tzparse as tzparse
from .get_metrics import STANDARD_METRIC_FIELDS as STANDARD_METRIC_FIELDS
from .get_metrics import extract_backtest_metrics as extract_backtest_metrics
from .get_metrics import get_backtest_metrics as get_backtest_metrics
from .get_metrics import write_metrics as write_metrics
from .log_message import configure_logging as configure_logging
from .log_message import get_logger as get_logger
from .log_message import reset_logging as reset_logging
from .log_message import set_level as set_level

__all__ = [
    "OrderedDict",
    "AutoDict",
    "AutoDictList",
    "AutoOrderedDict",
    "DotDict",
    "TIME_MAX",
    "UTC",
    "Localizer",
    "TZLocal",
    "date2num",
    "num2date",
    "num2dt",
    "num2time",
    "time2num",
    "tzparse",
    "STANDARD_METRIC_FIELDS",
    "get_backtest_metrics",
    "extract_backtest_metrics",
    "write_metrics",
    "get_logger",
    "configure_logging",
    "set_level",
    "reset_logging",
]
