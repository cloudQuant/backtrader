#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import Indicator

__all__ = [
    "CandleStopColor",
]


class CandleStopColor(Indicator):
    """Indicator computing highest-high/ lowest-low trailing stop channels with color breakout signal."""

    lines = ("color_idx", "upper", "lower")
    params = (
        ("up_trail_periods", 5),
        ("up_trail_shift", 5),
        ("dn_trail_periods", 5),
        ("dn_trail_shift", 5),
    )

    def next(self):
        """Compute trailing high/low range and set color index based on close position."""
        hh_indices = range(self.p.up_trail_shift, self.p.up_trail_shift + self.p.up_trail_periods)
        ll_indices = range(self.p.dn_trail_shift, self.p.dn_trail_shift + self.p.dn_trail_periods)
        highs = [float(self.data.high[-idx]) for idx in hh_indices if len(self.data) > idx]
        lows = [float(self.data.low[-idx]) for idx in ll_indices if len(self.data) > idx]
        if not highs or not lows:
            self.lines.color_idx[0] = 4.0
            return
        upper = max(highs)
        lower = min(lows)
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
