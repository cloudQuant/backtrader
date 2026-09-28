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
    "Wami",
]


class Wami(Indicator):
    """Calculate a WAMI-style oscillator and signal line from close-price MAs."""

    lines = ("wami", "signal")
    params = (
        ("period_ma1", 4),
        ("period_ma2", 13),
        ("period_ma3", 13),
        ("period_sig", 4),
        ("point_size", 0.01),
    )

    def __init__(self):
        """Initialize WAMI indicator stages and output lines."""
        base_ma = SimpleMovingAverage(self.data.close, period=1)
        diff = base_ma - base_ma(-1)
        ma1 = SimpleMovingAverage(diff, period=self.p.period_ma1)
        ma2 = SimpleMovingAverage(ma1, period=self.p.period_ma2)
        ma3 = SimpleMovingAverage(ma2, period=self.p.period_ma3)
        sig = SimpleMovingAverage(ma3, period=self.p.period_sig)
        scale = self.p.point_size if self.p.point_size else 1.0
        self.lines.wami = ma3 / scale
        self.lines.signal = sig / scale
        self.addminperiod(
            1 + self.p.period_ma1 + self.p.period_ma2 + self.p.period_ma3 + self.p.period_sig
        )
