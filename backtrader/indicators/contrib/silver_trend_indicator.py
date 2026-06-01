#!/usr/bin/env python
"""Functional-test indicators migrated to contrib.

Generated from a single functional strategy module to preserve file-local
helper functions and constants without cross-test name collisions.
"""

from .. import Indicator

__all__ = [
    "SilverTrendIndicator",
]


class SilverTrendIndicator(Indicator):
    """Reconstructs SilverTrend_Signal from its MQ5 source.

    Uses SSP-period average range to compute smin/smax bands.
    K = RISK * 100.
    smin = SsMin + (SsMax - SsMin) * K / 100
    smax = SsMax - (SsMax - SsMin) * K / 100
    Trend toggles: close < smin → downtrend, close > smax → uptrend.
    Buy arrow on uptrend toggle, sell arrow on downtrend toggle.
    """

    lines = ("buy_arrow", "sell_arrow")
    params = (
        ("ssp", 9),
        ("risk", 3),
    )

    def __init__(self):
        """Cache SSP/risk parameters, reset trend state, and set min period."""
        self._ssp = int(self.p.ssp)
        self._k = float(self.p.risk) * 100.0
        self._uptrend = False
        self._old = False
        self.addminperiod(self._ssp + 2)

    def next(self):
        """Update the adaptive bands and emit buy/sell arrows on trend flips."""
        ssp = self._ssp

        # Compute average range over SSP bars
        total_range = 0.0
        for i in range(ssp):
            h = float(self.data.high[-i])
            low_price = float(self.data.low[-i])
            total_range += h - low_price
        avg_range = total_range / ssp
        rng = avg_range

        # SsMax = highest high over SSP bars, SsMin = lowest low
        ss_max = max(float(self.data.high[-i]) for i in range(ssp))
        ss_min = min(float(self.data.low[-i]) for i in range(ssp))

        k = self._k
        smin = ss_min + (ss_max - ss_min) * k / 100.0
        smax = ss_max - (ss_max - ss_min) * k / 100.0

        cur_close = float(self.data.close[0])

        if cur_close < smin:
            self._uptrend = False
        if cur_close > smax:
            self._uptrend = True

        buy_val = 0.0
        sell_val = 0.0

        if self._uptrend != self._old and self._uptrend:
            buy_val = float(self.data.low[0]) - rng * 0.5
        if self._uptrend != self._old and not self._uptrend:
            sell_val = float(self.data.high[0]) + rng * 0.5

        self._old = self._uptrend

        self.lines.buy_arrow[0] = buy_val
        self.lines.sell_arrow[0] = sell_val
