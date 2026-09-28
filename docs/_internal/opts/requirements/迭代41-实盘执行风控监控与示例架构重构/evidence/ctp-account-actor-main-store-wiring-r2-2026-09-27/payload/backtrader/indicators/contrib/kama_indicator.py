#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

import math

from .. import (
    ExponentialMovingAverage,
    Indicator,
)

__all__ = [
    "KAMAIndicator",
    "ColorMomentumAMAIndicator",
]


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
    if price_mode in {"price_simpl", "simpl"}:
        return (data.open + data.close) / 2.0
    if price_mode in {"price_quarter", "quarter"}:
        return (data.high + data.low + data.open + data.close) / 4.0
    return data.close


class KAMAIndicator(Indicator):
    """Kaufman Adaptive Moving Average with both event and vectorized modes."""

    lines = ("ama",)
    params = (
        ("period", 9),
        ("fast_period", 2),
        ("slow_period", 30),
        ("power", 2.0),
    )

    def __init__(self):
        """Set the minimum period required before emitting values."""
        self.addminperiod(max(self.p.period, self.p.slow_period) + 2)

    def next(self):
        """Compute the adaptive moving average for the current bar."""
        period = int(self.p.period)
        current = float(self.data[0])
        prev = float(self.lines.ama[-1]) if len(self) > 0 else current
        if not math.isfinite(prev):
            prev = 0.0
        if not math.isfinite(current):
            self.lines.ama[0] = prev
            return
        if len(self.data) <= period:
            self.lines.ama[0] = current
            return
        change = abs(float(self.data[0]) - float(self.data[-period]))
        volatility = 0.0
        for i in range(period):
            left = float(self.data[-i])
            right = float(self.data[-i - 1])
            if math.isfinite(left) and math.isfinite(right):
                volatility += abs(left - right)
        er = (change / volatility) if volatility else 0.0
        fast_sc = 2.0 / (int(self.p.fast_period) + 1.0)
        slow_sc = 2.0 / (int(self.p.slow_period) + 1.0)
        sc = (er * (fast_sc - slow_sc) + slow_sc) ** float(self.p.power)
        self.lines.ama[0] = prev + sc * (current - prev)

    def once(self, start, end):
        """Vectorized KAMA computation over the array index range.

        Args:
            start: Start index (inclusive) of the range to compute.
            end: End index (exclusive) of the range to compute.
        """
        period = int(self.p.period)
        src = self.data.array
        dst = self.lines.ama.array
        fast_sc = 2.0 / (int(self.p.fast_period) + 1.0)
        slow_sc = 2.0 / (int(self.p.slow_period) + 1.0)
        power = float(self.p.power)
        for i in range(start, end):
            current = float(src[i])
            prev = float(dst[i - 1]) if i > 0 else current
            if not math.isfinite(prev):
                prev = 0.0
            if not math.isfinite(current):
                dst[i] = prev
                continue
            if i <= period:
                dst[i] = current
                continue
            change = abs(current - float(src[i - period]))
            volatility = 0.0
            for j in range(period):
                left = float(src[i - j])
                right = float(src[i - j - 1])
                if math.isfinite(left) and math.isfinite(right):
                    volatility += abs(left - right)
            er = (change / volatility) if volatility else 0.0
            sc = (er * (fast_sc - slow_sc) + slow_sc) ** power
            dst[i] = prev + sc * (current - prev)


class ColorMomentumAMAIndicator(Indicator):
    """EMA-smoothed momentum line used by the ColorMomentum_AMA strategy."""

    lines = ("value",)
    params = (
        ("alength", 8),
        ("ama_period", 9),
        ("fast_ma_period", 2),
        ("slow_ma_period", 30),
        ("ipc", "price_close"),
        ("g", 2.0),
    )

    def __init__(self):
        """Build the EMA-smoothed momentum line and set the minimum period."""
        price_line = resolve_price_line(self.data, self.p.ipc)
        momentum = price_line - price_line(-int(self.p.alength))
        self.lines.value = ExponentialMovingAverage(
            momentum,
            period=max(1, int(self.p.ama_period)),
        )
        self.addminperiod(int(self.p.alength) + int(self.p.ama_period) + 5)
