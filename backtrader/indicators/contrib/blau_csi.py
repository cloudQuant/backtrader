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
    "BlauCSI",
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


class BlauCSI(Indicator):
    """Blau CSI indicator built from smoothed momentum vs. range."""

    lines = ("main",)
    params = (
        ("xma_method", "ema"),
        ("xlength", 1),
        ("xlength1", 20),
        ("xlength2", 5),
        ("xlength3", 3),
        ("ipc1", "close"),
        ("ipc2", "open"),
    )

    def __init__(self):
        """Initialize smoothed momentum and price-range lines for CSI output."""
        shift = max(int(self.p.xlength) - 1, 0)
        price1 = _price_series(self.data, self.p.ipc1)
        price2 = _price_series(self.data, self.p.ipc2)
        mom = price1 - price2(-shift)
        price_range = Highest(self.data.high, period=max(int(self.p.xlength), 1)) - Lowest(
            self.data.low, period=max(int(self.p.xlength), 1)
        )

        xmom = EMA(mom, period=int(self.p.xlength1))
        xrange = EMA(price_range, period=int(self.p.xlength1))
        xxmom = EMA(xmom, period=int(self.p.xlength2))
        xxrange = EMA(xrange, period=int(self.p.xlength2))
        xxxmom = EMA(xxmom, period=int(self.p.xlength3))
        xxxrange = EMA(xxrange, period=int(self.p.xlength3))

        self.l.main = btfunc.DivByZero(100.0 * xxxmom, xxxrange, zero=0.0)
