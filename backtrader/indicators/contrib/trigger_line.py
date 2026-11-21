#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

import math

from .. import Indicator

__all__ = [
    "TriggerLine",
]


class TriggerLine(Indicator):
    """Trigger-line indicator tracking momentum-driven main and signal lines."""

    lines = ("main", "signal")
    params = (
        ("rperiod", 24),
        ("lsma_period", 6),
        ("price", "close"),
    )

    def __init__(self):
        """Initialize indicator coefficients and warmup."""
        self.addminperiod(int(self.p.rperiod) + 3)
        self.lengthvar = (int(self.p.rperiod) + 1) / 3.0
        self.kr = 6.0 / (float(self.p.rperiod) * (float(self.p.rperiod) + 1.0))
        self.klsma = 2.0 / (float(self.p.lsma_period) + 1.0)

    def _price(self, index=0):
        p = str(self.p.price).lower()
        if p == "open":
            return float(self.data.open[index])
        if p == "high":
            return float(self.data.high[index])
        if p == "low":
            return float(self.data.low[index])
        if p == "median":
            return (float(self.data.high[index]) + float(self.data.low[index])) / 2.0
        if p == "typical":
            return (
                float(self.data.high[index])
                + float(self.data.low[index])
                + float(self.data.close[index])
            ) / 3.0
        if p == "weighted":
            return (
                float(self.data.high[index])
                + float(self.data.low[index])
                + 2.0 * float(self.data.close[index])
            ) / 4.0
        return float(self.data.close[index])

    def _main_at(self, ago):
        """Calculate main directly from a price window ending ``ago`` bars back."""
        total = 0.0
        rp = int(self.p.rperiod)
        for iii in range(rp, 0, -1):
            idx = -(rp - iii + ago)
            total += (iii - self.lengthvar) * self._price(idx)
        return total * self.kr

    def next(self):
        """Compute main and signal values for current bar."""
        main = self._main_at(0)
        prev_main = float(self.lines.main[-1]) if len(self) > 1 else main
        if len(self) == self._minperiod and math.isnan(prev_main):
            # Default prenext does not populate main, although the input window
            # for the preceding bar is already available at the first next.
            prev_main = self._main_at(1)
        self.lines.main[0] = main
        self.lines.signal[0] = prev_main + (main - prev_main) * self.klsma
