#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import (
    EMA,
    Indicator,
)

__all__ = [
    "T3Indicator",
]


class T3Indicator(Indicator):
    """Tillson T3 moving average — six cascaded EMAs with volume factor."""

    lines = ("t3",)
    params = (
        ("period", 4),
        ("vfactor", 0.7),
    )

    def __init__(self):
        """Build the six cascaded EMAs and the T3 weighted combination line."""
        e1 = EMA(self.data, period=self.p.period)
        e2 = EMA(e1, period=self.p.period)
        e3 = EMA(e2, period=self.p.period)
        e4 = EMA(e3, period=self.p.period)
        e5 = EMA(e4, period=self.p.period)
        e6 = EMA(e5, period=self.p.period)
        v = self.p.vfactor
        c1 = -(v * v * v)
        c2 = 3 * v * v + 3 * v * v * v
        c3 = -6 * v * v - 3 * v - 3 * v * v * v
        c4 = 1 + 3 * v + v * v * v + 3 * v * v
        self.lines.t3 = c1 * e6 + c2 * e5 + c3 * e4 + c4 * e3
