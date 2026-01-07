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

from collections import OrderedDict

from .autodict import AutoDict, AutoDictList, AutoOrderedDict, DotDict
from .dateintern import (
    TIME_MAX,
    TZLocal,
    UTC,
    Localizer,
    date2num,
    num2date,
    num2dt,
    num2time,
    time2num,
    tzparse,
)
