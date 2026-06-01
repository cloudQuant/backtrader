#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import (
    Indicator,
    WeightedMovingAverage,
)

__all__ = [
    "AbsolutelyNoLagLwma",
]


class AbsolutelyNoLagLwma(Indicator):
    """Compute a low-lag LWMA proxy based on nested weighted moving averages."""

    lines = ("value",)
    params = (("length", 7),)

    def __init__(self):
        """Create line value from weighted moving average and set minimum period."""
        period = max(2, int(self.p.length))
        self.lines.value = WeightedMovingAverage(self.data.close, period=period)
        self.addminperiod(period + 2)
