#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import Indicator

__all__ = [
    "VWMADigitSystem",
]


class VWMADigitSystem(Indicator):
    """Digit-rounded volume-weighted band color indicator.

    Builds digit-rounded volume-weighted high and low levels over ``length``
    bars and emits a ``color`` line encoding whether the close breaks above the
    upper level or below the lower level, combined with candle direction.
    """

    lines = ("color",)
    params = (
        ("length", 12),
        ("digit", 2),
        ("shift", 2),
        ("use_tick_volume", True),
        ("point", 0.01),
    )

    def __init__(self):
        """Reserve the warm-up window for the shifted weighted levels."""
        self.addminperiod(int(self.p.length) + int(self.p.shift) + 3)

    def _weighted_level(self, series_name, ago=0):
        length = int(self.p.length)
        weights = []
        total = 0.0
        for i in range(length):
            idx = ago + i
            vol = (
                float(self.data.volume[-idx])
                if self.p.use_tick_volume
                else float(self.data.openinterest[-idx])
            )
            weights.append(max(vol, 0.0))
            total += max(vol, 0.0)
        if total == 0.0:
            return float(getattr(self.data, series_name)[-ago])
        value = 0.0
        for i in range(length):
            idx = ago + i
            value += float(getattr(self.data, series_name)[-idx]) * (weights[i] / total)
        step = float(self.p.point) * (10 ** int(self.p.digit))
        return round(value / step) * step if step else value

    def next(self):
        """Set the band color from close breaks of the weighted levels."""
        shift = int(self.p.shift)
        up = self._weighted_level("high", shift)
        dn = self._weighted_level("low", shift)
        close = float(self.data.close[0])
        open_ = float(self.data.open[0])
        color = 2.0
        if close > up:
            color = 4.0 if open_ < close else 3.0
        if close < dn:
            color = 0.0 if open_ > close else 1.0
        self.lines.color[0] = color
