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
    "JTpoProxy",
]


class JTpoProxy(Indicator):
    """Proxy oscillator measuring close deviation from its moving average."""

    lines = ("value",)
    params = (("period", 14),)

    def __init__(self):
        """Set up the SMA and minimum period from the period parameter."""
        self.period = max(2, int(self.p.period))
        self.ma = SimpleMovingAverage(self.data.close, period=self.period)
        self.addminperiod(self.period + 1)

    def next(self):
        """Compute the current close-minus-SMA deviation value."""
        self.lines.value[0] = float(self.data.close[0]) - float(self.ma[0])
