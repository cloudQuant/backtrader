#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

import backtrader.functions as btfunc

from .. import (
    EMA,
    Highest,
    Indicator,
    Lowest,
)

__all__ = [
    "BlauTStochI",
]


def _price_series(data, mode):
    key = str(mode).lower()
    if key in ("1", "close", "price_close"):
        return data.close
    if key in ("2", "open", "price_open"):
        return data.open
    if key in ("3", "high", "price_high"):
        return data.high
    if key in ("4", "low", "price_low"):
        return data.low
    if key in ("5", "median", "price_median"):
        return (data.high + data.low) / 2.0
    if key in ("6", "typical", "price_typical"):
        return (data.high + data.low + data.close) / 3.0
    if key in ("7", "weighted", "price_weighted"):
        return (data.high + data.low + data.close + data.close) / 4.0
    if key in ("8", "simple", "price_simpl"):
        return (data.open + data.close) / 2.0
    if key in ("9", "quarter", "price_quarter"):
        return (data.high + data.low + data.open + data.close) / 4.0
    return data.close


class BlauTStochI(Indicator):
    """Indicator generating a smoothed Blau T-Stoch histogram."""

    lines = ("hist",)
    params = (
        ("xlength", 20),
        ("xlength1", 5),
        ("xlength2", 3),
        ("xlength3", 8),
        ("ipc", "close"),
    )

    def __init__(self):
        """Build EMA-smoothed numerator and denominator terms for histogram output."""
        price = _price_series(self.data, self.p.ipc)
        hh = Highest(self.data.high, period=int(self.p.xlength))
        ll = Lowest(self.data.low, period=int(self.p.xlength))
        stoch = price - ll
        range_line = hh - ll

        xstoch = EMA(stoch, period=int(self.p.xlength1))
        xrange = EMA(range_line, period=int(self.p.xlength1))
        xxstoch = EMA(xstoch, period=int(self.p.xlength2))
        xxrange = EMA(xrange, period=int(self.p.xlength2))
        xxxstoch = EMA(xxstoch, period=int(self.p.xlength3))
        xxxrange = EMA(xxrange, period=int(self.p.xlength3))

        self.l.hist = btfunc.DivByZero(100.0 * xxxstoch, xxxrange, zero=0.0) - 50.0
