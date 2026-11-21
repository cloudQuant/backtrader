#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

import math

from .. import (
    TRIX,
    Indicator,
)

__all__ = [
    "TriXCandleIndicator",
]


class TriXCandleIndicator(Indicator):
    """Indicator that transforms TRIX values into a candle-style representation."""

    lines = ("o", "h", "l", "c", "color")
    params = (("period", 14),)

    def __init__(self):
        """Initialize TRIX line calculators and minimum data warmup."""
        self.addminperiod(int(self.p.period) + 2)
        self.trix_open = TRIX(self.data.open, period=int(self.p.period))
        self.trix_high = TRIX(self.data.high, period=int(self.p.period))
        self.trix_low = TRIX(self.data.low, period=int(self.p.period))
        self.trix_close = TRIX(self.data.close, period=int(self.p.period))

    def next(self):
        """Compute per-bar TRIX O/H/L/C proxy values and color state."""
        o = float(self.trix_open[0])
        h = float(self.trix_high[0])
        low_price = float(self.trix_low[0])
        c = float(self.trix_close[0])
        # TRIX's zero-denominator branch may emit zero even when its current
        # source price is missing. Preserve absence at the candle boundary.
        if not math.isfinite(float(self.data.open[0])):
            o = math.nan
        if not math.isfinite(float(self.data.high[0])):
            h = math.nan
        if not math.isfinite(float(self.data.low[0])):
            low_price = math.nan
        if not math.isfinite(float(self.data.close[0])):
            c = math.nan
        valid_body = math.isfinite(o) and math.isfinite(c)
        if valid_body and math.isfinite(h):
            h = max(o, c, h)
        else:
            h = math.nan
        if valid_body and math.isfinite(low_price):
            low_price = min(o, c, low_price)
        else:
            low_price = math.nan
        if not valid_body:
            color = math.nan
        elif o < c:
            color = 2
        elif o > c:
            color = 0
        else:
            color = 1
        self.lines.o[0] = o
        self.lines.h[0] = h
        self.lines.l[0] = low_price
        self.lines.c[0] = c
        self.lines.color[0] = color
