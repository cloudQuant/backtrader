#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import (
    ExponentialMovingAverage,
    Indicator,
    SimpleMovingAverage,
    StandardDeviation,
)

__all__ = [
    "TrendIntensityIndexProxy",
]


class TrendIntensityIndexProxy(Indicator):
    """Indicator computing Trend Intensity Index (TII) and quantized state."""

    lines = ("tii", "color_index")
    params = (
        ("length1", 60),
        ("length2", 30),
        ("high_level", 80),
        ("low_level", 20),
    )

    def __init__(self):
        """Initialize SMA/EMA/dev components for TII calculation."""
        self.sma = SimpleMovingAverage(self.data.close, period=self.p.length1)
        self.smooth = ExponentialMovingAverage(self.data.close, period=self.p.length2)
        self.dev = StandardDeviation(self.data.close, period=self.p.length1)
        self.addminperiod(max(self.p.length1, self.p.length2) + 5)

    def next(self):
        """Compute normalized TII value and discretized color state."""
        baseline = float(self.sma[0])
        smoothed = float(self.smooth[0])
        dev = max(float(self.dev[0]), 1e-8)
        value = 50.0 + (smoothed - baseline) / dev * 10.0
        value = max(0.0, min(100.0, value))
        self.lines.tii[0] = value
        if value <= self.p.low_level:
            self.lines.color_index[0] = 0.0
        elif value >= self.p.high_level:
            self.lines.color_index[0] = 4.0
        else:
            self.lines.color_index[0] = 2.0
