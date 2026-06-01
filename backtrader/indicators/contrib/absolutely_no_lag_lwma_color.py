#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import (
    Indicator,
    WeightedMovingAverage,
)

__all__ = [
    "AbsolutelyNoLagLwmaColor",
]


class AbsolutelyNoLagLwmaColor(Indicator):
    """Indicator computing WMA-of-WMA (no-lag) upper/lower channels with color breakout signal."""

    lines = ("color_idx", "upper", "lower")
    params = (("length", 7),)

    def __init__(self):
        """Initialize double-WMA smoothing for high and low inputs."""
        self.up_lwma_1 = WeightedMovingAverage(self.data.high, period=self.p.length)
        self.up_lwma_2 = WeightedMovingAverage(self.up_lwma_1, period=self.p.length)
        self.dn_lwma_1 = WeightedMovingAverage(self.data.low, period=self.p.length)
        self.dn_lwma_2 = WeightedMovingAverage(self.dn_lwma_1, period=self.p.length)

    def next(self):
        """Set the color index based on close position relative to the no-lag WMA channel."""
        upper = float(self.up_lwma_2[0])
        lower = float(self.dn_lwma_2[0])
        close = float(self.data.close[0])
        open_ = float(self.data.open[0])
        self.lines.upper[0] = upper
        self.lines.lower[0] = lower
        color = 4.0
        if close > upper:
            color = 3.0 if close >= open_ else 2.0
        elif close < lower:
            color = 0.0 if close <= open_ else 1.0
        self.lines.color_idx[0] = color
