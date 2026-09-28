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
    "IDeMarkerSignIndicator",
]


class IDeMarkerSignIndicator(Indicator):
    """DeMarker oscillator that emits buy/sell triggers on level crossings."""

    lines = ("sell", "buy", "demarker", "atr")
    params = (
        ("atr_period", 14),
        ("demarker_period", 14),
        ("up_level", 0.7),
        ("dn_level", 0.3),
    )

    def __init__(self):
        """Build the ATR sub-indicator and set the minimum warmup period."""
        self._atr = ATR(self.data, period=int(self.p.atr_period))
        self.addminperiod(max(int(self.p.atr_period), int(self.p.demarker_period) + 1) + 2)

    def _calc_demarker(self):
        period = int(self.p.demarker_period)
        demax_sum = 0.0
        demin_sum = 0.0
        for i in range(period):
            high0 = float(self.data.high[-i])
            high1 = float(self.data.high[-(i + 1)])
            low0 = float(self.data.low[-i])
            low1 = float(self.data.low[-(i + 1)])
            demax_sum += max(high0 - high1, 0.0)
            demin_sum += max(low1 - low0, 0.0)
        denom = demax_sum + demin_sum
        if denom == 0.0:
            return 0.5
        return demax_sum / denom

    def next(self):
        """Compute the DeMarker value and set buy/sell triggers on crossings."""
        self.lines.sell[0] = float("nan")
        self.lines.buy[0] = float("nan")
        demarker_now = self._calc_demarker()
        self.lines.demarker[0] = demarker_now
        self.lines.atr[0] = float(self._atr[0])
        if len(self) < 2:
            return
        demarker_prev = float(self.lines.demarker[-1])
        atr_now = float(self._atr[0])
        if demarker_now > float(self.p.dn_level) and demarker_prev <= float(self.p.dn_level):
            self.lines.buy[0] = float(self.data.low[0]) - atr_now * 3.0 / 8.0
        if demarker_now < float(self.p.up_level) and demarker_prev >= float(self.p.up_level):
            self.lines.sell[0] = float(self.data.high[0]) + atr_now * 3.0 / 8.0
