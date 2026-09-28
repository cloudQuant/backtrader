#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import Indicator

__all__ = [
    "StarterLaguerreFilter",
]


class StarterLaguerreFilter(Indicator):
    """Laguerre filter oscillator bounded in the [0, 1] range.

    Implements Ehlers' four-stage Laguerre filter and converts the staged
    values into a normalised oscillator. Readings near 0 indicate oversold
    conditions and readings near 1 indicate overbought conditions.
    """

    lines = ("value",)
    params = (("gamma", 0.7),)

    def __init__(self):
        """Set the minimum period and reset the four Laguerre stage buffers."""
        self.addminperiod(2)
        self._l0 = None
        self._l1 = None
        self._l2 = None
        self._l3 = None

    def next(self):
        """Advance the Laguerre stages and emit the normalised oscillator value."""
        price = float(self.data[0])
        gamma = float(self.p.gamma)
        if self._l0 is None:
            self._l0 = price
            self._l1 = price
            self._l2 = price
            self._l3 = price
            self.lines.value[0] = 0.5
            return
        l0_prev = self._l0
        l1_prev = self._l1
        l2_prev = self._l2
        l3_prev = self._l3
        self._l0 = (1.0 - gamma) * price + gamma * l0_prev
        self._l1 = -gamma * self._l0 + l0_prev + gamma * l1_prev
        self._l2 = -gamma * self._l1 + l1_prev + gamma * l2_prev
        self._l3 = -gamma * self._l2 + l2_prev + gamma * l3_prev
        cu = 0.0
        cd = 0.0
        pairs = ((self._l0, self._l1), (self._l1, self._l2), (self._l2, self._l3))
        for left, right in pairs:
            if left >= right:
                cu += left - right
            else:
                cd += right - left
        denom = cu + cd
        self.lines.value[0] = cu / denom if denom else self.lines.value[-1]
