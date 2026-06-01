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
    "HMA",
    "OsHMAIndicator",
]


class HMA(Indicator):
    """Hull Moving Average indicator used by OsHMA."""

    lines = ("hma",)
    params = (("period", 13),)

    def __init__(self):
        """Initialize the HMA with smoothed weighted moving averages."""
        half = max(1, int(self.p.period // 2))
        sqrt_period = max(1, int(self.p.period**0.5))
        wma_half = WeightedMovingAverage(self.data, period=half)
        wma_full = WeightedMovingAverage(self.data, period=int(self.p.period))
        diff = (2.0 * wma_half) - wma_full
        self.lines.hma = WeightedMovingAverage(diff, period=sqrt_period)
        self.addminperiod(int(self.p.period) + sqrt_period + 3)


class OsHMAIndicator(Indicator):
    """Histogram indicator that combines fast and slow HMA lines."""

    lines = ("hist",)
    params = (
        ("fast_hma", 13),
        ("slow_hma", 26),
    )

    def __init__(self):
        """Initialize fast and slow HMA sub-indicators and histogram output."""
        fast = HMA(self.data.close, period=self.p.fast_hma)
        slow = HMA(self.data.close, period=self.p.slow_hma)
        self.lines.hist = fast.hma - slow.hma
        self.addminperiod(max(self.p.fast_hma, self.p.slow_hma) + int(self.p.slow_hma**0.5) + 5)
