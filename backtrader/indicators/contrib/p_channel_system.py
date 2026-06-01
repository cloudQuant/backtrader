#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import Indicator

__all__ = [
    "PChannelSystem",
]


class PChannelSystem(Indicator):
    """Indicator that classifies current bar position versus rolling channel bounds."""

    lines = ("color",)
    params = (
        ("period", 20),
        ("shift", 2),
    )

    def __init__(self):
        """Initialize warmup requirements for the configured rolling period."""
        self.addminperiod(int(self.p.period) + int(self.p.shift) + 3)

    def next(self):
        """Compute channel colors from rolling high/low and current candle body."""
        shift = int(self.p.shift)
        hh = max(float(self.data.high[-(shift + i)]) for i in range(int(self.p.period)))
        ll = min(float(self.data.low[-(shift + i)]) for i in range(int(self.p.period)))
        close = float(self.data.close[0])
        open_ = float(self.data.open[0])
        color = 2.0
        if close > hh:
            color = 4.0 if open_ <= close else 3.0
        if close < ll:
            color = 0.0 if open_ > close else 1.0
        self.lines.color[0] = color
