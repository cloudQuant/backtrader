#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

import math

from .. import (
    Indicator,
    SimpleMovingAverage,
)

__all__ = [
    "ColorX2MA",
]


class ColorX2MA(Indicator):
    """Indicator that outputs smoothed MA value and directional color index."""

    lines = ("value", "color_idx")
    params = (
        ("length1", 12),
        ("length2", 5),
    )

    def __init__(self):
        """Initialize MA stacks and minimum period."""
        ma1 = SimpleMovingAverage(self.data.close, period=max(2, self.p.length1))
        ma2 = SimpleMovingAverage(ma1, period=max(2, self.p.length2))
        self.lines.value = ma2
        self.addminperiod(self.p.length1 + self.p.length2 + 2)

    def next(self):
        """Update color index based on value momentum."""
        current = float(self.lines.value[0])
        prev = (
            float(self.lines.value[-1])
            if len(self) > 1 and math.isfinite(float(self.lines.value[-1]))
            else current
        )
        color = 0.0
        if prev < current:
            color = 1.0
        elif prev > current:
            color = 2.0
        self.lines.color_idx[0] = color
