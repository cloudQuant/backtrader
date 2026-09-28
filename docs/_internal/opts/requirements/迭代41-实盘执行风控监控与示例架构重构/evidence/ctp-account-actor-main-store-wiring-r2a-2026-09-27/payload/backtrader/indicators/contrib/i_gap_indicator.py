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
    "IGapIndicator",
]


class IGapIndicator(Indicator):
    """Detect opening gaps and emit ATR-offset buy/sell arrow levels."""

    lines = ("sell_signal", "buy_signal", "atr_value")
    params = (
        ("size_gap", 5),
        ("point", 0.01),
        ("atr_period", 15),
    )

    def __init__(self):
        """Set the warm-up period, build the ATR, and cache the gap distance."""
        self.addminperiod(int(self.p.atr_period) + int(self.p.size_gap) + 4)
        self.atr = ATR(self.data, period=int(self.p.atr_period))
        self.gap_distance = float(self.p.size_gap) * float(self.p.point)

    def next(self):
        """Emit buy/sell arrow levels when the prior close gaps past the open."""
        self.lines.sell_signal[0] = 0.0
        self.lines.buy_signal[0] = 0.0
        atr_value = float(self.atr[0])
        self.lines.atr_value[0] = atr_value
        if len(self.data) < 2:
            return
        if float(self.data.close[-1]) > float(self.data.open[0]) + self.gap_distance:
            self.lines.buy_signal[0] = float(self.data.low[0]) - atr_value * 3.0 / 8.0
        if float(self.data.close[-1]) < float(self.data.open[0]) - self.gap_distance:
            self.lines.sell_signal[0] = float(self.data.high[0]) + atr_value * 3.0 / 8.0
