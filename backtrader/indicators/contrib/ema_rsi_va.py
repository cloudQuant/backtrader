#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

import math

from .. import (
    RSI,
    Indicator,
)

__all__ = [
    "EmaRsiVa",
]


class EmaRsiVa(Indicator):
    """Volatility-adaptive EMA whose smoothing reacts to RSI distance from 50."""

    lines = ("value",)
    params = (
        ("rsi_period", 14),
        ("ema_periods", 14.0),
        ("applied_price", "close"),
    )

    def __init__(self):
        """Resolve the applied price line, build RSI, and set warmup period."""
        self.price_line = self._resolve_price_line()
        self.rsi = RSI(self.price_line, period=self.p.rsi_period)
        self.addminperiod(max(2, int(self.p.rsi_period) * 2))

    def _resolve_price_line(self):
        ap = str(self.p.applied_price).lower()
        if ap in ("close", "price_close"):
            return self.data.close
        if ap in ("open", "price_open"):
            return self.data.open
        if ap in ("high", "price_high"):
            return self.data.high
        if ap in ("low", "price_low"):
            return self.data.low
        if ap in ("median", "price_median"):
            return (self.data.high + self.data.low) / 2.0
        if ap in ("typical", "price_typical"):
            return (self.data.high + self.data.low + self.data.close) / 3.0
        if ap in ("weighted", "price_weighted"):
            return (self.data.high + self.data.low + self.data.close * 2.0) / 4.0
        return self.data.close

    def next(self):
        """Update the adaptive EMA line using the RSI-modulated smoothing factor."""
        price = float(self.price_line[0])
        if len(self) == int(self.p.rsi_period) * 2:
            self.lines.value[0] = price
            return

        rsi_value = float(self.rsi[0]) if len(self.rsi) else float("nan")
        if not math.isfinite(rsi_value):
            prev = (
                float(self.lines.value[-1]) if math.isfinite(float(self.lines.value[-1])) else price
            )
            self.lines.value[0] = prev
            return

        rsvoltl = abs(rsi_value - 50.0) + 1.0
        multi = (5.0 + 100.0 / float(self.p.rsi_period)) / (
            0.06 + 0.92 * rsvoltl + 0.02 * rsvoltl**2
        )
        pdsx = max(1.0, multi * float(self.p.ema_periods))
        alpha = 2.0 / (pdsx + 1.0)

        prev_value = float(self.lines.value[-1])
        if not math.isfinite(prev_value):
            prev_value = float(self.price_line[-1])

        self.lines.value[0] = price * alpha + prev_value * (1.0 - alpha)
