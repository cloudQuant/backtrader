#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import Indicator

__all__ = [
    "RKDIndicator",
]


class RKDIndicator(Indicator):
    """Compute a custom RKD line set from RSV/K/D values."""

    lines = ("rsv", "k", "d")
    params = (
        ("kd_period", 30),
        ("m1", 3),
        ("m2", 6),
    )

    def __init__(self):
        """Define indicator warm-up length before valid line updates."""
        self.addminperiod(max(int(self.p.kd_period), int(self.p.m1), int(self.p.m2)) + 2)

    def next(self):
        """Update RSV, K, and D for the latest bar."""
        kd_period = int(self.p.kd_period)
        m1 = int(self.p.m1)
        m2 = int(self.p.m2)
        highs = [float(self.data.high[-i]) for i in range(kd_period)]
        lows = [float(self.data.low[-i]) for i in range(kd_period)]
        max_high = max(highs)
        min_low = min(lows)
        denom = max_high - min_low
        if denom == 0:
            rsv = 0.0
        else:
            rsv = (float(self.data.close[0]) - min_low) / denom * 100.0
        self.lines.rsv[0] = rsv

        if len(self) < m1:
            self.lines.k[0] = 0.0
        else:
            self.lines.k[0] = sum(float(self.lines.rsv[-i]) for i in range(m1)) / m1

        if len(self) < m2:
            self.lines.d[0] = 0.0
        else:
            self.lines.d[0] = sum(float(self.lines.k[-i]) for i in range(m2)) / m2
