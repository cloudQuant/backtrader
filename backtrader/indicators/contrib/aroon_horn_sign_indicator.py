#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import Indicator

__all__ = [
    "AroonHornSignIndicator",
]


class AroonHornSignIndicator(Indicator):
    """Reconstructs AroonHornSign indicator.

    BULLS = 100 - (bars_since_highest_high + 0.5) * 100 / AroonPeriod
    BEARS = 100 - (bars_since_lowest_low + 0.5) * 100 / AroonPeriod
    trend = +1 if BULLS > BEARS and BULLS >= 50
    trend = -1 if BULLS < BEARS and BEARS >= 50
    BullsAroon (buy arrow) when trend flips from -1 to +1: low - ATR*3/8
    BearsAroon (sell arrow) when trend flips from +1 to -1: high + ATR*3/8
    Buffers: 0=BearsAroon(sell), 1=BullsAroon(buy).
    """

    lines = ("bears_aroon", "bulls_aroon")
    params = (
        ("aroon_period", 9),
        ("atr_period", 10),
    )

    def __init__(self):
        """Initialize Aroon window, ATR window, and trend tracking state."""
        self._ap = int(self.p.aroon_period)
        self._atr_p = int(self.p.atr_period)
        self._trend_prev = 0
        self.addminperiod(max(self._ap, self._atr_p) + 3)

    def _calc_atr(self):
        period = self._atr_p
        total = 0.0
        for i in range(period):
            h = float(self.data.high[-i])
            low_price = float(self.data.low[-i])
            if i + 1 < len(self.data):
                pc = float(self.data.close[-(i + 1)])
                tr = max(h - low_price, abs(h - pc), abs(low_price - pc))
            else:
                tr = h - low_price
            total += tr
        return total / period

    def next(self):
        """Compute bear/bull arrow levels based on trend flips and ATR displacement."""
        ap = self._ap

        # Find bars since highest high and lowest low within AroonPeriod
        max_idx = 0
        max_val = float(self.data.high[0])
        min_idx = 0
        min_val = float(self.data.low[0])
        for i in range(ap):
            h = float(self.data.high[-i])
            low_price = float(self.data.low[-i])
            if h > max_val:
                max_val = h
                max_idx = i
            if low_price < min_val:
                min_val = low_price
                min_idx = i

        bulls = 100.0 - (max_idx + 0.5) * 100.0 / ap
        bears = 100.0 - (min_idx + 0.5) * 100.0 / ap

        trend = self._trend_prev
        if bulls > bears and bulls >= 50:
            trend = 1
        if bulls < bears and bears >= 50:
            trend = -1

        bu = 0.0
        be = 0.0

        if self._trend_prev < 0 and trend > 0:
            atr = self._calc_atr()
            bu = float(self.data.low[0]) - atr * 3.0 / 8.0

        if self._trend_prev > 0 and trend < 0:
            atr = self._calc_atr()
            be = float(self.data.high[0]) + atr * 3.0 / 8.0

        self._trend_prev = trend

        self.lines.bears_aroon[0] = be
        self.lines.bulls_aroon[0] = bu
