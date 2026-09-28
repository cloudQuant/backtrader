#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import (
    ExponentialMovingAverage,
    Indicator,
)

__all__ = [
    "RaviIndicator",
]


class RaviIndicator(Indicator):
    """RAVI oscillator: percentage spread between a fast and slow EMA of close."""

    lines = ("ravi",)
    params = (
        ("fast_length", 7),
        ("slow_length", 65),
    )

    def __init__(self):
        """Build the fast/slow EMAs and set the indicator warmup period."""
        self.fast_ma = ExponentialMovingAverage(self.data.close, period=self.p.fast_length)
        self.slow_ma = ExponentialMovingAverage(self.data.close, period=self.p.slow_length)
        self.addminperiod(self.p.slow_length + 3)

    def next(self):
        """Compute the RAVI value as the percent spread of fast over slow EMA."""
        slow = float(self.slow_ma[0])
        if abs(slow) <= 1e-12:
            value = 0.0
        else:
            value = 100.0 * (float(self.fast_ma[0]) - slow) / slow
        self.lines.ravi[0] = value
