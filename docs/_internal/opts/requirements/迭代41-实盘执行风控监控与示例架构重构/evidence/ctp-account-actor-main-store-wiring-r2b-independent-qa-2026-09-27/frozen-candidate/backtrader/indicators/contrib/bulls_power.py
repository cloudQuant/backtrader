#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import (
    ExponentialMovingAverage,
    Indicator,
)

__all__ = [
    "BullsPower",
    "BearsPower",
]


class BullsPower(Indicator):
    """Indicator for Bulls Power built from high price minus EMA."""

    lines = ("value",)
    params = (("period", 5),)

    def __init__(self):
        """Initialize EMA and minimum period.

        Args:
            self: Instance reference.
        """
        self.ema = ExponentialMovingAverage(self.data.close, period=self.p.period)
        self.addminperiod(self.p.period + 3)

    def next(self):
        """Update current Bulls Power value."""
        self.lines.value[0] = float(self.data.high[0]) - float(self.ema[0])


class BearsPower(Indicator):
    """Indicator for Bears Power built from low price minus EMA."""

    lines = ("value",)
    params = (("period", 5),)

    def __init__(self):
        """Initialize EMA and minimum period.

        Args:
            self: Instance reference.
        """
        self.ema = ExponentialMovingAverage(self.data.close, period=self.p.period)
        self.addminperiod(self.p.period + 3)

    def next(self):
        """Update current Bears Power value."""
        self.lines.value[0] = float(self.data.low[0]) - float(self.ema[0])
