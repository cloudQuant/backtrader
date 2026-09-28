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
    StandardDeviation,
    WeightedMovingAverage,
)

__all__ = [
    "CorrectedAverageIndicator",
]


def resolve_ma_class(name):
    """Return the backtrader moving-average class for a method name.

    Args:
        name: MA method name (sma, ema, smma, or a weighted fallback).

    Returns:
        The corresponding backtrader moving-average indicator class.
    """
    mode = str(name).lower()
    if mode in {"sma", "mode_sma"}:
        return SimpleMovingAverage
    if mode in {"ema", "mode_ema"}:
        return ExponentialMovingAverage
    if mode in {"smma", "mode_smma"}:
        return SmoothedMovingAverage
    return WeightedMovingAverage


def resolve_price_line(data, mode):
    """Return the price line selected by an MT5 applied-price mode.

    Args:
        data: The data feed providing OHLC lines.
        mode: Applied-price mode name (e.g. ``price_close``, ``price_median``).

    Returns:
        The line or line expression for the requested applied price; defaults
        to the close line for unrecognized modes.
    """
    price_mode = str(mode).lower()
    if price_mode in {"price_open", "open"}:
        return data.open
    if price_mode in {"price_high", "high"}:
        return data.high
    if price_mode in {"price_low", "low"}:
        return data.low
    if price_mode in {"price_median", "median"}:
        return (data.high + data.low) / 2.0
    if price_mode in {"price_typical", "typical"}:
        return (data.high + data.low + data.close) / 3.0
    if price_mode in {"price_weighted", "weighted"}:
        return (data.high + data.low + data.close + data.close) / 4.0
    return data.close


class CorrectedAverageIndicator(Indicator):
    """Ehlers-style adaptive Corrected Average with event and vectorized modes."""

    lines = ("corrected",)
    params = (
        ("ma_method", "sma"),
        ("length", 12),
        ("applied_price", "price_close"),
    )

    def __init__(self):
        """Build the base MA and standard deviation and set the min period."""
        price_line = resolve_price_line(self.data, self.p.applied_price)
        self._ma = resolve_ma_class(self.p.ma_method)(price_line, period=self.p.length)
        self._std = StandardDeviation(price_line, period=self.p.length)
        self.addminperiod(int(self.p.length) + 3)

    def next(self):
        """Compute the corrected average for the current bar."""
        ma = float(self._ma[0])
        std = float(self._std[0])
        prev = float(self.lines.corrected[-1]) if len(self) > 0 else ma
        if prev != prev:
            prev = ma
        v1 = std**2
        v2 = (prev - ma) ** 2
        if v2 < v1 or v2 == 0:
            k = 0.0
        else:
            k = 1.0 - v1 / v2
        self.lines.corrected[0] = prev + k * (ma - prev)

    def once(self, start, end):
        """Vectorized corrected-average computation over the array index range.

        Args:
            start: Start index (inclusive) of the range to compute.
            end: End index (exclusive) of the range to compute.
        """
        ma_array = self._ma.array
        std_array = self._std.array
        corrected_line = self.lines.corrected.array
        while len(corrected_line) < end:
            corrected_line.append(float("nan"))

        prev = None
        actual_end = min(end, len(ma_array), len(std_array))
        for i in range(start, actual_end):
            ma = float(ma_array[i])
            std = float(std_array[i])
            previous = ma if prev is None else prev
            v1 = std**2
            v2 = (previous - ma) ** 2
            if v2 < v1 or v2 == 0:
                k = 0.0
            else:
                k = 1.0 - v1 / v2
            value = previous + k * (ma - previous)
            corrected_line[i] = value
            prev = value
