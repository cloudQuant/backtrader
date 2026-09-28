#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import (
    ExponentialMovingAverage,
    Indicator,
    SimpleMovingAverage,
    SmoothedMovingAverage,
    WeightedMovingAverage,
)

__all__ = [
    "CenterOfGravityCandleIndicator",
]


class CenterOfGravityCandleIndicator(Indicator):
    """Center-of-Gravity Candle indicator exposing center, signal, and state lines."""

    lines = ("center", "signal", "state")
    params = (
        ("period", 10),
        ("smooth_period", 3),
        ("ma_method", "sma"),
        ("applied_price", "close"),
        ("point", 0.01),
    )

    def __init__(self):
        """Build the center, signal, and warmup period from the applied price.

        Side effects:
            Computes ``center`` as the point-scaled product of an SMA and a LWMA
            of the applied price, derives ``signal`` by smoothing ``center``, and
            sets the minimum warmup period.
        """
        ma_cls = self._ma_class()
        price = self._price_line()
        sma = SimpleMovingAverage(price, period=self.p.period)
        lwma = WeightedMovingAverage(price, period=self.p.period)
        self.lines.center = (sma * lwma) / self.p.point
        self.lines.signal = ma_cls(self.lines.center, period=self.p.smooth_period)
        self.addminperiod(self.p.period + self.p.smooth_period + 5)

    def _ma_class(self):
        mode = str(self.p.ma_method).lower()
        if mode in {"ema", "mode_ema"}:
            return ExponentialMovingAverage
        if mode in {"smma", "smoothed", "mode_smma"}:
            return SmoothedMovingAverage
        if mode in {"lwma", "wma", "mode_lwma"}:
            return WeightedMovingAverage
        return SimpleMovingAverage

    def _price_line(self):
        mode = str(self.p.applied_price).lower()
        if mode == "open":
            return self.data.open
        if mode == "high":
            return self.data.high
        if mode == "low":
            return self.data.low
        if mode == "median":
            return (self.data.high + self.data.low) / 2.0
        if mode == "typical":
            return (self.data.high + self.data.low + self.data.close) / 3.0
        if mode == "weighted":
            return (self.data.high + self.data.low + self.data.close + self.data.close) / 4.0
        if mode == "simpl":
            return (self.data.open + self.data.close) / 2.0
        if mode == "quarter":
            return (self.data.high + self.data.low + self.data.open + self.data.close) / 4.0
        return self.data.close

    def next(self):
        """Set ``state`` to 2 when center is above signal, else 0, for the bar."""
        self.lines.state[0] = (
            2.0 if float(self.lines.center[0]) > float(self.lines.signal[0]) else 0.0
        )
