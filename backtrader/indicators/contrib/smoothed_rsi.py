#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import (
    RSI,
    Indicator,
    SimpleMovingAverage,
)

__all__ = [
    "SmoothedRsi",
]


class SmoothedRsi(Indicator):
    """Smooth RSI value using an outer simple moving average."""

    lines = ("value",)
    params = (
        ("period", 14),
        ("smoothing", 6),
    )

    def __init__(self):
        """Initialize RSI and smoothed value lines from configured parameters."""
        rsi = RSI(self.data, period=self.p.period)
        self.lines.value = SimpleMovingAverage(rsi, period=self.p.smoothing)
