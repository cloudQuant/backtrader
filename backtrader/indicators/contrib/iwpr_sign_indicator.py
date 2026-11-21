#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

import math

from .. import (
    ATR,
    Indicator,
)

__all__ = [
    "IWPRSignIndicator",
]


class IWPRSignIndicator(Indicator):
    """WPR buy/sell levels with ATR; incomplete WPR price windows yield NaN."""

    lines = ("sell", "buy", "wpr", "atr")
    params = (
        ("atr_period", 14),
        ("wpr_period", 14),
        ("up_level", -30),
        ("dn_level", -70),
    )

    def __init__(self):
        """Initialize ATR source and required lookback."""
        self._atr = ATR(self.data, period=int(self.p.atr_period))
        self.addminperiod(max(int(self.p.atr_period), int(self.p.wpr_period)) + 2)

    def _calc_wpr(self):
        period = int(self.p.wpr_period)
        highs = [float(self.data.high[-i]) for i in range(period)]
        lows = [float(self.data.low[-i]) for i in range(period)]
        hh = max(highs)
        ll = min(lows)
        cp = float(self.data.close[0])
        # Python max/min can ignore NaN after the first element; do not
        # classify an incomplete window as though its extrema were known.
        if not math.isfinite(cp) or not all(math.isfinite(v) for v in highs + lows):
            return float("nan")
        if hh == ll:
            return -50.0
        return -100.0 * (hh - cp) / (hh - ll)

    def next(self):
        """Compute WPR and create buy/sell trigger levels."""
        self.lines.sell[0] = float("nan")
        self.lines.buy[0] = float("nan")
        wpr_now = self._calc_wpr()
        self.lines.wpr[0] = wpr_now
        self.lines.atr[0] = float(self._atr[0])
        if len(self) < 2:
            return
        wpr_prev = float(self.lines.wpr[-1])
        atr_now = float(self._atr[0])
        if wpr_now > float(self.p.dn_level) and wpr_prev <= float(self.p.dn_level):
            self.lines.buy[0] = float(self.data.low[0]) - atr_now * 3.0 / 8.0
        if wpr_now < float(self.p.up_level) and wpr_prev >= float(self.p.up_level):
            self.lines.sell[0] = float(self.data.high[0]) + atr_now * 3.0 / 8.0
