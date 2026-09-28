#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import (
    EMA,
    SMA,
    Indicator,
)

__all__ = [
    "XMACDIndicator",
]


class XMACDIndicator(Indicator):
    """Configurable MACD indicator with selectable MA methods and price.

    Computes the MACD line as the difference of a fast and slow moving average
    of a chosen applied price, then a signal line by smoothing the MACD. The
    moving-average type, signal-smoothing type, periods and applied price are all
    configurable via parameters.
    """

    lines = (
        "macd",
        "signal",
    )
    params = (
        ("ma_method", "ema"),
        ("signal_method", "sma"),
        ("fast_period", 12),
        ("slow_period", 26),
        ("signal_period", 9),
        ("applied_price", "close"),
    )

    def __init__(self):
        """Build the fast/slow MAs, MACD and signal lines and set min period."""
        ma_cls = EMA if str(self.p.ma_method).lower() == "ema" else SMA
        signal_cls = EMA if str(self.p.signal_method).lower() == "ema" else SMA
        price = self._price_line()
        fast = ma_cls(price, period=self.p.fast_period)
        slow = ma_cls(price, period=self.p.slow_period)
        self.lines.macd = fast - slow
        self.lines.signal = signal_cls(self.lines.macd, period=self.p.signal_period)
        self.addminperiod(max(self.p.fast_period, self.p.slow_period) + self.p.signal_period + 5)

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
