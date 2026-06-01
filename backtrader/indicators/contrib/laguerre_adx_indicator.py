#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

import math

from .. import (
    Indicator,
    MinusDirectionalIndicator,
    PlusDirectionalIndicator,
)

__all__ = [
    "LaguerreAdxIndicator",
]


class LaguerreAdxIndicator(Indicator):
    """Laguerre-filtered ADX directional components built from +/- DI."""

    lines = ("up", "down")
    params = (
        ("adx_period", 14),
        ("gamma", 0.764),
    )

    def __init__(self):
        """Initialize DI inputs, laguerre states, and minimum period."""
        self.addminperiod(int(self.p.adx_period) + 5)
        self.plus_di = PlusDirectionalIndicator(self.data, period=int(self.p.adx_period))
        self.minus_di = MinusDirectionalIndicator(self.data, period=int(self.p.adx_period))
        self._p = {"l0": 0.0, "l1": 0.0, "l2": 0.0, "l3": 0.0}
        self._m = {"l0": 0.0, "l1": 0.0, "l2": 0.0, "l3": 0.0}

    def _laguerre_step(self, value, state, previous_output):
        gamma = float(self.p.gamma)
        l0a = state["l0"]
        l1a = state["l1"]
        l2a = state["l2"]
        l3a = state["l3"]
        l0 = (1.0 - gamma) * value + gamma * l0a
        l1 = -gamma * l0 + l0a + gamma * l1a
        l2 = -gamma * l1 + l1a + gamma * l2a
        l3 = -gamma * l2 + l2a + gamma * l3a
        state["l0"] = l0
        state["l1"] = l1
        state["l2"] = l2
        state["l3"] = l3
        cu = 0.0
        cd = 0.0
        if l0 >= l1:
            cu = l0 - l1
        else:
            cd = l1 - l0
        if l1 >= l2:
            cu += l1 - l2
        else:
            cd += l2 - l1
        if l2 >= l3:
            cu += l2 - l3
        else:
            cd += l3 - l2
        if cu + cd != 0.0:
            return cu / (cu + cd)
        return previous_output

    def next(self):
        """Compute smoothed up/down values from directional indicators."""
        prev_up = (
            float(self.lines.up[-1])
            if len(self) > 0 and math.isfinite(float(self.lines.up[-1]))
            else 0.0
        )
        prev_down = (
            float(self.lines.down[-1])
            if len(self) > 0 and math.isfinite(float(self.lines.down[-1]))
            else 0.0
        )
        plus_value = float(self.plus_di[0]) if math.isfinite(float(self.plus_di[0])) else 0.0
        minus_value = float(self.minus_di[0]) if math.isfinite(float(self.minus_di[0])) else 0.0
        self.lines.up[0] = self._laguerre_step(plus_value, self._p, prev_up)
        self.lines.down[0] = self._laguerre_step(minus_value, self._m, prev_down)
