#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import (
    Indicator,
    SimpleMovingAverage,
)

__all__ = [
    "CaudateXPeriodCandleColor",
]


class CaudateXPeriodCandleColor(Indicator):
    """Synthetic period-candle indicator emitting a color index and smoothed OHLC."""

    lines = ("color_idx", "xopen", "xclose", "xhigh", "xlow")
    params = (
        ("cperiod", 5),
        ("ma_length", 3),
    )

    def __init__(self):
        """Build the smoothed OHLC moving averages and set the warmup period."""
        self.smooth_open = SimpleMovingAverage(self.data.open, period=self.p.ma_length)
        self.smooth_high = SimpleMovingAverage(self.data.high, period=self.p.ma_length)
        self.smooth_low = SimpleMovingAverage(self.data.low, period=self.p.ma_length)
        self.smooth_close = SimpleMovingAverage(self.data.close, period=self.p.ma_length)
        self.addminperiod(self.p.ma_length + self.p.cperiod)

    def next(self):
        """Build the period candle and assign its color index from the midpoint."""
        lookback = max(1, int(self.p.cperiod))
        start = -(lookback - 1)
        xopen = float(self.smooth_open[start])
        xclose = float(self.smooth_close[0])
        highs = [float(self.smooth_high[-i]) for i in range(lookback)]
        lows = [float(self.smooth_low[-i]) for i in range(lookback)]
        xhigh = max(highs)
        xlow = min(lows)
        self.lines.xopen[0] = xopen
        self.lines.xclose[0] = xclose
        self.lines.xhigh[0] = xhigh
        self.lines.xlow[0] = xlow

        color = 2.0 if xopen <= xclose else 4.0
        candle_half = (xhigh + xlow) / 2.0
        if xopen > candle_half and xclose > candle_half:
            color = 0.0 if xopen <= xclose else 1.0
        elif xopen < candle_half and xclose < candle_half:
            color = 6.0 if xopen >= xclose else 5.0
        self.lines.color_idx[0] = color
