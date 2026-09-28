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
    "BullsBearsEyes",
]


class BullsBearsEyes(Indicator):
    """Rebuild a signal oscillator from recursive smoothed directional momentum."""

    lines = ("value",)
    params = (
        ("period", 13),
        ("gamma", 0.6),
    )

    def __init__(self):
        """Initialize EMA and recursive helper state used by the indicator."""
        self.ema = ExponentialMovingAverage(self.data.close, period=int(self.p.period))
        self.addminperiod(int(self.p.period) + 5)
        self._l0 = 0.0
        self._l1 = 0.0
        self._l2 = 0.0
        self._l3 = 0.0

    def next(self):
        """Compute the next recursive signal value and write it to ``lines.value``."""
        bulls = float(self.data.high[0] - self.ema[0])
        bears = float(self.data.low[0] - self.ema[0])
        gamma = float(self.p.gamma)
        l0a = self._l0
        l1a = self._l1
        l2a = self._l2
        l3a = self._l3
        l0 = (1.0 - gamma) * (bears + bulls) + gamma * l0a
        l1 = -gamma * l0 + l0a + gamma * l1a
        l2 = -gamma * l1 + l1a + gamma * l2a
        l3 = -gamma * l2 + l2a + gamma * l3a
        cu = 0.0
        cd = 0.0
        if l0 >= l1:
            cu += l0 - l1
        else:
            cd += l1 - l0
        if l1 >= l2:
            cu += l1 - l2
        else:
            cd += l2 - l1
        if l2 >= l3:
            cu += l2 - l3
        else:
            cd += l3 - l2
        self.lines.value[0] = cu / (cu + cd) if (cu + cd) != 0.0 else 0.0
        self._l0 = l0
        self._l1 = l1
        self._l2 = l2
        self._l3 = l3
