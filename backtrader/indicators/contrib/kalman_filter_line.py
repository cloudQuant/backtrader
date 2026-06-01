#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

import math

from .. import Indicator

__all__ = [
    "KalmanFilterLine",
    "KalmanFilterCandleIndicator",
]


def weighted_price(data, ago=0):
    """Return the weighted price ``(high + low + 2*close) / 4`` for a bar.

    Args:
        data: Data feed exposing high/low/close lines.
        ago: Bar offset (0 is the current bar).

    Returns:
        The weighted price as a float.
    """
    return (float(data.high[ago]) + float(data.low[ago]) + 2.0 * float(data.close[ago])) / 4.0


def indicator_source_price(data, ago=0):
    """Return the indicator source price for a bar or scalar line.

    Args:
        data: Data feed with OHLC lines, or a single value line.
        ago: Bar offset (0 is the current bar).

    Returns:
        The weighted price when OHLC lines are present, otherwise the line's
        value at ``ago``.
    """
    if all(hasattr(data, attr) for attr in ("high", "low", "close")):
        return weighted_price(data, ago)
    return float(data[ago])


class KalmanFilterLine(Indicator):
    """Single-series Kalman-style adaptive filter with a velocity term."""

    lines = ("value", "color")
    params = (
        ("k", 1.0),
        ("price_shift_points", 0.0),
    )

    def __init__(self):
        """Set the minimum period and initialize filter state."""
        self.addminperiod(2)
        self._initialized = False
        self._velocity = 0.0
        self.sqrt100 = math.sqrt(float(self.p.k) / 100.0)
        self.k100 = float(self.p.k) / 100.0

    def next(self):
        """Advance the filter one bar and emit the value and color lines."""
        source_price = indicator_source_price(self.data, 0)
        if not self._initialized:
            self.lines.value[0] = source_price + float(self.p.price_shift_points)
            self.lines.color[0] = 0
            self._velocity = 0.0
            self._initialized = True
            return
        prev_value = float(self.lines.value[-1]) - float(self.p.price_shift_points)
        distance = source_price - prev_value
        error = prev_value + distance * self.sqrt100
        self._velocity += distance * self.k100
        filtered = error + self._velocity + float(self.p.price_shift_points)
        self.lines.value[0] = filtered
        self.lines.color[0] = 1 if self._velocity > 0 else 0


class KalmanFilterCandleIndicator(Indicator):
    """Builds Kalman-filtered OHLC candles and a bull/bear color line."""

    lines = ("k_open", "k_high", "k_low", "k_close", "color")
    params = (
        ("k", 1.0),
        ("point", 0.01),
        ("price_shift", 0),
    )

    def __init__(self):
        """Construct per-OHLC Kalman filter lines and set the minimum period."""
        price_shift_points = float(self.p.point) * float(self.p.price_shift)
        self.k_open_line = KalmanFilterLine(
            self.data.open, k=self.p.k, price_shift_points=price_shift_points
        )
        self.k_high_line = KalmanFilterLine(
            self.data.high, k=self.p.k, price_shift_points=price_shift_points
        )
        self.k_low_line = KalmanFilterLine(
            self.data.low, k=self.p.k, price_shift_points=price_shift_points
        )
        self.k_close_line = KalmanFilterLine(
            self.data.close, k=self.p.k, price_shift_points=price_shift_points
        )
        self.addminperiod(3)

    def next(self):
        """Assemble the filtered candle and classify its bull/bear color."""
        o = float(self.k_open_line.value[0])
        h = max(float(self.k_high_line.value[0]), o)
        low_price = min(float(self.k_low_line.value[0]), o)
        c = float(self.k_close_line.value[0])
        h = max(h, c)
        low_price = min(low_price, c)
        self.lines.k_open[0] = o
        self.lines.k_high[0] = h
        self.lines.k_low[0] = low_price
        self.lines.k_close[0] = c
        if o < c:
            color = 2
        elif o > c:
            color = 0
        else:
            color = 1
        self.lines.color[0] = color
