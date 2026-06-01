#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

import math

from .. import Indicator

__all__ = [
    "DotsIndicator",
]


class DotsIndicator(Indicator):
    """Compute a multi-cycle Dots value and color-change state.

    Attributes:
        lines: Custom lines ``dots`` and ``color``.
        params: Indicator parameters used in strategy logic.
    """

    lines = ("dots", "color")
    params = (
        ("length", 10),
        ("filter_points", 0.0),
        ("price_code", 1),
        ("point", 0.01),
    )

    def __init__(self):
        """Initialize internal caches and indicator warmup state."""
        self.addminperiod(int(self.p.length) * 4 + int(self.p.length) + 5)
        self.res1 = 1.0 / max(float(self.p.length), 1.0)
        self.phase = max(int(self.p.length) - 1, 0)
        self.cycle = 4
        self.filter_distance = float(self.p.filter_points) * float(self.p.point)

    def _price_value(self, shift):
        o = float(self.data.open[-shift] if shift else self.data.open[0])
        h = float(self.data.high[-shift] if shift else self.data.high[0])
        low_price = float(self.data.low[-shift] if shift else self.data.low[0])
        c = float(self.data.close[-shift] if shift else self.data.close[0])
        code = int(self.p.price_code)
        if code == 1:
            return c
        if code == 2:
            return o
        if code == 3:
            return h
        if code == 4:
            return low_price
        if code == 5:
            return (h + low_price) / 2.0
        if code == 6:
            return (h + low_price + c) / 3.0
        if code == 7:
            return (h + low_price + c + c) / 4.0
        if code == 8:
            return (o + h + low_price + c) / 4.0
        return c

    def next(self):
        """Update smoothed value and color state for the current bar."""
        total_len = self.phase + int(self.p.length) * self.cycle
        if len(self.data) <= total_len:
            return
        t = 0.0
        total = 0.0
        weight = 0.0
        for iii in range(total_len):
            if t <= 0.5:
                g = 1.0
            else:
                g = 1.0 / (self.phase + 1.0)
            beta = math.cos(math.pi * t)
            alpha = g * beta
            price = self._price_value(iii)
            total += alpha * price
            weight += alpha
            if t < 1.0:
                t += self.res1
        ma = total / weight if weight else self.data.close[0]
        prev_ma = float(self.lines.dots[-1]) if len(self.data) > 1 else ma
        color = float(self.lines.color[-1]) if len(self.data) > 1 else 0.0
        if ma - prev_ma > self.filter_distance:
            color = 0.0
        elif prev_ma - ma > self.filter_distance:
            color = 1.0
        self.lines.dots[0] = ma
        self.lines.color[0] = color
