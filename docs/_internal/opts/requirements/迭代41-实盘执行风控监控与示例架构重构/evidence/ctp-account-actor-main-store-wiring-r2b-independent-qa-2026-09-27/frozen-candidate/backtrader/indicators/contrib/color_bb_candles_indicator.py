#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import (
    EMA,
    SMA,
    Indicator,
    StandardDeviation,
)

__all__ = [
    "ColorBBCandlesIndicator",
]


class ColorBBCandlesIndicator(Indicator):
    """Color BBCandles indicator producing zone states from volatility envelopes.

    The indicator computes a moving-average center line and standard deviation
    bands with multiple deviation levels, then emits a discrete state 0..10.
    """

    lines = (
        "state",
        "price_line",
        "mid",
    )
    params = (
        ("period", 100),
        ("deviation1", 1.0),
        ("deviation2", 1.5),
        ("deviation3", 2.0),
        ("deviation4", 2.5),
        ("deviation5", 3.0),
        ("ma_method", "ema"),
        ("applied_price", "close"),
    )

    def __init__(self):
        """Prepare price line selector and required indicator buffers."""
        ma_cls = EMA if str(self.p.ma_method).lower() == "ema" else SMA
        self.price = self._price_line()
        self.lines.price_line = self.price
        self.lines.mid = ma_cls(self.price, period=self.p.period)
        self.stddev = StandardDeviation(self.price, period=self.p.period)
        self.addminperiod(self.p.period + 5)

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
        """Evaluate the current bar and emit the normalized volatility state."""
        price = float(self.price[0])
        mid = float(self.lines.mid[0])
        stdev = float(self.stddev[0])
        up1 = mid + stdev * self.p.deviation1
        up2 = mid + stdev * self.p.deviation2
        up3 = mid + stdev * self.p.deviation3
        up4 = mid + stdev * self.p.deviation4
        up5 = mid + stdev * self.p.deviation5
        dn1 = mid - stdev * self.p.deviation1
        dn2 = mid - stdev * self.p.deviation2
        dn3 = mid - stdev * self.p.deviation3
        dn4 = mid - stdev * self.p.deviation4
        dn5 = mid - stdev * self.p.deviation5
        state = 5.0
        if price > up5:
            state = 10.0
        elif price > up4:
            state = 9.0
        elif price > up3:
            state = 8.0
        elif price > up2:
            state = 7.0
        elif price > up1:
            state = 6.0
        elif price < dn5:
            state = 0.0
        elif price < dn4:
            state = 1.0
        elif price < dn3:
            state = 2.0
        elif price < dn2:
            state = 3.0
        elif price < dn1:
            state = 4.0
        self.lines.state[0] = state
