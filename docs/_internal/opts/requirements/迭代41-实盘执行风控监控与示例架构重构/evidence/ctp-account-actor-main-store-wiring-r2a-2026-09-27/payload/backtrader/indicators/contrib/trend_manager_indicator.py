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
    "TrendManagerIndicator",
]


class TrendManagerIndicator(Indicator):
    """Simple MA-based trend indicator generating color state."""

    lines = ("color_state", "fast_line", "slow_line")
    params = (
        ("length1", 23),
        ("length2", 84),
    )

    def __init__(self):
        """Initialize fast and slow SMAs for crossover detection."""
        self.fast = SimpleMovingAverage(self.data.close, period=self.p.length1)
        self.slow = SimpleMovingAverage(self.data.close, period=self.p.length2)
        self.addminperiod(max(self.p.length1, self.p.length2) + 3)

    def next(self):
        """Update trend lines and color state on each bar."""
        fast = float(self.fast[0])
        slow = float(self.slow[0])
        self.lines.fast_line[0] = fast
        self.lines.slow_line[0] = slow
        self.lines.color_state[0] = 0.0 if fast >= slow else 1.0
