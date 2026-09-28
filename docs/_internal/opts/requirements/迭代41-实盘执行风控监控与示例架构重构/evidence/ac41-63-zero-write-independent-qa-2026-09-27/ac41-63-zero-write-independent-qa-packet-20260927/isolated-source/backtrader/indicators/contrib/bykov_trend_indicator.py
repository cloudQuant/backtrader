#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import Indicator

__all__ = [
    "BykovTrendIndicator",
]


class BykovTrendIndicator(Indicator):
    """Reconstructs BykovTrend from its MQ5 source.

    Uses WPR(SSP) + ATR(15) to detect trend flips.
    Outputs buy_arrow / sell_arrow (non-zero price level when arrow fires).
    """

    lines = ("buy_arrow", "sell_arrow")
    params = (
        ("risk", 3),
        ("ssp", 9),
    )

    def __init__(self):
        """Cache WPR/ATR periods, the risk threshold, and set indicator warmup."""
        self._k = 33 - int(self.p.risk)
        self._atr_period = 15
        self._wpr_period = int(self.p.ssp)
        self._uptrend = True
        self._old = True
        self.addminperiod(max(self._wpr_period, self._atr_period) + 2)

    def _calc_wpr(self):
        period = self._wpr_period
        if len(self.data) < period:
            return 0.0
        hh = max(float(self.data.high[-i]) for i in range(period))
        ll = min(float(self.data.low[-i]) for i in range(period))
        close_val = float(self.data.close[0])
        if hh == ll:
            return 0.0
        return -100.0 * (hh - close_val) / (hh - ll)

    def _calc_atr(self):
        period = self._atr_period
        if len(self.data) < period + 1:
            return 0.0
        total = 0.0
        for i in range(period):
            hi = float(self.data.high[-i])
            lo = float(self.data.low[-i])
            prev_close = float(self.data.close[-(i + 1)])
            tr = max(hi - lo, abs(hi - prev_close), abs(prev_close - lo))
            total += tr
        return total / period

    def next(self):
        """Update the trend state and emit buy/sell arrow offsets on flips."""
        k = self._k
        wpr = self._calc_wpr()
        atr = self._calc_atr()
        rng = atr * 3.0 / 8.0

        uptrend = self._uptrend
        if wpr < -100 + k:
            uptrend = False
        if wpr > -k:
            uptrend = True

        buy_val = 0.0
        sell_val = 0.0
        if not self._old and uptrend:
            buy_val = float(self.data.low[0]) - rng
        if self._old and not uptrend:
            sell_val = float(self.data.high[0]) + rng

        self.lines.buy_arrow[0] = buy_val
        self.lines.sell_arrow[0] = sell_val

        self._old = uptrend
        self._uptrend = uptrend
