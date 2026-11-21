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


class _BlauCSIDivision(btfunc.Logic):
    """Preserve missing operands while retaining the existing zero policy."""

    def __init__(self, *args, **kwargs):
        self.zero = kwargs.pop("zero", 0.0)
        super().__init__(*args)
        self.a, self.b = self.args

    @staticmethod
    def _missing(value):
        return isinstance(value, float) and value != value

    def next(self):
        a = self.a[0]
        b = self.b[0]
        if self._missing(a) or self._missing(b):
            self[0] = float("nan")
            return
        a = btfunc._sanitize_div_value(a)
        b = btfunc._sanitize_div_value(b)
        self[0] = a / b if b else self.zero

    def once(self, start, end):
        dst = self.array
        srca = self.a.array
        srcb = self.b.array
        while len(dst) < end:
            dst.append(0.0)
        for index in range(start, end):
            a = btfunc._value_at(srca, index)
            b = btfunc._value_at(srcb, index)
            if self._missing(a) or self._missing(b):
                dst[index] = float("nan")
                continue
            a = btfunc._sanitize_div_value(a)
            b = btfunc._sanitize_div_value(b)
            dst[index] = a / b if b else self.zero


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

        self.l.main = _BlauCSIDivision(100.0 * xxxmom, xxxrange, zero=0.0)
