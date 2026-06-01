#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

import math

from .. import (
    Highest,
    Indicator,
    Lowest,
    WeightedMovingAverage,
)

__all__ = [
    "UltraAbsolutelyNoLagLwmaColor",
]


class UltraAbsolutelyNoLagLwmaColor(Indicator):
    """Low-lag LWMA range-position oscillator emitting bulls/bears and color.

    Positions a smoothed weighted moving average within its recent high/low
    range to produce bulls/bears strength lines and a color state encoding their
    dominance and slope across configurable up/down levels.
    """

    lines = ("bulls", "bears", "color_idx")
    params = (
        ("flength", 7),
        ("start_length", 5),
        ("pstep", 2),
        ("psteps_total", 10),
        ("smooth_length", 3),
        ("up_level", 80.0),
        ("dn_level", 20.0),
    )

    def __init__(self):
        """Build the range high/low and smoothing averages, set min period."""
        lookback = max(
            self.p.flength * 2,
            self.p.start_length + self.p.pstep * self.p.psteps_total,
            self.p.smooth_length + 2,
        )
        self.range_high = Highest(self.data.high, period=max(2, self.p.flength * 2))
        self.range_low = Lowest(self.data.low, period=max(2, self.p.flength * 2))
        self.smooth_close = WeightedMovingAverage(
            self.data.close, period=max(2, self.p.start_length + self.p.pstep)
        )
        self.smooth_signal = WeightedMovingAverage(
            self.smooth_close, period=max(2, self.p.smooth_length)
        )
        self.addminperiod(lookback + 2)

    def next(self):
        """Compute bulls/bears strengths and the color state for this bar."""
        high = float(self.range_high[0])
        low = float(self.range_low[0])
        spread = high - low
        if spread <= 0:
            bulls = 50.0
        else:
            bulls = (float(self.smooth_close[0]) - low) / spread * 100.0
        bulls = max(0.0, min(100.0, bulls))
        bears = 100.0 - bulls
        self.lines.bulls[0] = bulls
        self.lines.bears[0] = bears
        prev_bulls = (
            float(self.lines.bulls[-1])
            if len(self) > 1 and math.isfinite(float(self.lines.bulls[-1]))
            else bulls
        )
        prev_bears = (
            float(self.lines.bears[-1])
            if len(self) > 1 and math.isfinite(float(self.lines.bears[-1]))
            else bears
        )
        color = 0.0
        if bulls > bears:
            if bulls > self.p.up_level or bears < self.p.dn_level:
                color = 7.0 if prev_bulls <= bulls else 8.0
            else:
                color = 5.0 if prev_bulls <= bulls else 6.0
        elif bulls < bears:
            if bulls < self.p.dn_level or bears > self.p.up_level:
                color = 1.0 if prev_bears <= bears else 2.0
            else:
                color = 3.0 if prev_bears <= bears else 4.0
        self.lines.color_idx[0] = color
