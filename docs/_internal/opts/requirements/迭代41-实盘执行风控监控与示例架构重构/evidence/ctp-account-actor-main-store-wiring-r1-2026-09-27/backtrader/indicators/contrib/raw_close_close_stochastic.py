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
    "RawCloseCloseStochastic",
    "CloseCloseEmaStochastic",
]


class RawCloseCloseStochastic(Indicator):
    """Raw close-based Stochastic (%K numerator) over a close-only window."""

    lines = ("raw",)
    params = (("period", 5),)

    def __init__(self):
        """Set the minimum period required before emitting values."""
        self.addminperiod(int(self.p.period))

    def next(self):
        """Compute the raw close-based Stochastic value for the current bar."""
        period = int(self.p.period)
        closes = [float(self.data.close[-i]) for i in range(period)]
        highest = max(closes)
        lowest = min(closes)
        denom = highest - lowest
        if denom == 0:
            self.lines.raw[0] = 0.0
            return
        self.lines.raw[0] = 100.0 * (float(self.data.close[0]) - lowest) / denom

    def once(self, start, end):
        """Vectorized raw close-based Stochastic over the array index range.

        Args:
            start: Start index (inclusive) of the range to compute.
            end: End index (exclusive) of the range to compute.
        """
        period = int(self.p.period)
        closes = self.data.close.array
        raw = self.lines.raw.array
        for i in range(start, end):
            window_start = max(0, i - period + 1)
            window = closes[window_start : i + 1]
            highest = max(window)
            lowest = min(window)
            denom = highest - lowest
            raw[i] = 0.0 if denom == 0 else 100.0 * (closes[i] - lowest) / denom


class CloseCloseEmaStochastic(Indicator):
    """EMA-smoothed close-based Stochastic exposing ``percK`` and ``percD``."""

    lines = ("percK", "percD")
    params = (
        ("period", 5),
        ("slowing", 3),
        ("dperiod", 3),
    )

    def __init__(self):
        """Build the EMA-smoothed %K and %D lines from the raw Stochastic."""
        raw = RawCloseCloseStochastic(self.data, period=int(self.p.period))
        self.lines.percK = ExponentialMovingAverage(raw, period=int(self.p.slowing))
        self.lines.percD = ExponentialMovingAverage(self.lines.percK, period=int(self.p.dperiod))
