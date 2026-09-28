#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import Indicator

__all__ = [
    "InverseReactionIndicator",
]


class InverseReactionIndicator(Indicator):
    """Indicator that tracks candle reaction amplitude and dynamic thresholds."""

    lines = ("price_change", "upper_level", "lower_level")
    params = (
        ("ma_period", 3),
        ("coefficient", 1.618),
    )

    def __init__(self):
        """Set minimum required history for moving-average reaction computation."""
        self.addminperiod(self.p.ma_period)

    def next(self):
        """Compute per-bar price-change and dynamic reaction upper/lower levels."""
        price_change = float(self.data.close[0] - self.data.open[0])
        self.lines.price_change[0] = price_change
        if len(self) < self.p.ma_period:
            self.lines.upper_level[0] = float("nan")
            self.lines.lower_level[0] = float("nan")
            return
        total = 0.0
        for i in range(self.p.ma_period):
            total += abs(float(self.data.close[-i] - self.data.open[-i]))
        dcl = (total / float(self.p.ma_period)) * float(self.p.coefficient)
        self.lines.upper_level[0] = dcl
        self.lines.lower_level[0] = -dcl
