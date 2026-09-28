#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

import math

from .. import Indicator

__all__ = [
    "KalmanFilterIndicator",
]


APPLIED_PRICE_MAP = {
    "PRICE_CLOSE": 0,
    "PRICE_OPEN": 1,
    "PRICE_HIGH": 2,
    "PRICE_LOW": 3,
    "PRICE_MEDIAN": 4,
    "PRICE_TYPICAL": 5,
    "PRICE_WEIGHTED": 6,
    "PRICE_OPEN_CLOSE": 8,
    "PRICE_OHLC_AVERAGE": 9,
    "PRICE_DEMARK": 10,
    "PRICE_AVERAGE_DEMARK": 11,
}


SIGNAL_MODE_MAP = {
    "Trend": 0,
    "Kalman": 1,
}


class KalmanFilterIndicator(Indicator):
    """Kalman-style adaptive price filter producing value and direction lines."""

    lines = ("value", "color_idx")
    params = (
        ("k", 1.0),
        ("applied_price", "PRICE_WEIGHTED"),
        ("signal_mode", "Kalman"),
        ("price_shift", 0),
        ("point", 0.01),
    )

    def __init__(self):
        """Initialize internal state and precompute coefficients."""
        self.addminperiod(2)
        self._velocity = 0.0
        self._sqrt100 = math.sqrt(float(self.p.k) / 100.0) if float(self.p.k) > 0 else 0.0
        self._k100 = float(self.p.k) / 100.0
        self._price_shift = float(self.p.point) * float(self.p.price_shift)

    def _mode_value(self, mapping, value, default_value):
        if isinstance(value, str):
            return mapping.get(value, default_value)
        return int(value)

    def _price(self, ago=0):
        mode = self._mode_value(APPLIED_PRICE_MAP, self.p.applied_price, 0)
        open_ = float(self.data.open[ago])
        high = float(self.data.high[ago])
        low = float(self.data.low[ago])
        close = float(self.data.close[ago])
        if mode == 0:
            return close
        if mode == 1:
            return open_
        if mode == 2:
            return high
        if mode == 3:
            return low
        if mode == 4:
            return (high + low) / 2.0
        if mode == 5:
            return (close + high + low) / 3.0
        if mode == 6:
            return (2.0 * close + high + low) / 4.0
        if mode == 8:
            return (open_ + close) / 2.0
        if mode == 9:
            return (open_ + close + high + low) / 4.0
        if mode == 10:
            if close > open_:
                return high
            if close < open_:
                return low
            return close
        if mode == 11:
            if close > open_:
                return (high + close) / 2.0
            if close < open_:
                return (low + close) / 2.0
            return close
        return close

    def next(self):
        """Update the filtered value and direction for each bar."""
        price = self._price(0)
        if len(self) == 1:
            self.lines.value[0] = price
            self.lines.color_idx[0] = 0.0
            self._velocity = 0.0
            return
        prev_value = float(self.lines.value[-1])
        distance = price - prev_value
        error = prev_value + distance * self._sqrt100
        self._velocity += distance * self._k100
        value = error + self._velocity + self._price_shift
        self.lines.value[0] = value
        signal_mode = self._mode_value(SIGNAL_MODE_MAP, self.p.signal_mode, 1)
        if signal_mode == 0:
            self.lines.color_idx[0] = 0.0 if prev_value > value else 1.0
        else:
            self.lines.color_idx[0] = 1.0 if self._velocity > 0 else 0.0
