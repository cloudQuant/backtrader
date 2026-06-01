#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import (
    Indicator,
    SimpleMovingAverage,
    StandardDeviation,
    WeightedMovingAverage,
)

__all__ = [
    "MalrIndicator",
]


class MalrIndicator(Indicator):
    """Compute MALR trend channels used for breakout-trigger detection."""

    lines = ("malr", "malrh", "malrl", "malrhh", "malrll")
    params = (
        ("ma_period", 120),
        ("ma_shift", 0),
        ("channel_reversal", 1.1),
        ("channel_breakout", 1.1),
    )

    def __init__(self):
        """Initialize MA basis and channel deviation buffers."""
        sma = SimpleMovingAverage(self.data.close, period=self.p.ma_period)
        lwma = WeightedMovingAverage(self.data.close, period=self.p.ma_period)
        self._ff = 3.0 * lwma - 2.0 * sma
        diff = self.data.close - self._ff
        self._std = StandardDeviation(diff, period=self.p.ma_period)
        self.addminperiod(int(self.p.ma_period) * 2 + 3)

    def next(self):
        """Calculate MALR center and channel boundaries for the current bar."""
        ff = float(self._ff[0])
        std = float(self._std[0])
        t1 = std * float(self.p.channel_reversal)
        t2 = std * (float(self.p.channel_reversal) + float(self.p.channel_breakout))
        self.lines.malr[0] = ff
        self.lines.malrh[0] = ff + t1
        self.lines.malrl[0] = ff - t1
        self.lines.malrhh[0] = ff + t2
        self.lines.malrll[0] = ff - t2

    def once(self, start, end):
        """Vectorized computation path for backtesting efficiency."""
        ff_array = self._ff.array
        std_array = self._std.array
        lines = (
            self.lines.malr.array,
            self.lines.malrh.array,
            self.lines.malrl.array,
            self.lines.malrhh.array,
            self.lines.malrll.array,
        )
        for line in lines:
            while len(line) < end:
                line.append(float("nan"))

        actual_end = min(end, len(ff_array), len(std_array))
        for i in range(start, actual_end):
            ff = float(ff_array[i])
            std = float(std_array[i])
            t1 = std * float(self.p.channel_reversal)
            t2 = std * (float(self.p.channel_reversal) + float(self.p.channel_breakout))
            lines[0][i] = ff
            lines[1][i] = ff + t1
            lines[2][i] = ff - t1
            lines[3][i] = ff + t2
            lines[4][i] = ff - t2
