#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import (
    Highest,
    Indicator,
    Lowest,
)

__all__ = [
    "ColorMetroWprIndicator",
]


class ColorMetroWprIndicator(Indicator):
    """ColorMETRO step lines (fast/slow NRTR) computed over Williams %R."""

    lines = ("fast_line", "slow_line", "wpr_shifted")
    params = (
        ("period_wpr", 7),
        ("step_size_fast", 5),
        ("step_size_slow", 15),
    )

    def __init__(self):
        """Build the Highest/Lowest sub-indicators and reset NRTR step state."""
        period = int(self.p.period_wpr)
        self.highest = Highest(self.data.high, period=period)
        self.lowest = Lowest(self.data.low, period=period)
        self.addminperiod(period + 3)
        self._fmin1 = 999999.0
        self._fmax1 = -999999.0
        self._smin1 = 999999.0
        self._smax1 = -999999.0
        self._ftrend = 0
        self._strend = 0

    def next(self):
        """Update the fast and slow NRTR step lines from the current %R value."""
        highest = float(self.highest[0])
        lowest = float(self.lowest[0])
        close = float(self.data.close[0])
        span = highest - lowest
        wpr0 = 50.0 if span == 0 else 100.0 * (close - lowest) / span
        fmax0 = wpr0 + 2.0 * float(self.p.step_size_fast)
        fmin0 = wpr0 - 2.0 * float(self.p.step_size_fast)
        if wpr0 > self._fmax1:
            self._ftrend = 1
        if wpr0 < self._fmin1:
            self._ftrend = -1
        if self._ftrend > 0 and fmin0 < self._fmin1:
            fmin0 = self._fmin1
        if self._ftrend < 0 and fmax0 > self._fmax1:
            fmax0 = self._fmax1
        smax0 = wpr0 + 2.0 * float(self.p.step_size_slow)
        smin0 = wpr0 - 2.0 * float(self.p.step_size_slow)
        if wpr0 > self._smax1:
            self._strend = 1
        if wpr0 < self._smin1:
            self._strend = -1
        if self._strend > 0 and smin0 < self._smin1:
            smin0 = self._smin1
        if self._strend < 0 and smax0 > self._smax1:
            smax0 = self._smax1
        fast_line = (
            fmin0 + float(self.p.step_size_fast)
            if self._ftrend > 0
            else fmax0 - float(self.p.step_size_fast)
        )
        slow_line = (
            smin0 + float(self.p.step_size_slow)
            if self._strend > 0
            else smax0 - float(self.p.step_size_slow)
        )
        self.lines.fast_line[0] = fast_line
        self.lines.slow_line[0] = slow_line
        self.lines.wpr_shifted[0] = wpr0
        self._fmin1 = fmin0
        self._fmax1 = fmax0
        self._smin1 = smin0
        self._smax1 = smax0
