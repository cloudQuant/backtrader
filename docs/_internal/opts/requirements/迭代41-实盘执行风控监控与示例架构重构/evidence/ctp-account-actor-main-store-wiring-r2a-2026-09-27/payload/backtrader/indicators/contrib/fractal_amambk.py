#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

import math

from .. import Indicator

__all__ = [
    "FractalAMAMBK",
]


class FractalAMAMBK(Indicator):
    """FRAMA-style indicator exposing smoothed trend and trigger lines."""

    lines = ("frama", "trigger")
    params = (
        ("r_period", 16),
        ("multiplier", 4.6),
        ("signal_multiplier", 2.5),
    )

    def __init__(self):
        """Set minimum period based on FRAMA computation window."""
        self.addminperiod(max(int(self.p.r_period), 2) + 2)

    def _range(self, high_line, low_line, start_shift, count):
        highs = [
            float(high_line[-shift]) if shift else float(high_line[0])
            for shift in range(start_shift, start_shift + count)
        ]
        lows = [
            float(low_line[-shift]) if shift else float(low_line[0])
            for shift in range(start_shift, start_shift + count)
        ]
        return max(highs) - min(lows)

    def next(self):
        """Compute FRAMA and trigger values for the current bar."""
        period = max(int(self.p.r_period), 2)
        n = (period // 2) * 2
        n2 = max(n // 2, 1)
        price = float(self.data.close[0])

        if len(self.data) <= n:
            self.l.frama[0] = price
            self.l.trigger[0] = price
            return

        r1 = self._range(self.data.high, self.data.low, 0, n2) / n2
        r2 = self._range(self.data.high, self.data.low, n2, n2) / n2
        r3 = self._range(self.data.high, self.data.low, 0, n) / n

        if r3 <= 0 or (r1 + r2) <= 0:
            dimension_estimate = 1.0
        else:
            dimension_estimate = (math.log(r1 + r2) - math.log(r3)) * 1.442695

        alpha = math.exp(-float(self.p.multiplier) * (dimension_estimate - 1.0))
        alpha = min(max(alpha, 0.01), 1.0)
        alphas = math.exp(-float(self.p.signal_multiplier) * (dimension_estimate - 1.0))

        prev_frama = (
            float(self.l.frama[-1])
            if len(self.data) > 1 and math.isfinite(float(self.l.frama[-1]))
            else float(self.data.close[-1])
        )
        prev_trigger = (
            float(self.l.trigger[-1])
            if len(self.data) > 1 and math.isfinite(float(self.l.trigger[-1]))
            else prev_frama
        )

        frama = alpha * price + (1.0 - alpha) * prev_frama
        trigger = alphas * frama + (1.0 - alphas) * prev_trigger
        self.l.frama[0] = frama
        self.l.trigger[0] = trigger
