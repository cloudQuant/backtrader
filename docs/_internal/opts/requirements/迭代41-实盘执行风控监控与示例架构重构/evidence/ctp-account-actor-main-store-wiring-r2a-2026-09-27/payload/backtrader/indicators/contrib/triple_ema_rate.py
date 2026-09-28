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
    "TripleEmaRate",
]


class TripleEmaRate(Indicator):
    """TRIX: the bar-over-bar rate of change of a triple-smoothed EMA."""

    lines = ("value",)
    params = (("period", 14),)

    def __init__(self):
        """Build the three chained EMAs and set the minimum warm-up period."""
        self.ema1 = EMA(self.data, period=self.p.period)
        self.ema2 = EMA(self.ema1, period=self.p.period)
        self.ema3 = EMA(self.ema2, period=self.p.period)
        self.addminperiod(self.p.period * 3 + 2)

    def next(self):
        """Emit the fractional change of the triple EMA versus the prior bar."""
        prev = float(self.ema3[-1])
        self.lines.value[0] = (float(self.ema3[0]) - prev) / prev if prev else 0.0
