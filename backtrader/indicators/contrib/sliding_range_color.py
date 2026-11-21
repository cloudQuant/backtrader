#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

import math

from ...linebuffer import _reject_factor_infinity
from .. import Indicator

__all__ = [
    "SlidingRangeColor",
]


class SlidingRangeColor(Indicator):
    """Average range channels and breakout color; missing inputs yield NaN color."""

    lines = ("color_idx", "upper", "lower")
    params = (
        ("up_calc_period_range", 5),
        ("up_calc_period_shift", 0),
        ("dn_calc_period_range", 5),
        ("dn_calc_period_shift", 0),
        ("up_digit", 2),
        ("dn_digit", 2),
    )

    def qbuffer(self, savemem=0):
        """Retain input history without delaying the partial-window output."""
        super().qbuffer(savemem=savemem)
        lookback = max(
            1,
            self.p.up_calc_period_shift + self.p.up_calc_period_range,
            self.p.dn_calc_period_shift + self.p.dn_calc_period_range,
        )
        self.data.minbuffer(lookback)

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
        close = float(self.data.close[0])
        open_ = float(self.data.open[0])
        for value in (open_, close, *highs, *lows):
            if math.isinf(value):
                _reject_factor_infinity(self.lines.color_idx, value)
        if not highs or not lows:
            self.lines.upper[0] = float("nan")
            self.lines.lower[0] = float("nan")
            self.lines.color_idx[0] = (
                4.0 if all(math.isfinite(x) for x in (open_, close, *highs, *lows))
                else float("nan")
            )
            return
        high_sum = sum(highs) if all(math.isfinite(x) for x in highs) else float("nan")
        low_sum = sum(lows) if all(math.isfinite(x) for x in lows) else float("nan")
        for value in (high_sum, low_sum):
            if math.isinf(value):
                _reject_factor_infinity(self.lines.color_idx, value)
        upper = round(high_sum / len(highs), self.p.up_digit)
        lower = round(low_sum / len(lows), self.p.dn_digit)
        self.lines.upper[0] = upper
        self.lines.lower[0] = lower
        if not all(math.isfinite(x) for x in (open_, close, upper, lower)):
            self.lines.color_idx[0] = float("nan")
            return
        color = 4.0
        if close > upper:
            color = 3.0 if close >= open_ else 2.0
        elif close < lower:
            color = 0.0 if close <= open_ else 1.0
        self.lines.color_idx[0] = color
