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
    "PercentEnvelope",
]


class PercentEnvelope(Indicator):
    """Percent envelope built from a moving-average midpoint."""

    lines = ("top", "bot")
    params = (
        ("period", 14),
        ("perc", 1.0),
    )

    def __init__(self):
        """Initialize MA and enforce minimum lookback warm-up."""
        self.ma = SimpleMovingAverage(self.data, period=int(self.p.period))
        self.addminperiod(int(self.p.period))

    def next(self):
        """Update upper/lower envelope boundaries for the current bar."""
        offset = float(self.p.perc) / 100.0
        ma = float(self.ma[0])
        self.lines.top[0] = ma * (1.0 + offset)
        self.lines.bot[0] = ma * (1.0 - offset)
