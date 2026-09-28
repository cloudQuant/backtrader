#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import Indicator

__all__ = [
    "CGOscillator",
]


class CGOscillator(Indicator):
    """Center of Gravity (CG) oscillator with a one-bar-lagged signal line.

    The main line is a length-weighted ratio of recent median prices, shifted
    to centre around zero. The signal line is the previous bar's main value.
    """

    lines = ("main", "signal")
    params = (("length", 10),)

    def __init__(self):
        """Set the minimum period and precompute the CG centring shift."""
        self.addminperiod(int(self.p.length) + 1)
        self.cgshift = (float(self.p.length) + 1.0) / 2.0

    def next(self):
        """Compute the CG main and lagged signal value for the current bar."""
        num = 0.0
        denom = 0.0
        length = int(self.p.length)
        for count in range(length):
            price = (float(self.data.high[-count]) + float(self.data.low[-count])) / 2.0
            num += (1.0 + count) * price
            denom += price
        self.lines.main[0] = (-num / denom + self.cgshift) if denom else 0.0
        self.lines.signal[0] = self.lines.main[-1] if len(self) > 1 else 0.0
