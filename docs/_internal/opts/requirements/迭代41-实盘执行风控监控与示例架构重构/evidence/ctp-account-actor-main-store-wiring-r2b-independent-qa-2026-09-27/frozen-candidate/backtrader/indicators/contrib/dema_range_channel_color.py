#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import (
    DoubleExponentialMovingAverage,
    Indicator,
)

__all__ = [
    "DemaRangeChannelColor",
]


class DemaRangeChannelColor(Indicator):
    """Indicator computing DEMA-based upper/lower range channels with a color index for breakout direction."""

    lines = ("color_idx", "upper", "lower")
    params = (("period", 14),)

    def __init__(self):
        """Initialize DEMA channels from high/low inputs."""
        self.upper_dema = DoubleExponentialMovingAverage(self.data.high, period=self.p.period)
        self.lower_dema = DoubleExponentialMovingAverage(self.data.low, period=self.p.period)

    def next(self):
        """Set the upper, lower, and color_idx line values based on close position relative to DEMA band."""
        upper = float(self.upper_dema[0])
        lower = float(self.lower_dema[0])
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
