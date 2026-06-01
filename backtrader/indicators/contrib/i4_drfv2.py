#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import Indicator

__all__ = [
    "I4DRFV2",
]


class I4DRFV2(Indicator):
    """Close-difference indicator producing value and binary color trend state."""

    lines = ("color", "value")
    params = (("period", 11),)

    def __init__(self):
        """Initialize the minimum period requirement."""
        self.addminperiod(int(self.p.period) + 2)

    def next(self):
        """Compute current indicator value and color."""
        total = 0.0
        period = int(self.p.period)
        for i in range(period):
            diff = float(self.data.close[-i]) - float(self.data.close[-(i + 1)])
            total += 1.0 if diff > 0 else -1.0
        value = total / float(period) * 100.0
        self.lines.value[0] = value
        self.lines.color[0] = 1.0 if value > 0 else 0.0
