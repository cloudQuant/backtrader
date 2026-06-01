#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import Indicator

__all__ = [
    "KDJIndicator",
]


class KDJIndicator(Indicator):
    """Indicator class implementing the custom KDJ oscillator.

    Lines:
        kdc (Line): Output difference line (%K - %D).
        rsv (Line): Raw Stochastic Value line.
        k (Line): Smoothed %K line.
        d (Line): Smoothed %D line.
    """

    lines = ("kdc", "rsv", "k", "d")
    params = (
        ("m1", 3),
        ("m2", 6),
        ("kdj_period", 30),
    )

    def __init__(self):
        """Initialize the custom KDJ indicator and establish minimum warmup period."""
        self.addminperiod(int(self.p.kdj_period) + int(self.p.m2) + 2)

    def next(self):
        """Calculate RSV, %K, %D, and %K-%D values on each new bar."""
        kdj_period = int(self.p.kdj_period)
        m1 = int(self.p.m1)
        m2 = int(self.p.m2)
        highs = [float(self.data.high[-i]) for i in range(kdj_period)]
        lows = [float(self.data.low[-i]) for i in range(kdj_period)]
        max_high = max(highs)
        min_low = min(lows)
        if max_high - min_low != 0.0:
            self.lines.rsv[0] = (float(self.data.close[0]) - min_low) / (max_high - min_low) * 100.0
        else:
            self.lines.rsv[0] = 1.0
        rsv_values = []
        for i in range(m1):
            value = float(self.lines.rsv[-i]) if len(self) > i else 50.0
            rsv_values.append(value)
        self.lines.k[0] = sum(rsv_values) / float(m1)
        k_values = []
        for i in range(m2):
            value = float(self.lines.k[-i]) if len(self) > i else 50.0
            k_values.append(value)
        self.lines.d[0] = sum(k_values) / float(m2)
        self.lines.kdc[0] = float(self.lines.k[0]) - float(self.lines.d[0])
