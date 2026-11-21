#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

import math

from ...linebuffer import _reject_factor_infinity
from .. import Indicator

__all__ = [
    "DonchianChannelsSystem",
]


class DonchianChannelsSystem(Indicator):
    """Donchian-channel indicator emitting breakout-oriented color states."""

    lines = ("color",)
    params = (
        ("period", 20),
        ("shift", 2),
        ("margins", -2),
    )

    def __init__(self):
        """Initialize warmup period based on configured Donchian window."""
        self.addminperiod(int(self.p.period) + int(self.p.shift) + 3)

    def next(self):
        """Update rolling channel bounds and write the current breakout color."""
        shift = int(self.p.shift)
        highs = [float(self.data.high[-(shift + i)]) for i in range(int(self.p.period))]
        lows = [float(self.data.low[-(shift + i)]) for i in range(int(self.p.period))]
        if not all(map(math.isfinite, (*highs, *lows))):
            self.lines.color[0] = float("nan")
            return
        hh = max(highs)
        ll = min(lows)
        def offset():
            span = hh - ll
            if math.isinf(span):
                _reject_factor_infinity(self.lines.color, span)
            margins = float(self.p.margins)
            if math.isinf(margins):
                _reject_factor_infinity(self.lines.color, margins)
            scaled = span * margins
            if math.isinf(scaled):
                _reject_factor_infinity(self.lines.color, scaled)
            return scaled / 100.0

        smin = ll + offset()
        if math.isinf(smin):
            _reject_factor_infinity(self.lines.color, smin)
        smax = hh - offset()
        if math.isinf(smax):
            _reject_factor_infinity(self.lines.color, smax)
        close = float(self.data.close[0])
        open_ = float(self.data.open[0])
        if not all(map(math.isfinite, (smin, smax, close, open_))):
            self.lines.color[0] = float("nan")
            return
        color = 2.0
        if close > smax:
            color = 4.0 if open_ <= close else 3.0
        if close < smin:
            color = 0.0 if open_ > close else 1.0
        self.lines.color[0] = color
