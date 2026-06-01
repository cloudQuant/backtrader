#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

import math

from .. import (
    ExponentialMovingAverage,
    Indicator,
    SimpleMovingAverage,
    SmoothedMovingAverage,
    WeightedMovingAverage,
)

__all__ = [
    "GOIndicator",
]


class GOIndicator(Indicator):
    """Indicator that derives a GO signal from smoothed OHLC components."""

    lines = ("go",)
    params = (
        ("period", 174),
        ("ma_method", "SMA"),
    )

    def __init__(self):
        """Build MA buffers for OHLC input series and warmup period.

        Args:
            None.

        Returns:
            None.

        Side effects:
            Creates ``ma_open``, ``ma_high``, ``ma_low``, ``ma_close`` lines.
        """
        ma_cls = {
            "SMA": SimpleMovingAverage,
            "EMA": ExponentialMovingAverage,
            "SMMA": SmoothedMovingAverage,
            "WMA": WeightedMovingAverage,
        }.get(str(self.p.ma_method).upper(), SimpleMovingAverage)
        self.ma_open = ma_cls(self.data.open, period=self.p.period)
        self.ma_high = ma_cls(self.data.high, period=self.p.period)
        self.ma_low = ma_cls(self.data.low, period=self.p.period)
        self.ma_close = ma_cls(self.data.close, period=self.p.period)
        self.addminperiod(int(self.p.period) + 1)

    def _calc_go(self, ma_open, ma_high, ma_low, ma_close, volume):
        values = (ma_open, ma_high, ma_low, ma_close, volume)
        if not all(math.isfinite(float(v)) for v in values):
            return 0.0
        return (
            (ma_close - ma_open)
            + (ma_high - ma_open)
            + (ma_low - ma_open)
            + (ma_close - ma_low)
            + (ma_close - ma_high)
        ) * volume

    def next(self):
        """Compute GO for current bar and publish it to ``lines.go``."""
        self.lines.go[0] = self._calc_go(
            float(self.ma_open[0]),
            float(self.ma_high[0]),
            float(self.ma_low[0]),
            float(self.ma_close[0]),
            float(self.data.volume[0]),
        )

    def once(self, start, end):
        """Compute GO for buffered bars in run-once mode."""
        ma_open = self.ma_open.array
        ma_high = self.ma_high.array
        ma_low = self.ma_low.array
        ma_close = self.ma_close.array
        volume = self.data.volume.array
        go = self.lines.go.array
        for i in range(start, end):
            go[i] = self._calc_go(
                float(ma_open[i]),
                float(ma_high[i]),
                float(ma_low[i]),
                float(ma_close[i]),
                float(volume[i]),
            )
