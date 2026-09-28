#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import Indicator

__all__ = [
    "LaguerreFilterIndicator",
]


class LaguerreFilterIndicator(Indicator):
    """Laguerre smoothing indicator with finite impulse response fallback lines."""

    lines = ("laguerre", "fir")
    params = (("gamma", 0.7),)

    def __init__(self):
        """Initialize internal Laguerre filter state and warm-up requirements."""
        self.addminperiod(4)
        self._l0 = None
        self._l1 = None
        self._l2 = None
        self._l3 = None

    def _price(self, ago=0):
        return (float(self.data.high[ago]) + float(self.data.low[ago])) / 2.0

    def next(self):
        """Compute current Laguerre and FIR values for the current bar."""
        price = self._price(0)
        if self._l0 is None:
            self._l0 = price
            self._l1 = price
            self._l2 = price
            self._l3 = price
            self.lines.laguerre[0] = price
            self.lines.fir[0] = price
            return
        l0a = self._l0
        l1a = self._l1
        l2a = self._l2
        l3a = self._l3
        gamma = float(self.p.gamma)
        l0 = (1.0 - gamma) * price + gamma * l0a
        l1 = -gamma * l0 + l0a + gamma * l1a
        l2 = -gamma * l1 + l1a + gamma * l2a
        l3 = -gamma * l2 + l2a + gamma * l3a
        self._l0 = l0
        self._l1 = l1
        self._l2 = l2
        self._l3 = l3
        if len(self) > 4:
            self.lines.laguerre[0] = (l0 + 2.0 * l1 + 2.0 * l2 + l3) / 6.0
            self.lines.fir[0] = (
                1.0 * self._price(0)
                + 2.0 * self._price(-1)
                + 2.0 * self._price(-2)
                + 1.0 * self._price(-3)
            ) / 6.0
        else:
            self.lines.laguerre[0] = price
            self.lines.fir[0] = price
