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
    "EnvelopesJpAlonso",
]


class EnvelopesJpAlonso(Indicator):
    """Compute static upper/lower envelope bands around a simple moving average."""

    lines = ("mid", "upper", "lower")
    params = (
        ("period", 200),
        ("deviation", 0.35),
    )

    def __init__(self):
        """Initialize envelope lines from the configured SMA period and deviation."""
        self.lines.mid = SimpleMovingAverage(self.data.close, period=self.p.period)
        ratio = float(self.p.deviation) / 100.0
        self.lines.upper = self.lines.mid * (1.0 + ratio)
        self.lines.lower = self.lines.mid * (1.0 - ratio)
