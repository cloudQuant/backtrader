#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

import math

from .. import (
    ExponentialMovingAverage,
    Indicator,
)

__all__ = [
    "BlauTVI",
]


class BlauTVI(Indicator):
    """Blau Tick Volume Indicator: a triple-EMA-smoothed up/down tick oscillator."""

    lines = ("value", "color_idx")
    params = (
        ("xlength1", 12),
        ("xlength2", 12),
        ("xlength3", 12),
    )

    def __init__(self):
        """Build the up/down tick EMAs and the smoothed oscillator value line."""
        up_ticks = (self.data.volume + (self.data.close - self.data.open) / 0.01) / 2.0
        dn_ticks = (self.data.volume - (self.data.close - self.data.open) / 0.01) / 2.0
        up_1 = ExponentialMovingAverage(up_ticks, period=self.p.xlength1)
        dn_1 = ExponentialMovingAverage(dn_ticks, period=self.p.xlength1)
        up_2 = ExponentialMovingAverage(up_1, period=self.p.xlength2)
        dn_2 = ExponentialMovingAverage(dn_1, period=self.p.xlength2)
        raw = 100.0 * (up_2 - dn_2) / (up_2 + dn_2 + 1e-12)
        self.lines.value = ExponentialMovingAverage(raw, period=self.p.xlength3)
        self.addminperiod(self.p.xlength1 + self.p.xlength2 + self.p.xlength3 + 2)

    def next(self):
        """Assign a color index based on the value's sign and direction of change."""
        current = float(self.lines.value[0])
        prev = (
            float(self.lines.value[-1])
            if len(self) > 1 and math.isfinite(float(self.lines.value[-1]))
            else current
        )
        color = 2.0
        if current > 0:
            color = 4.0 if current > prev else 3.0
        elif current < 0:
            color = 0.0 if current < prev else 1.0
        self.lines.color_idx[0] = color
