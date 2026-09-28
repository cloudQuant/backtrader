#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import (
    ATR,
    Indicator,
)

__all__ = [
    "IRSISignIndicator",
]


def _applied_price(data, price_type, ago=0):
    """Resolve applied price by type and history shift."""
    o = float(data.open[-ago])
    h = float(data.high[-ago])
    low_price = float(data.low[-ago])
    c = float(data.close[-ago])
    if price_type == 0:
        return c
    if price_type == 1:
        return o
    if price_type == 2:
        return h
    if price_type == 3:
        return low_price
    if price_type == 4:
        return (h + low_price) / 2.0
    if price_type == 5:
        return (h + low_price + c) / 3.0
    if price_type == 6:
        return (h + low_price + c + c) / 4.0
    return c


class IRSISignIndicator(Indicator):
    """Compute RSI sign-flip levels and adaptive ATR-adjusted marker lines."""

    lines = ("sell", "buy", "rsi", "atr")
    params = (
        ("atr_period", 14),
        ("rsi_period", 14),
        ("rsi_price", 0),
        ("up_level", 70),
        ("dn_level", 30),
    )

    def __init__(self):
        """Initialize ATR series and minimum required history."""
        self._atr = ATR(self.data, period=int(self.p.atr_period))
        self.addminperiod(max(int(self.p.atr_period), int(self.p.rsi_period)) + 2)

    def _calc_rsi(self):
        """Calculate RSI manually from configured applied prices."""
        period = int(self.p.rsi_period)
        gains = []
        losses = []
        for i in range(period):
            p0 = _applied_price(self.data, int(self.p.rsi_price), i)
            p1 = _applied_price(self.data, int(self.p.rsi_price), i + 1)
            delta = p0 - p1
            gains.append(max(delta, 0.0))
            losses.append(max(-delta, 0.0))
        avg_gain = sum(gains) / period if period else 0.0
        avg_loss = sum(losses) / period if period else 0.0
        if avg_loss == 0.0:
            return 100.0 if avg_gain > 0.0 else 50.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def next(self):
        """Update buy/sell marker levels and RSI / ATR output lines."""
        self.lines.sell[0] = float("nan")
        self.lines.buy[0] = float("nan")
        rsi_now = self._calc_rsi()
        self.lines.rsi[0] = rsi_now
        self.lines.atr[0] = float(self._atr[0])

        if len(self) < 2:
            return

        rsi_prev = float(self.lines.rsi[-1])
        atr_now = float(self._atr[0])
        low_now = float(self.data.low[0])
        high_now = float(self.data.high[0])

        if rsi_now > float(self.p.dn_level) and rsi_prev <= float(self.p.dn_level):
            self.lines.buy[0] = low_now - atr_now * 3.0 / 8.0
        if rsi_now < float(self.p.up_level) and rsi_prev >= float(self.p.up_level):
            self.lines.sell[0] = high_now + atr_now * 3.0 / 8.0
