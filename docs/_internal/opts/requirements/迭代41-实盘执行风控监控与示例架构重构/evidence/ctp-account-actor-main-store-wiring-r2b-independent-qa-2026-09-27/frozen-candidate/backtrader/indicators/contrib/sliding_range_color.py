#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import Indicator

__all__ = [
    "SlidingRangeColor",
]


class SlidingRangeColor(Indicator):
    """Indicator computing sliding-window average range channels with a color index for breakout direction."""

    lines = ("color_idx", "upper", "lower")
    params = (
        ("up_calc_period_range", 5),
        ("up_calc_period_shift", 0),
        ("dn_calc_period_range", 5),
        ("dn_calc_period_shift", 0),
        ("up_digit", 2),
        ("dn_digit", 2),
    )

    def next(self):
        """Compute rounded average of recent highs/lows and set color based on close relative to the range."""
        up_end = len(self.data) - 1 - self.p.up_calc_period_shift
        up_start = max(0, up_end - self.p.up_calc_period_range + 1)
        dn_end = len(self.data) - 1 - self.p.dn_calc_period_shift
        dn_start = max(0, dn_end - self.p.dn_calc_period_range + 1)
        highs = [
            float(self.data.high[-idx])
            for idx in range(len(self.data) - 1 - up_end, len(self.data) - up_start)
        ]
        lows = [
            float(self.data.low[-idx])
            for idx in range(len(self.data) - 1 - dn_end, len(self.data) - dn_start)
        ]
        if not highs or not lows:
            self.lines.color_idx[0] = 4.0
            return
        upper = round(sum(highs) / len(highs), self.p.up_digit)
        lower = round(sum(lows) / len(lows), self.p.dn_digit)
        close = float(self.data.close[0])
        open_ = float(self.data.open[0])
        self.lines.upper[0] = upper
        self.lines.lower[0] = lower
        color = 4.0
        if close > upper:
            color = 3.0 if close >= open_ else 2.0
        elif close < lower:
            color = 0.0 if close <= open_ else 1.0
        self.lines.color_idx[0] = color
