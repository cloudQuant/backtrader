#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

import math

from .. import Indicator

__all__ = [
    "XFisherIndicator",
]


class XFisherIndicator(Indicator):
    """Fisher Transform of Williams %R position with an EMA-smoothed signal line."""

    lines = ("xfisher", "signal")
    params = (
        ("flength", 7),
        ("ma_length", 5),
    )

    def __init__(self):
        """Set the warm-up period, recurrence seeds, and EMA smoothing factor."""
        self.addminperiod(self.p.flength + self.p.ma_length + 2)
        self._value_prev = 0.0
        self._fish_prev = 0.0
        self._smooth_prev = None
        self._alpha = 2.0 / (self.p.ma_length + 1.0)

    def next(self):
        """Compute the smoothed Fisher value and store it with its lagged signal."""
        highs = [float(self.data.high[-i]) for i in range(self.p.flength)]
        lows = [float(self.data.low[-i]) for i in range(self.p.flength)]
        smax = max(highs)
        smin = min(lows)
        spread = smax - smin
        if spread == 0:
            spread = 1e-12

        price = float(self.data.close[0])
        wpr = (price - smin) / spread
        value = (wpr - 0.5) + 0.67 * self._value_prev
        value = max(min(value, 0.999), -0.999)

        ratio = (1.0 + value) / (1.0 - value)
        ratio = max(ratio, 1e-7)
        fish = 0.5 * math.log(ratio) + 0.5 * self._fish_prev
        smooth = (
            fish
            if self._smooth_prev is None
            else self._smooth_prev + self._alpha * (fish - self._smooth_prev)
        )

        prev_smooth = smooth if len(self) <= 1 else float(self.lines.xfisher[-1])
        self.lines.xfisher[0] = smooth
        self.lines.signal[0] = prev_smooth

        self._value_prev = value
        self._fish_prev = fish
        self._smooth_prev = smooth
