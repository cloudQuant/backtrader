#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import Indicator

__all__ = [
    "IAMMAIndicator",
]


class IAMMAIndicator(Indicator):
    """Indicator implementation of i-AMMA value progression."""

    lines = ("value",)
    params = (
        ("ma_period", 25),
        ("price_shift", 0),
        ("point", 0.01),
    )

    def __init__(self):
        """Initialize i-AMMA offset and minimum startup bars."""
        self.price_offset = float(self.p.point) * float(self.p.price_shift)
        self.addminperiod(2)

    def next(self):
        """Compute adaptive MA value for current bar."""
        if len(self) == 1:
            self.l.value[0] = float(self.data.close[0])
            return
        period = max(int(self.p.ma_period), 1)
        prev = float(self.l.value[-1])
        price = float(self.data.close[0])
        amma = (((period - 1) * (prev - self.price_offset)) + price) / period
        self.l.value[0] = amma + self.price_offset
