#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

import math

from .. import Indicator

__all__ = [
    "I4DRFV3",
]


class I4DRFV3(Indicator):
    """High/low direction indicator; unavailable window comparisons yield NaN."""

    lines = ("color", "value")
    params = (("period", 11),)

    def __init__(self):
        """Initialize minimum history and derived signal parameters."""
        self.addminperiod(int(self.p.period) + 2)

    def next(self):
        """Calculate directional value and color for the current bar."""
        total = 0.0
        period = int(self.p.period)
        for i in range(period):
            high_diff = float(self.data.high[-i]) - float(self.data.high[-(i + 1)])
            low_diff = float(self.data.low[-i]) - float(self.data.low[-(i + 1)])
            if not math.isfinite(high_diff) or not math.isfinite(low_diff):
                self.lines.value[0] = float("nan")
                self.lines.color[0] = float("nan")
                return
            if high_diff > 0:
                total += 1.0
            if low_diff < 0:
                total -= 1.0
        value = total / float(period) * 100.0
        self.lines.value[0] = value
        self.lines.color[0] = 1.0 if value > 0 else 0.0
