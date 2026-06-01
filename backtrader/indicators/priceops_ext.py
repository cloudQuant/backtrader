#!/usr/bin/env python
"""Price transform and simple signal indicators.

This module hosts small price-derived indicators migrated from functional
strategy tests. They are intentionally lightweight and depend only on the
standard Backtrader line API so they can be reused as ``bt.indicators.Xxx``.
"""

from . import Indicator
from .sma import SMA

__all__ = [
    "HighLowAverage",
    "MedianPrice",
    "PercentReturnsPeriod",
    "SMACloseSignal",
    "TypicalPrice",
    "WeightedPrice",
]


class WeightedPrice(Indicator):
    """Weighted price ``(high + low + 2 * close) / 4``.

    The indicator exposes both ``value`` and ``weighted`` lines because the
    migrated functional tests used both names for the same formula.
    """

    lines = ("value", "weighted")

    def __init__(self):
        weighted = (self.data.high + self.data.low + self.data.close * 2.0) / 4.0
        self.lines.value = weighted
        self.lines.weighted = weighted


class MedianPrice(Indicator):
    """Median price ``(high + low) / 2``."""

    lines = ("value", "median")

    def __init__(self):
        median = (self.data.high + self.data.low) / 2.0
        self.lines.value = median
        self.lines.median = median


class TypicalPrice(Indicator):
    """Typical price ``(high + low + close) / 3``."""

    lines = ("typical", "value")

    def __init__(self):
        typical = (self.data.high + self.data.low + self.data.close) / 3.0
        self.lines.typical = typical
        self.lines.value = typical


class HighLowAverage(Indicator):
    """Rolling average of the high-low range."""

    lines = ("avg",)
    params = (("period", 50),)

    def __init__(self):
        self.addminperiod(self.p.period)

    def next(self):
        total = 0.0
        for i in range(self.p.period):
            total += float(self.data.high[-i] - self.data.low[-i])
        self.lines.avg[0] = total / self.p.period


class PercentReturnsPeriod(Indicator):
    """Percentage return over ``period`` bars using the close line."""

    lines = ("returns",)
    params = (("period", 40),)

    def __init__(self):
        self.addminperiod(self.p.period)

    def next(self):
        previous = self.data.close[-self.p.period]
        if previous != 0:
            self.lines.returns[0] = (self.data.close[0] - previous) / previous
        else:
            self.lines.returns[0] = 0


class SMACloseSignal(Indicator):
    """Signal line equal to current price minus its SMA."""

    lines = ("signal",)
    params = (("period", 30),)

    def __init__(self):
        self.lines.signal = self.data - SMA(self.data, period=self.p.period)
