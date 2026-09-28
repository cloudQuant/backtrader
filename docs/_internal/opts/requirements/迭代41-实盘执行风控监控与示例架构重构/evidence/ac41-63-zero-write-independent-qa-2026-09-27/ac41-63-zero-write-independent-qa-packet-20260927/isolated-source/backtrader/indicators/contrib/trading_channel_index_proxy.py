#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import (
    Indicator,
    SimpleMovingAverage,
    StandardDeviation,
)

__all__ = [
    "TradingChannelIndexProxy",
]


class TradingChannelIndexProxy(Indicator):
    """Indicator computing Trading Channel Index (TCI) and quantized state."""

    lines = ("tci", "color_index")
    params = (
        ("length1", 60),
        ("length2", 30),
        ("coeff", 0.015),
        ("high_level", 50),
        ("low_level", -50),
    )

    def __init__(self):
        """Initialize indicator inputs used by the TCI computation."""
        self.sma1 = SimpleMovingAverage(self.data.close, period=self.p.length1)
        self.dev = StandardDeviation(self.data.close, period=self.p.length1)
        self.addminperiod(max(self.p.length1, self.p.length2) + 5)

    def next(self):
        """Compute raw TCI and discretized color state for the current bar."""
        base = float(self.sma1[0])
        dev = max(float(self.dev[0]), 1e-8)
        raw = (float(self.data.close[0]) - base) / (dev * self.p.coeff)
        self.lines.tci[0] = raw
        if raw <= self.p.low_level:
            self.lines.color_index[0] = 0.0
        elif raw >= self.p.high_level:
            self.lines.color_index[0] = 4.0
        else:
            self.lines.color_index[0] = 2.0
