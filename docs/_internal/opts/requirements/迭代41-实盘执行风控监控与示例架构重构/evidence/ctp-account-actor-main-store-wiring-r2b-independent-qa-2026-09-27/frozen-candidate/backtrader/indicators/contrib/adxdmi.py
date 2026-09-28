#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import (
    Indicator,
    MinusDirectionalIndicator,
    PlusDirectionalIndicator,
)

__all__ = [
    "ADXDMI",
]


class ADXDMI(Indicator):
    """DMI direction indicator exposing plus/minus directional values."""

    lines = ("plus", "minus")
    params = (("period", 14),)

    def __init__(self):
        """Initialize plus and minus directional sub-indicators."""
        self.addminperiod(int(self.p.period) + 3)
        self.plus_di = PlusDirectionalIndicator(self.data, period=int(self.p.period))
        self.minus_di = MinusDirectionalIndicator(self.data, period=int(self.p.period))

    def next(self):
        """Write current directional index values to output lines."""
        self.lines.plus[0] = float(self.plus_di[0])
        self.lines.minus[0] = float(self.minus_di[0])
