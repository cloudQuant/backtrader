#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

import math

from .. import Indicator

__all__ = [
    "FramaSeries",
    "FramaLinesIndicator",
]


class FramaSeries(Indicator):
    """Fractal Adaptive Moving Average (FrAMA) of a single input series."""

    lines = ("frama",)
    params = (("period", 14),)

    def __init__(self):
        """Set the minimum period required for the FrAMA computation."""
        self.addminperiod(max(int(self.p.period), 2))

    def next(self):
        """Compute the adaptive-alpha FrAMA value for the current bar."""
        period = max(int(self.p.period), 2)
        half = max(period // 2, 1)
        window = [float(self.data[-i]) for i in range(period - 1, -1, -1)]
        if len(window) < period:
            self.lines.frama[0] = float(self.data[0])
            return
        first = window[:half]
        second = window[-half:]
        n1 = (max(first) - min(first)) / float(half)
        n2 = (max(second) - min(second)) / float(half)
        n3 = (max(window) - min(window)) / float(period)
        if n1 > 0.0 and n2 > 0.0 and n3 > 0.0:
            dim = (math.log(n1 + n2) - math.log(n3)) / math.log(2.0)
        else:
            dim = 1.0
        alpha = math.exp(-4.6 * (dim - 1.0))
        alpha = min(max(alpha, 0.01), 1.0)
        prev = float(self.lines.frama[-1]) if len(self) > 0 else float(self.data[0])
        self.lines.frama[0] = alpha * float(self.data[0]) + (1.0 - alpha) * prev


class FramaLinesIndicator(Indicator):
    """FrAMA candle indicator emitting smoothed OHLC and a color line."""

    lines = ("o", "h", "l", "c", "color")
    params = (("period", 14),)

    def __init__(self):
        """Build FrAMA series for each of the open/high/low/close inputs."""
        self.addminperiod(int(self.p.period) + 2)
        self.frama_open = FramaSeries(self.data.open, period=int(self.p.period))
        self.frama_high = FramaSeries(self.data.high, period=int(self.p.period))
        self.frama_low = FramaSeries(self.data.low, period=int(self.p.period))
        self.frama_close = FramaSeries(self.data.close, period=int(self.p.period))

    def next(self):
        """Assemble the smoothed FrAMA candle and classify its color."""
        o = float(self.frama_open[0])
        h = float(self.frama_high[0])
        low_price = float(self.frama_low[0])
        c = float(self.frama_close[0])
        mx = max(o, c)
        mn = min(o, c)
        h = max(mx, h)
        low_price = min(mn, low_price)
        color = 1
        if o < c:
            color = 2
        elif o > c:
            color = 0
        self.lines.o[0] = o
        self.lines.h[0] = h
        self.lines.l[0] = low_price
        self.lines.c[0] = c
        self.lines.color[0] = color
