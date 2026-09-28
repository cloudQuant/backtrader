#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

import math

from .. import Indicator

__all__ = [
    "ColorHMA",
]


def _weighted_ma(values):
    weights = list(range(1, len(values) + 1))
    denominator = float(sum(weights))
    return sum(value * weight for value, weight in zip(values, weights)) / denominator


class ColorHMA(Indicator):
    """Hull Moving Average line plus its slope-direction ("color") line."""

    lines = ("hma", "direction")
    params = (("period", 13),)

    def __init__(self):
        """Derive the half, full, and sqrt periods and set the warmup window."""
        self.period = max(int(self.p.period), 2)
        self.half_period = max(int(math.floor(self.period / 2.0)), 1)
        self.sqrt_period = max(int(math.floor(math.sqrt(self.period))), 1)
        self._dma_history = []
        self.addminperiod(self.period + self.sqrt_period + 2)

    def _window(self, length):
        return [float(self.data[-idx]) for idx in range(length - 1, -1, -1)]

    def next(self):
        """Compute the HMA value for this bar and update its slope direction."""
        if len(self.data) < self.period:
            current = (
                float(self.data.close[0]) if hasattr(self.data, "close") else float(self.data[0])
            )
            self._dma_history.append(current)
            self.l.hma[0] = current
            self.l.direction[0] = 0.0
            return

        half_values = self._window(self.half_period)
        full_values = self._window(self.period)
        lwma_half = _weighted_ma(half_values)
        lwma_full = _weighted_ma(full_values)
        dma = 2.0 * lwma_half - lwma_full
        self._dma_history.append(dma)

        if len(self._dma_history) >= self.sqrt_period:
            hma = _weighted_ma(self._dma_history[-self.sqrt_period :])
        else:
            hma = dma

        self.l.hma[0] = hma
        if len(self) < 2:
            self.l.direction[0] = 0.0
        elif self.l.hma[-1] < self.l.hma[0]:
            self.l.direction[0] = 1.0
        elif self.l.hma[-1] > self.l.hma[0]:
            self.l.direction[0] = -1.0
        else:
            self.l.direction[0] = self.l.direction[-1]
