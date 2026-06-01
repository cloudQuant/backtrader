#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import (
    Indicator,
    SimpleMovingAverage,
)

__all__ = [
    "IndexedMovingAverage",
]


class IndexedMovingAverage(Indicator):
    """Indicator that normalizes price-to-MA imbalance for directional signals."""

    lines = ("ima",)
    params = (("period", 5),)

    def __init__(self):
        """Initialize MA line and warmup period for indicator output."""
        self.ma = SimpleMovingAverage(self.data.close, period=self.p.period)
        self.addminperiod(self.p.period + 1)

    def next(self):
        """Write indexed moving-average deviation to ``lines.ima`` for current bar."""
        ma = float(self.ma[0])
        close = float(self.data.close[0])
        self.lines.ima[0] = 0.0 if abs(ma) < 1e-12 else (close / ma) - 1.0
